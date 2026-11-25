"""回测 / 因子分析共用：股票池（历史成分股）、截面过滤、去极值标准化、行业市值中性化、价格面板缓存。"""
from __future__ import annotations

import bisect
import datetime as dt
import threading
import time

import numpy as np
import pandas as pd

from backend.db.conn import query_df
from backend.formula import FormulaError, all_factors, base_columns, evaluate, materialize
from backend.screener import apply_rules

UNIVERSES = {
    "all": "全 A 股（含退市）",
    "hs800": "沪深300+中证500（历史成分）",
    "hs300": "沪深300（历史成分）",
    "zz500": "中证500（历史成分）",
    "core": "当前沪深300+中证500",
}
NEUTRALIZE = {"industry": "行业", "size": "市值"}

_lock = threading.Lock()
_mem: dict = {}


def _cached(key: str, ttl: float, fn):
    with _lock:
        hit = _mem.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _lock:
        _mem[key] = (time.time(), val)
    return val


def clear_cache():
    with _lock:
        _mem.clear()


# ---------------- 股票池 ----------------
def _load_members():
    df = query_df("SELECT index_code, date, code FROM index_member")
    if df.empty:
        return [], {}
    df["date"] = pd.to_datetime(df.date).dt.date
    snaps = {}
    for (i, d), g in df.groupby(["index_code", "date"]):
        snaps.setdefault(d, {})[i] = set(g.code)
    return sorted(snaps), snaps


def universe_codes(universe: str, d: dt.date) -> set | None:
    """信号日 d 时的股票池；None 表示不限制。历史成分取 d 之前最近一次快照。"""
    if universe in ("all", None, ""):
        return None
    if universe == "core":
        return _cached("core", 300, lambda: set(query_df("SELECT code FROM stock_basic WHERE in_universe").code))
    if universe not in UNIVERSES:
        raise ValueError(f"未知股票池: {universe}")
    dates, snaps = _cached("members", 300, _load_members)
    if not dates:
        raise ValueError("缺少历史成分股数据，请先运行: python -m backend.cli members")
    k = bisect.bisect_right(dates, d) - 1
    snap = snaps[dates[max(k, 0)]]
    idx = ("hs300", "zz500") if universe == "hs800" else (universe,)
    out = set()
    for i in idx:
        out |= snap.get(i, set())
    return out


# ---------------- 截面处理 ----------------
def filter_cross_section(df: pd.DataFrame, d: dt.date, universe: str = "all", exclude_st: bool = True,
                         min_listed_days: int = 365, rules=None, industries=None, expr: str | None = None,
                         min_amount: float = 0.0) -> pd.DataFrame:
    """信号日截面过滤。rules / expr 只用当日及以前的数据，回测中逐期动态筛选。"""
    codes = universe_codes(universe, d)
    if codes is not None:
        df = df[df.code.isin(codes)]
    if exclude_st:
        df = df[df.is_st != 1]
    df = df[(df.listed_days >= min_listed_days) & df.close_hfq.notna()]
    if min_amount > 0:
        df = df[df.amount_20 >= min_amount]
    rules = rules or []
    need = [r["field"] for r in rules]
    df = materialize(df, need, by=None)
    df = apply_rules(df, rules, industries)
    if expr:
        try:
            df = df[evaluate(expr, df, by=None).fillna(0) != 0]
        except FormulaError as e:
            raise ValueError(f"过滤公式错误: {e}") from None
    return df


def winsor_z(x: pd.Series) -> pd.Series:
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    if not np.isfinite(mad) or mad == 0:
        mad = x.std() or 1.0
    x = x.clip(med - 3 * mad, med + 3 * mad)
    sd = x.std()
    return (x - x.mean()) / (sd if sd and np.isfinite(sd) else 1.0)


def neutralize(z: pd.Series, df: pd.DataFrame, how) -> pd.Series:
    """对行业哑变量和/或对数流通市值做截面 OLS，取残差并重新标准化。"""
    how = set(how or [])
    if not how or len(z) < 10:
        return z
    cols = []
    if "industry" in how:
        ind = df["industry"].fillna("未知")
        cols.append(pd.get_dummies(ind, dtype=float).values)
    else:
        cols.append(np.ones((len(z), 1)))
    if "size" in how:
        lmv = np.log(df["float_mv"].where(df["float_mv"] > 0))
        cols.append(lmv.fillna(lmv.median()).fillna(0).values.reshape(-1, 1))
    X = np.hstack(cols)
    y = z.values.astype(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = pd.Series(y - X @ beta, index=z.index)
    sd = resid.std()
    return (resid - resid.mean()) / (sd if sd and np.isfinite(sd) else 1.0)


def factor_sign(name: str, direction: str | None = None) -> float:
    meta = all_factors().get(name)
    if meta is None:
        raise ValueError(f"未知因子: {name}")
    d = direction or meta["better"]
    return 1.0 if d == "high" else -1.0


def composite_score(df: pd.DataFrame, factors, neutral=None) -> pd.Series:
    """factors: [(name, weight, direction)]。每个因子去极值标准化（可中性化）后按方向加权。"""
    total_w = sum(abs(w) for _, w, _ in factors) or 1.0
    score = 0.0
    for name, w, direction in factors:
        z = neutralize(winsor_z(df[name]), df, neutral)
        score = score + z * factor_sign(name, direction) * w
    return score / total_w


def snapshot_columns(names, rules=None, expr: str | None = None) -> list[str]:
    """读取截面时需要的 factor_daily 列。"""
    need = set(names) | {r["field"] for r in rules or []}
    cols = base_columns(need, extra_expr=expr) if expr else base_columns(need)
    cols |= {"listed_days", "is_st", "close_hfq", "industry", "float_mv", "amount_20", "name"}
    return sorted(c for c in cols if c not in ("code", "date"))


def load_snapshots(dates, cols) -> dict:
    df = query_df(f"SELECT code, date, {', '.join(cols)} FROM factor_view WHERE date IN (SELECT unnest(?::DATE[]))",
                  [list(dates)])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return {d: g for d, g in df.groupby("date")}


def signal_dates(cal: list, freq: str) -> list:
    s = pd.Series(pd.to_datetime(cal), index=pd.to_datetime(cal))
    key = s.dt.to_period({"W": "W", "Q": "Q"}.get(freq, "M"))
    return [d.date() for d in s.groupby(key).max().tolist()]


# ---------------- 价格面板（全市场 × 全部交易日，进程内缓存） ----------------
def _panel_version() -> str:
    r = query_df("SELECT max(updated_at) t FROM etl_log WHERE task = 'factors'")
    return str(r.t.iloc[0])


_PANEL_SQL = """
WITH c AS (SELECT code, (row_number() OVER (ORDER BY code) - 1)::INTEGER AS ci
           FROM (SELECT DISTINCT code FROM factor_daily)),
     d AS (SELECT date, (row_number() OVER (ORDER BY date) - 1)::INTEGER AS di
           FROM (SELECT DISTINCT date FROM index_daily WHERE code = 'sh.000300'))
SELECT c.ci, d.di, f.open_hfq::FLOAT AS o, f.close_hfq::FLOAT AS cl,
       coalesce(f.one_price, false) AND coalesce(f.pct_chg, 0) > 0 AS lu,
       coalesce(f.one_price, false) AND coalesce(f.pct_chg, 0) < 0 AS ld
FROM factor_daily f JOIN c USING (code) JOIN d USING (date)
"""


def _build_panel() -> dict:
    """在 DuckDB 中把 (code, date) 映射为整数下标后直接取 numpy 数组，避免上千万个 Python 字符串。"""
    from backend.db.conn import connect
    with connect() as con:
        cal = list(pd.to_datetime(con.execute(
            "SELECT DISTINCT date FROM index_daily WHERE code = 'sh.000300' ORDER BY date").df().date).dt.date)
        codes = con.execute("SELECT DISTINCT code FROM factor_daily ORDER BY code").df().code.tolist()
        a = con.execute(_PANEL_SQL).fetchnumpy()
        delisted = set(con.execute("SELECT code FROM stock_basic WHERE status = 0").df().code)
    didx = {d: i for i, d in enumerate(cal)}
    cidx = {c: i for i, c in enumerate(codes)}
    shape = (len(cal), len(codes))
    open_ = np.full(shape, np.nan, dtype=np.float32)
    close = np.full(shape, np.nan, dtype=np.float32)
    limup = np.zeros(shape, bool)
    limdn = np.zeros(shape, bool)
    ri, ci = np.asarray(a["di"]), np.asarray(a["ci"])
    open_[ri, ci] = np.asarray(a["o"], dtype=np.float32)
    close[ri, ci] = np.asarray(a["cl"], dtype=np.float32)
    limup[ri, ci] = np.asarray(a["lu"], dtype=bool)
    limdn[ri, ci] = np.asarray(a["ld"], dtype=bool)
    del a
    close_ff = pd.DataFrame(close).ffill().values.astype(np.float32)
    # 退市股：最后一个交易日之后按最后收盘价视为可卖出（资金退出），避免"永远锁仓"
    has = ~np.isnan(close)
    last_row = np.where(has.any(axis=0), len(cal) - 1 - np.argmax(has[::-1], axis=0), -1)
    for c in delisted & set(codes):
        j = cidx[c]
        i = last_row[j]
        if 0 <= i < len(cal) - 1:
            open_[i + 1:, j] = close_ff[i, j]
    return {"cal": cal, "didx": didx, "codes": codes, "cidx": cidx, "open": open_, "close": close,
            "close_ff": close_ff, "limup": limup, "limdn": limdn}


def price_panel() -> dict:
    ver = _panel_version()
    with _lock:
        hit = _mem.get("panel")
    if hit and hit[1]["ver"] == ver:
        return hit[1]
    p = _build_panel()
    p["ver"] = ver
    with _lock:
        _mem["panel"] = (time.time(), p)
    return p
