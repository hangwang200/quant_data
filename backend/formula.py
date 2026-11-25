"""公式因子：用表达式对已有因子做算术 / 逻辑组合。

语法（Python 表达式子集，经 AST 白名单校验，不会执行任意代码）：
  算术   + - * / ** %，括号，数字
  比较   > >= < <= == !=（可链式：10 < pe_ttm < 30）
  逻辑   and or not（也可写 & | ~），以及 a if 条件 else b
  函数   abs log sqrt sign exp
         min(a, b) max(a, b) clip(x, lo, hi) fillna(x, v) where(条件, a, b) isnull(x)
         rank(x)    截面百分位排名 0~1（越大排名越高）
         zscore(x)  截面去极值(3×MAD)标准化
         demean(x)  截面去均值
         ind_rank(x) / ind_zscore(x)  行业内排名 / 行业内标准化
示例
  rank(ep) + rank(roe_ann)                      价值+质量等权排名
  where(pe_ttm > 0, 1 / pe_ttm, 0) * 100        自定义 EP
  (roe_ann > 15) and (dividend_yield > 3)       逻辑条件 → 1 / 0，可作为选股过滤
  zscore(bp) - 0.5 * zscore(vol_60)
逻辑结果为 1.0（真）/ 0.0（假）；任一输入缺失时数值结果为缺失。
"""
from __future__ import annotations

import ast
import re
import time

import numpy as np
import pandas as pd

from backend.factors.build import FACTORS

# 除因子外，公式中还可以引用的行情字段；mkt_ 开头为市场级字段（当日所有股票相同，用于择时）
EXTRA_FIELDS = {
    "close": "收盘价", "pct_chg": "涨跌幅%", "amount": "成交额(元)", "listed_days": "上市天数",
    "is_st": "是否 ST",
    "mkt_amt_top5": "市场：近一周成交额前5%个股占比%", "mkt_sentiment": "市场：情绪指数 0-100",
    "mkt_above_ma20": "市场：站上20日线比例%", "mkt_breadth": "市场：上涨家数占比%", "mkt_amount": "市场：成交额(亿)",
}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_FUNCS = {"abs", "log", "sqrt", "sign", "exp", "min", "max", "clip", "fillna", "where", "isnull",
          "rank", "zscore", "demean", "ind_rank", "ind_zscore"}
_XS_FUNCS = {"rank", "zscore", "demean", "ind_rank", "ind_zscore"}  # 截面函数，需要按日期分组
_ARITY = {"abs": 1, "log": 1, "sqrt": 1, "sign": 1, "exp": 1, "min": 2, "max": 2, "clip": 3, "fillna": 2,
          "where": 3, "isnull": 1, "rank": 1, "zscore": 1, "demean": 1, "ind_rank": 1, "ind_zscore": 1}
# 时间序列函数（融合市场指标用）：窗口 n 为交易日数
_TS_FUNCS = {"abs", "log", "sqrt", "sign", "exp", "min", "max", "clip", "fillna", "where", "isnull",
             "ma", "ema", "ts_rank", "ts_zscore", "ts_max", "ts_min", "ts_std", "diff", "lag", "pct_change"}
_ARITY.update({"ma": 2, "ema": 2, "ts_rank": 2, "ts_zscore": 2, "ts_max": 2, "ts_min": 2, "ts_std": 2,
               "diff": 2, "lag": 2, "pct_change": 2})
_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.BitAnd, ast.BitOr)
_CMPOPS = (ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq)


class FormulaError(ValueError):
    pass


# ---------------- 自定义因子注册表 ----------------
_cache: dict = {"t": 0.0, "rows": {}}


def custom_factors(refresh: bool = False) -> dict[str, dict]:
    """数据库中的公式因子（缓存 5 秒，写入后调用 invalidate）。"""
    if refresh or time.time() - _cache["t"] > 5:
        from backend.db.conn import query_df
        try:
            df = query_df("SELECT name, label, expr, better FROM custom_factor ORDER BY created_at")
        except Exception:  # noqa: BLE001 — 表尚未创建
            df = pd.DataFrame(columns=["name", "label", "expr", "better"])
        _cache["rows"] = {r.name: {"label": r.label or r.name, "group": "自定义", "unit": "", "better": r.better or "high",
                                   "expr": r.expr} for r in df.itertuples()}
        _cache["t"] = time.time()
    return _cache["rows"]


def invalidate():
    _cache["t"] = 0.0


def all_factors() -> dict[str, dict]:
    return {**FACTORS, **custom_factors()}


# ---------------- 解析与校验 ----------------
def _parse(expr: str) -> ast.Expression:
    if not expr or not expr.strip():
        raise FormulaError("公式不能为空")
    if len(expr) > 1000:
        raise FormulaError("公式过长")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"语法错误（第 {e.offset} 个字符附近）") from None
    return tree


def _check(node, names: set, known: set, funcs: set = _FUNCS):
    if isinstance(node, ast.Expression):
        return _check(node.body, names, known, funcs)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError(f"不支持的常量: {node.value!r}")
        return
    if isinstance(node, ast.Name):
        if node.id not in known:
            raise FormulaError(f"未知因子或字段: {node.id}")
        names.add(node.id)
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _BINOPS):
            raise FormulaError("不支持的运算符")
        _check(node.left, names, known, funcs)
        _check(node.right, names, known, funcs)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not, ast.Invert)):
            raise FormulaError("不支持的一元运算符")
        return _check(node.operand, names, known, funcs)
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _check(v, names, known, funcs)
        return
    if isinstance(node, ast.Compare):
        if not all(isinstance(o, _CMPOPS) for o in node.ops):
            raise FormulaError("不支持的比较运算符")
        _check(node.left, names, known, funcs)
        for c in node.comparators:
            _check(c, names, known, funcs)
        return
    if isinstance(node, ast.IfExp):
        for v in (node.test, node.body, node.orelse):
            _check(v, names, known, funcs)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in funcs:
            fn = getattr(node.func, "id", "?")
            raise FormulaError(f"不支持的函数: {fn}（可用：{', '.join(sorted(funcs))}）")
        if node.keywords or len(node.args) != _ARITY[node.func.id]:
            raise FormulaError(f"{node.func.id}() 需要 {_ARITY[node.func.id]} 个参数")
        for a in node.args:
            _check(a, names, known, funcs)
        return
    raise FormulaError(f"不支持的语法: {type(node).__name__}")


def referenced(expr: str, exclude: str | None = None) -> set[str]:
    """公式直接引用的名字（因子 / 字段 / 其他公式因子）。"""
    known = set(FACTORS) | set(EXTRA_FIELDS) | (set(custom_factors()) - {exclude})
    names: set[str] = set()
    _check(_parse(expr), names, known)
    return names


def validate(expr: str, name: str | None = None) -> set[str]:
    """校验公式并检查循环引用，返回展开后依赖的基础列。"""
    return base_columns([name] if name else [], extra_expr=expr, self_name=name)


def base_columns(names, extra_expr: str | None = None, self_name: str | None = None) -> set[str]:
    """把（可能包含公式因子的）名字列表展开为 factor_daily 中的基础列。"""
    customs = custom_factors()
    out: set[str] = set()

    def visit(n: str, stack: tuple):
        if n in stack:
            raise FormulaError(f"公式循环引用: {' → '.join(stack + (n,))}")
        if n == self_name and extra_expr is not None:
            expr = extra_expr
        elif n in customs:
            expr = customs[n]["expr"]
        else:
            out.add(n)
            return
        for m in referenced(expr, exclude=n):
            visit(m, stack + (n,))

    for n in names:
        visit(n, ())
    if extra_expr is not None and not self_name:
        for m in referenced(extra_expr):
            visit(m, ())
    return out


def needs_industry(expr: str) -> bool:
    return "ind_" in expr


# ---------------- 求值 ----------------
def _num(x):
    if isinstance(x, pd.Series):
        return x.astype(float)
    return x


def _bool(x):
    """数值 → 真值：非零且非缺失为真。"""
    if isinstance(x, pd.Series):
        return x.fillna(0).astype(bool) if x.dtype != bool else x
    return bool(x) and not (isinstance(x, float) and np.isnan(x))


def _as_float(x, nan_mask=None):
    if isinstance(x, pd.Series):
        x = x.astype(float)
        if nan_mask is not None:
            x = x.where(~nan_mask)
        return x
    return float(x)


def _mad_z(x: pd.Series) -> pd.Series:
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    if not np.isfinite(mad) or mad == 0:
        mad = x.std()
    if not mad or not np.isfinite(mad):
        return x * 0.0
    x = x.clip(med - 3 * mad, med + 3 * mad)
    sd = x.std()
    return (x - x.mean()) / (sd if sd and np.isfinite(sd) else 1.0)


class _Evaluator:
    def __init__(self, df: pd.DataFrame, by: str | None):
        self.df = df
        self.by = by if by and by in df.columns and df[by].nunique() > 1 else None
        self.customs = custom_factors()
        self.memo: dict[str, pd.Series] = {}

    def series(self, v):
        return v if isinstance(v, pd.Series) else pd.Series(float(v), index=self.df.index)

    def xs(self, s: pd.Series, fn, keys=None):
        keys = keys if keys is not None else ([self.df[self.by]] if self.by else None)
        if keys is None:
            return fn(s)
        return s.groupby(keys, group_keys=False).transform(fn)

    def name(self, n: str):
        if n in self.memo:
            return self.memo[n]
        if n in self.customs and n not in self.df.columns:
            v = self.series(self.eval(_parse(self.customs[n]["expr"]).body))
        else:
            v = self.df[n].astype(float)
        self.memo[n] = v
        return v

    def eval(self, node):
        if isinstance(node, ast.Constant):
            return np.float64(node.value)  # numpy 标量：1/0 → inf（随后转为缺失），不抛异常
        if isinstance(node, ast.Name):
            return self.name(node.id)
        if isinstance(node, ast.BinOp):
            a, b = self.eval(node.left), self.eval(node.right)
            op = node.op
            if isinstance(op, ast.BitAnd):
                return self._logic(a, b, "and")
            if isinstance(op, ast.BitOr):
                return self._logic(a, b, "or")
            with np.errstate(all="ignore"):
                if isinstance(op, ast.Add):
                    r = a + b
                elif isinstance(op, ast.Sub):
                    r = a - b
                elif isinstance(op, ast.Mult):
                    r = a * b
                elif isinstance(op, ast.Div):
                    r = a / b
                elif isinstance(op, ast.Mod):
                    r = a % b
                else:
                    r = a ** b
            return r.replace([np.inf, -np.inf], np.nan) if isinstance(r, pd.Series) else r
        if isinstance(node, ast.UnaryOp):
            v = self.eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return v
            if isinstance(v, pd.Series):  # not / ~
                return _as_float(~_bool(v), v.isna())
            return float(not _bool(v))
        if isinstance(node, ast.BoolOp):
            vals = [self.eval(v) for v in node.values]
            r = vals[0]
            for v in vals[1:]:
                r = self._logic(r, v, "and" if isinstance(node.op, ast.And) else "or")
            return r
        if isinstance(node, ast.Compare):
            left = self.eval(node.left)
            result = None
            for op, comp in zip(node.ops, node.comparators):
                right = self.eval(comp)
                with np.errstate(invalid="ignore"):
                    c = {ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b, ast.Lt: lambda a, b: a < b,
                         ast.LtE: lambda a, b: a <= b, ast.Eq: lambda a, b: a == b,
                         ast.NotEq: lambda a, b: a != b}[type(op)](left, right)
                nan = None
                for v in (left, right):
                    if isinstance(v, pd.Series):
                        nan = v.isna() if nan is None else (nan | v.isna())
                c = _as_float(c, nan)
                result = c if result is None else self._logic(result, c, "and")
                left = right
            return result
        if isinstance(node, ast.IfExp):
            return self._where(self.eval(node.test), self.eval(node.body), self.eval(node.orelse))
        if isinstance(node, ast.Call):
            return self._call(node.func.id, [self.eval(a) for a in node.args])
        raise FormulaError(f"不支持的语法: {type(node).__name__}")

    def _logic(self, a, b, kind):
        nan = None
        for v in (a, b):
            if isinstance(v, pd.Series):
                nan = v.isna() if nan is None else (nan | v.isna())
        ba, bb = _bool(a), _bool(b)
        r = (ba & bb) if kind == "and" else (ba | bb)
        if isinstance(r, pd.Series):
            # 逻辑短路语义：and 中任一为假 → 假；or 中任一为真 → 真；否则有缺失 → 缺失
            if nan is not None:
                decided = (~r) if kind == "and" else r
                return r.astype(float).where(~nan | decided)
            return r.astype(float)
        return float(r)

    def _where(self, cond, a, b):
        c = self.series(cond)
        out = self.series(b).where(~_bool(c), self.series(a))
        return out.where(c.notna())

    def _call(self, fn, args):
        x = args[0]
        if fn in ("abs", "sign", "exp"):
            return {"abs": np.abs, "sign": np.sign, "exp": np.exp}[fn](x)
        if fn == "log":
            with np.errstate(all="ignore"):
                return np.log(self.series(x).where(self.series(x) > 0))
        if fn == "sqrt":
            with np.errstate(all="ignore"):
                return np.sqrt(self.series(x).where(self.series(x) >= 0))
        if fn in ("min", "max"):
            a, b = self.series(args[0]), self.series(args[1])
            r = np.fmin(a, b) if fn == "min" else np.fmax(a, b)
            return r.where(a.notna() & b.notna())
        if fn == "clip":
            return self.series(x).clip(args[1], args[2])
        if fn == "fillna":
            return self.series(x).fillna(args[1])
        if fn == "isnull":
            return self.series(x).isna().astype(float)
        if fn == "where":
            return self._where(*args)
        s = self.series(x)
        if fn in _TS_FUNCS - _FUNCS:
            n = int(args[1])
            mp = max(2, min(n, n // 3 + 1))
            if fn == "ma":
                return s.rolling(n, min_periods=mp).mean()
            if fn == "ema":
                return s.ewm(span=n, min_periods=mp, adjust=False).mean()
            if fn == "ts_max":
                return s.rolling(n, min_periods=mp).max()
            if fn == "ts_min":
                return s.rolling(n, min_periods=mp).min()
            if fn == "ts_std":
                return s.rolling(n, min_periods=mp).std()
            if fn == "ts_zscore":
                m, sd = s.rolling(n, min_periods=mp).mean(), s.rolling(n, min_periods=mp).std()
                return (s - m) / sd.replace(0, np.nan)
            if fn == "ts_rank":  # 当前值在过去 n 期中的百分位 0~100
                return s.rolling(n, min_periods=mp).apply(lambda v: (v[:-1] < v[-1]).mean() * 100 if len(v) > 1 else np.nan, raw=True)
            if fn == "diff":
                return s.diff(n)
            if fn == "lag":
                return s.shift(n)
            if fn == "pct_change":
                return s.pct_change(n, fill_method=None) * 100
        if fn == "rank":
            return self.xs(s, lambda v: v.rank(pct=True))
        if fn == "zscore":
            return self.xs(s, _mad_z)
        if fn == "demean":
            return self.xs(s, lambda v: v - v.mean())
        if fn in ("ind_rank", "ind_zscore"):
            if "industry" not in self.df.columns:
                raise FormulaError(f"{fn} 需要行业数据")
            keys = [self.df["industry"].fillna("未知")]
            if self.by:
                keys.insert(0, self.df[self.by])
            f = (lambda v: v.rank(pct=True)) if fn == "ind_rank" else _mad_z
            return self.xs(s, f, keys)
        raise FormulaError(f"不支持的函数: {fn}")


def evaluate(expr: str, df: pd.DataFrame, by: str | None = "date") -> pd.Series:
    """在 DataFrame 上计算公式。by: 截面函数（rank/zscore…）的分组列；单截面时自动忽略。"""
    tree = _parse(expr)
    known = set(FACTORS) | set(EXTRA_FIELDS) | set(custom_factors())
    _check(tree, set(), known)
    r = _Evaluator(df, by).eval(tree.body)
    if not isinstance(r, pd.Series):
        r = pd.Series(float(r), index=df.index)
    return r.astype(float).replace([np.inf, -np.inf], np.nan)


def materialize(df: pd.DataFrame, names, by: str | None = "date") -> pd.DataFrame:
    """为 names 中的公式因子在 df 上添加计算列（基础因子原样保留）。"""
    customs = custom_factors()
    todo = [n for n in dict.fromkeys(names) if n in customs and n not in df.columns]
    if not todo:
        return df
    df = df.copy()
    for n in todo:
        df[n] = evaluate(customs[n]["expr"], df, by)
    return df


# ---------------- 时间序列公式（融合市场指标） ----------------
def market_known() -> set[str]:
    from backend.factors.build import MARKET_INDICATORS
    return set(MARKET_INDICATORS)


def validate_ts(expr: str, known_extra: set | None = None) -> set[str]:
    names: set[str] = set()
    _check(_parse(expr), names, market_known() | (known_extra or set()), _TS_FUNCS)
    return names


def evaluate_ts(expr: str, df: pd.DataFrame, customs: dict[str, str] | None = None) -> pd.Series:
    """df: 按日期排序的市场指标表（列 = 指标名）。customs: 其他已保存融合指标 {name: expr}，可相互引用。"""
    customs = customs or {}
    tree = _parse(expr)
    _check(tree, set(), market_known() | set(customs), _TS_FUNCS)
    ev = _Evaluator(df, None)
    ev.customs = {}

    def resolve(n, stack=()):
        if n in stack:
            raise FormulaError(f"公式循环引用: {' → '.join(stack + (n,))}")
        if n in ev.memo:
            return
        if n in customs:
            t = _parse(customs[n])
            names: set[str] = set()
            _check(t, names, market_known() | set(customs), _TS_FUNCS)
            for m in names:
                resolve(m, stack + (n,))
            ev.memo[n] = ev.series(ev.eval(t.body))

    names: set[str] = set()
    _check(tree, names, market_known() | set(customs), _TS_FUNCS)
    for n in names:
        resolve(n)
    r = ev.eval(tree.body)
    if not isinstance(r, pd.Series):
        r = pd.Series(float(r), index=df.index)
    return r.astype(float).replace([np.inf, -np.inf], np.nan)
