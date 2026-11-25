"""FastAPI 服务：uvicorn backend.api.main:app --port 8000"""
from __future__ import annotations

import datetime as dt
import json
import threading
import uuid

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import BENCHMARKS, ROOT
from backend.db.conn import connect, query_df
from backend.factors.build import FACTORS
from backend import screener
from backend.formula import FormulaError, all_factors

app = FastAPI(title="Quant Factor Lab")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def records(df: pd.DataFrame) -> list[dict]:
    df = df.replace([np.inf, -np.inf], np.nan).astype(object).where(df.notna(), None)
    for c in df.columns:
        if len(df) and isinstance(df[c].iloc[0], (dt.date, pd.Timestamp)):
            df[c] = df[c].map(lambda x: str(x)[:10] if x is not None else None)
    return df.to_dict("records")


def _latest() -> dt.date:
    try:
        d = screener.latest_date()
    except Exception:  # factor_daily 表尚未生成
        d = None
    if d is None or pd.isna(d):
        raise HTTPException(503, "暂无数据，请先运行 ETL: python -m backend.cli etl")
    return pd.Timestamp(d).date()


# ---------------- 元数据 ----------------
@app.get("/api/meta")
def meta():
    with connect() as con:
        tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        etl = con.execute("SELECT task, status, message, updated_at FROM etl_log ORDER BY task").df()
        from backend.backtest.universe import NEUTRALIZE, UNIVERSES
        info = {"etl": records(etl), "factors": all_factors(), "benchmarks": BENCHMARKS,
                "universes": UNIVERSES, "neutralize": NEUTRALIZE}
        if "factor_daily" in tables:
            r = con.execute("SELECT min(date), max(date), count(DISTINCT code) FROM factor_daily").fetchone()
            info.update(start=str(r[0]), end=str(r[1]), n_stocks=r[2])
            info["industries"] = [x[0] for x in con.execute(
                "SELECT industry, count(*) n FROM stock_basic WHERE status = 1 AND industry IS NOT NULL "
                "GROUP BY 1 ORDER BY n DESC").fetchall()]
        info["ready"] = "factor_daily" in tables
    return info


# ---------------- 市场总览 ----------------
@app.get("/api/market/overview")
def market_overview(date: dt.date | None = None):
    date = date or _latest()
    sent = query_df("SELECT * FROM market_sentiment ORDER BY date")
    sent["date"] = pd.to_datetime(sent.date).dt.date
    sent = sent[sent.date <= date]
    if sent.empty:
        raise HTTPException(404, "该日期无数据")
    cur = sent.iloc[-1]

    def ago(days):
        target = date - dt.timedelta(days=days)
        s = sent[sent.date <= target]
        return None if s.empty else {"date": str(s.iloc[-1].date), "score": round(float(s.iloc[-1].score), 1)}

    idx = query_df("""
        SELECT code, date, close, pct_chg FROM index_daily
        WHERE date <= ? ORDER BY date""", [date])
    indices = []
    for code, name in BENCHMARKS.items():
        g = idx[idx.code == code]
        if g.empty:
            continue
        indices.append({"code": code, "name": name, "close": float(g.close.iloc[-1]),
                        "pct_chg": float(g.pct_chg.iloc[-1]) if pd.notna(g.pct_chg.iloc[-1]) else None,
                        "dates": [str(d)[:10] for d in g.date], "values": [round(float(v), 2) for v in g.close]})
    tl = sent
    comps = ["breadth", "above_ma20", "high_low", "volume", "momentum"]
    return {
        "date": str(cur.date),
        "stats": {k: (None if pd.isna(cur[k]) else float(cur[k])) for k in ["n", "up", "down", "flat", "amount"]},
        "sentiment": {
            "score": round(float(cur.score), 1),
            "components": {k: (None if pd.isna(cur[k]) else round(float(cur[k]), 1)) for k in comps},
            "history": {"prev": ago(1), "week": ago(7), "month": ago(30), "year": ago(365)},
            "timeline": {"dates": [str(d) for d in tl.date], "scores": [round(float(s), 1) for s in tl.score]},
        },
        "indices": indices,
    }


@app.get("/api/market/stocks")
def market_stocks(date: dt.date | None = None):
    date = date or _latest()
    df = query_df("""SELECT code, name, industry, close, pct_chg, amount/1e8 AS amount, turnover, float_mv,
                            pe_ttm, pb, roe_ann, mom_20, vol_60
                     FROM factor_daily WHERE date = ? ORDER BY amount DESC LIMIT 1000""", [date])
    return {"date": str(date), "rows": records(df)}


# ---------------- 市场指标 / 融合指标 ----------------
def _market_df() -> pd.DataFrame:
    from backend.factors.build import MARKET_INDICATORS
    cols = [c for c in MARKET_INDICATORS]
    df = query_df(f"SELECT date, {', '.join(cols)} FROM market_sentiment ORDER BY date")
    df["date"] = pd.to_datetime(df.date).dt.date
    return df.reset_index(drop=True)


def _market_formulas() -> dict:
    df = query_df("SELECT name, label, expr FROM market_formula ORDER BY created_at")
    return {r.name: {"label": r.label, "expr": r.expr} for r in df.itertuples()}


def _clean_list(v: pd.Series, nd=4):
    return [None if pd.isna(x) else round(float(x), nd) for x in v]


@app.get("/api/market/indicators")
def market_indicators(names: str = ""):
    """内置市场指标 + 已保存的融合指标；names 指定需要返回序列的指标（逗号分隔）。"""
    from backend.factors.build import MARKET_INDICATORS
    from backend.formula import evaluate_ts
    saved = _market_formulas()
    out = {"builtin": MARKET_INDICATORS, "saved": saved, "dates": [], "series": {}}
    want = [n for n in names.split(",") if n]
    if not want:
        return out
    df = _market_df()
    out["dates"] = [str(d) for d in df.date]
    exprs = {k: v["expr"] for k, v in saved.items()}
    for n in want:
        if n in MARKET_INDICATORS:
            out["series"][n] = _clean_list(df[n])
        elif n in saved:
            try:
                out["series"][n] = _clean_list(evaluate_ts(saved[n]["expr"], df, exprs))
            except FormulaError:
                out["series"][n] = []
    return out


class MarketExprReq(BaseModel):
    expr: str


@app.post("/api/market/formula/preview")
def market_formula_preview(req: MarketExprReq):
    from backend.formula import evaluate_ts
    df = _market_df()
    try:
        v = evaluate_ts(req.expr, df, {k: x["expr"] for k, x in _market_formulas().items()})
    except FormulaError as e:
        return {"ok": False, "error": str(e)}
    ok = v.dropna()
    return {"ok": True, "dates": [str(d) for d in df.date], "values": _clean_list(v),
            "last": float(ok.iloc[-1]) if len(ok) else None, "coverage": int(len(ok))}


class MarketFormulaReq(BaseModel):
    name: str
    label: str | None = None
    expr: str


@app.post("/api/market/formulas")
def save_market_formula(req: MarketFormulaReq):
    from backend.factors.build import MARKET_INDICATORS
    from backend.formula import NAME_RE, evaluate_ts
    if not NAME_RE.match(req.name):
        raise HTTPException(400, "名称须为小写字母开头，只含小写字母/数字/下划线，2–32 位")
    if req.name in MARKET_INDICATORS:
        raise HTTPException(400, "名称与内置指标重复")
    others = {k: v["expr"] for k, v in _market_formulas().items() if k != req.name}
    try:
        evaluate_ts(req.expr, _market_df().tail(300).reset_index(drop=True), others)  # 不能引用自身
    except FormulaError as e:
        raise HTTPException(400, str(e))
    with connect(read_only=False) as con:
        con.execute("DELETE FROM market_formula WHERE name = ?", [req.name])
        con.execute("INSERT INTO market_formula (name, label, expr) VALUES (?, ?, ?)",
                    [req.name, req.label or req.name, req.expr.strip()])
    return {"ok": True}


@app.delete("/api/market/formulas/{name}")
def delete_market_formula(name: str):
    with connect(read_only=False) as con:
        con.execute("DELETE FROM market_formula WHERE name = ?", [name])
    return {"ok": True}


# ---------------- 个股 ----------------
@app.get("/api/stocks/search")
def search(q: str = "", limit: int = 20):
    df = query_df("""SELECT code, name, industry, status FROM stock_basic
                     WHERE (code ILIKE ? OR name ILIKE ?) ORDER BY status DESC, in_universe DESC, code LIMIT ?""",
                  [f"%{q}%", f"%{q}%", limit])
    return records(df)


@app.get("/api/stocks/{code}")
def stock_detail(code: str, years: int = Query(3, ge=0, le=15)):
    """years=0 返回全部历史（前端按时间窗口自行截取）。"""
    basic = query_df("SELECT * FROM stock_basic WHERE code = ?", [code])
    if basic.empty:
        raise HTTPException(404, "股票不存在")
    start = _latest() - dt.timedelta(days=365 * (years or 100))
    k = query_df("""SELECT date, open, high, low, close, volume, close_hfq, pe_ttm, pb, pct_chg
                    FROM factor_daily WHERE code = ? ORDER BY date""", [code])
    k["date"] = pd.to_datetime(k["date"]).dt.date
    start = pd.Timestamp(start).date()
    snap =query_df("SELECT * FROM factor_daily WHERE code = ? ORDER BY date DESC LIMIT 1", [code])
    out = {"basic": records(basic)[0], "snapshot": records(snap)[0] if len(snap) else None}
    if k.empty:
        out.update(kline=[], valuation={})
        return out
    # 前复权 = 后复权 / 最新复权因子（与不复权价在最新一天对齐）
    ratio = k.close_hfq.iloc[-1] / k.close.iloc[-1]
    adj = k.close_hfq / ratio / k.close
    for c in ["open", "high", "low", "close"]:
        k[c] = (k[c] * adj).round(3)
    k["ma20"] = k.close.rolling(20).mean().round(3)
    k["ma60"] = k.close.rolling(60).mean().round(3)
    kk = k[k.date >= start]
    out["kline"] = records(kk[["date", "open", "high", "low", "close", "volume", "ma20", "ma60", "pct_chg"]])
    val = {}
    for col in ["pe_ttm", "pb"]:  # 估值带用全部历史
        s = k[["date", col]].dropna()
        s = s[s[col] > 0]
        if s.empty:
            continue
        v = s[col]
        val[col] = {
            "dates": [str(d) for d in s.date], "values": [round(float(x), 2) for x in v],
            "mean": float(v.mean()), "std": float(v.std()),
            "current": float(v.iloc[-1]), "percentile": float((v < v.iloc[-1]).mean() * 100),
        }
    out["valuation"] = val
    return out


@app.get("/api/stocks/{code}/financials")
def stock_financials(code: str, limit: int = 20):
    df = query_df("""SELECT report_date, effective_date, revenue, revenue_yoy, net_profit, net_profit_yoy,
                            op_profit, total_expense, op_cost, sell_exp, admin_exp, fin_exp, eps, bps, roe,
                            roe_ann, gross_margin
                     FROM financial_report WHERE code = ? ORDER BY report_date DESC LIMIT ?""", [code, limit])
    return records(df.iloc[::-1])


@app.get("/api/stocks/{code}/dividends")
def stock_dividends(code: str):
    """分红记录 + 按年汇总（每股分红合计、分红率 = 当年每股分红 / 年报 EPS）。"""
    df = query_df("""SELECT d.report_date, d.dps, d.bonus_per10, d.plan_date, d.ex_date, d.progress,
                            year(d.report_date) AS year
                     FROM dividend d WHERE d.code = ? AND (d.dps > 0 OR d.bonus_per10 > 0)
                     ORDER BY d.report_date DESC""", [code])
    if df.empty:
        return []
    eps = query_df("SELECT year(report_date) AS year, eps FROM financial_report WHERE code = ? AND month(report_date) = 12",
                   [code])
    yr = df[df.dps > 0].groupby("year").dps.sum().rename("year_dps").reset_index().merge(eps, on="year", how="left")
    yr["year_payout"] = np.where(yr.eps > 0, yr.year_dps / yr.eps * 100, np.nan)
    first = df.drop_duplicates("year").index  # 每年只在最新一条记录上带汇总，前端据此画年度图
    df = df.merge(yr[["year", "year_dps", "year_payout"]], on="year", how="left")
    df.loc[~df.index.isin(first), ["year_dps", "year_payout"]] = np.nan
    return records(df.sort_values("report_date", ascending=False))


@app.get("/api/stocks/{code}/balance")
def stock_balance(code: str, refresh: bool = False):
    """资产负债结构（东方财富 F10 按需拉取，缓存 3 天）。"""
    from backend.etl import balance
    try:
        return balance.get(code, refresh=refresh)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资产负债表获取失败：{e}") from None


# ---------------- 对比 ----------------
@app.get("/api/compare")
def compare(codes: str, years: int = 3):
    cl = [c for c in codes.split(",") if c][:6]
    if not cl:
        raise HTTPException(400, "codes 不能为空")
    start = _latest() - dt.timedelta(days=365 * years)
    df = query_df("""SELECT code, name, date, close_hfq, ret FROM factor_daily
                     WHERE code IN (SELECT unnest(?::VARCHAR[])) AND date >= ? ORDER BY date""", [cl, start])
    series, stats = [], []
    for code in cl:
        g = df[df.code == code]
        if g.empty:
            continue
        nav = g.close_hfq / g.close_hfq.iloc[0]
        dd = (nav / nav.cummax() - 1).min()
        n = len(nav) - 1
        series.append({"code": code, "name": g.name.iloc[0], "dates": [str(d)[:10] for d in g.date],
                       "values": [round(float(x), 4) for x in nav]})
        stats.append({"code": code, "ann_return": float(nav.iloc[-1] ** (252 / n) - 1) * 100 if n > 0 else None,
                      "ann_vol": float(g.ret.std() * np.sqrt(252) * 100), "max_dd": float(dd * 100)})
    snap = query_df(f"""SELECT {', '.join(screener.SNAPSHOT_COLS)} FROM factor_daily
                        WHERE code IN (SELECT unnest(?::VARCHAR[])) AND date = ?""", [cl, _latest()])
    snap = snap.merge(pd.DataFrame(stats), on="code", how="left") if stats else snap
    return {"series": series, "table": records(snap)}


# ---------------- 选股器 / 股票池 ----------------
class Rule(BaseModel):
    field: str
    min: float | None = None
    max: float | None = None


class ScreenReq(BaseModel):
    rules: list[Rule] = []
    industries: list[str] = []
    exclude_st: bool = True
    sort: str | None = "roe_ann"
    desc: bool = True
    expr: str | None = None


@app.post("/api/screener")
def run_screener(req: ScreenReq):
    try:
        df = screener.screen([r.model_dump() for r in req.rules], req.industries, req.exclude_st,
                             sort=req.sort, desc=req.desc, expr=req.expr or None)
    except (ValueError, FormulaError) as e:
        raise HTTPException(400, str(e))
    return {"date": str(_latest()), "count": len(df), "rows": records(df.head(500))}


class PoolReq(BaseModel):
    name: str
    rules: list[Rule] = []
    industries: list[str] = []
    exclude_st: bool = True
    expr: str | None = None


@app.get("/api/pools")
def list_pools():
    df = query_df("SELECT pool_id, name, rules, created_at FROM stock_pool ORDER BY created_at DESC")
    out = records(df)
    for r in out:
        r["rules"] = json.loads(r["rules"]) if isinstance(r["rules"], str) else r["rules"]
    return out


@app.post("/api/pools")
def save_pool(req: PoolReq):
    pid = uuid.uuid4().hex[:8]
    body = {"rules": [r.model_dump() for r in req.rules], "industries": req.industries, "exclude_st": req.exclude_st,
            "expr": req.expr or None}
    with connect(read_only=False) as con:
        con.execute("INSERT INTO stock_pool (pool_id, name, rules) VALUES (?, ?, ?)", [pid, req.name, json.dumps(body)])
    return {"pool_id": pid}


@app.delete("/api/pools/{pool_id}")
def delete_pool(pool_id: str):
    with connect(read_only=False) as con:
        con.execute("DELETE FROM stock_pool WHERE pool_id = ?", [pool_id])
    return {"ok": True}


# ---------------- 回测 ----------------
class FactorReq(BaseModel):
    name: str
    weight: float = 1.0
    direction: str | None = None


class BacktestReq(BaseModel):
    name: str = "未命名策略"
    factors: list[FactorReq] = Field(min_length=1)
    start: dt.date = dt.date(2015, 1, 1)
    end: dt.date | None = None
    freq: str = "M"
    top_n: int = Field(30, ge=1, le=200)
    pool_id: str | None = None
    rules: list[Rule] = []
    industries: list[str] = []
    benchmark: str = "sh.000300"
    commission: float = 0.00025
    slippage: float = 0.001
    universe: str = "all"
    neutralize: list[str] = []
    expr: str | None = None
    min_amount: float = 0.0
    exclude_st: bool = True


def _pool_filters(pool_id, rules, industries, expr):
    """合并股票池里保存的规则 / 行业 / 公式。"""
    rules, industries = list(rules), list(industries)
    exprs = [expr] if expr else []
    if pool_id:
        pool = query_df("SELECT rules FROM stock_pool WHERE pool_id = ?", [pool_id])
        if pool.empty:
            raise HTTPException(404, "股票池不存在")
        body = json.loads(pool.rules.iloc[0])
        rules += body.get("rules", [])
        industries += body.get("industries", [])
        if body.get("expr"):
            exprs.append(body["expr"])
    expr = " and ".join(f"({e})" for e in exprs) if exprs else None
    return rules, industries, expr


@app.post("/api/backtest")
def backtest(req: BacktestReq):
    from backend.backtest.engine import BacktestParams, FactorSpec, run_backtest

    rules, industries, expr = _pool_filters(req.pool_id, [r.model_dump() for r in req.rules], req.industries, req.expr)
    p = BacktestParams(
        factors=[FactorSpec(f.name, f.weight, f.direction) for f in req.factors],
        start=req.start, end=req.end, freq=req.freq, top_n=req.top_n, rules=rules, industries=industries,
        benchmark=req.benchmark, commission=req.commission, slippage=req.slippage, universe=req.universe,
        neutralize=req.neutralize, expr=expr, min_amount=req.min_amount, exclude_st=req.exclude_st)
    try:
        res = run_backtest(p)
    except (ValueError, FormulaError) as e:
        raise HTTPException(400, str(e))
    run_id = uuid.uuid4().hex[:8]
    with connect(read_only=False) as con:
        con.execute("INSERT INTO backtest_run (run_id, name, params, metrics, result) VALUES (?, ?, ?, ?, ?)",
                    [run_id, req.name, req.model_dump_json(), json.dumps(res["metrics"]), json.dumps(res)])
    return {"run_id": run_id, "name": req.name, "params": json.loads(req.model_dump_json()), **res}


@app.get("/api/backtests")
def list_backtests():
    df = query_df("SELECT run_id, name, params, metrics, created_at FROM backtest_run ORDER BY created_at DESC LIMIT 200")
    out = records(df)
    for r in out:
        r["params"] = json.loads(r["params"])
        r["metrics"] = json.loads(r["metrics"])
    return out


@app.get("/api/backtests/compare")
def compare_backtests(ids: str):
    """多个已保存回测的净值叠加与指标对比。"""
    il = [i for i in ids.split(",") if i][:8]
    df = query_df("SELECT run_id, name, params, result, created_at FROM backtest_run "
                  "WHERE run_id IN (SELECT unnest(?::VARCHAR[]))", [il])
    order = {r: k for k, r in enumerate(il)}
    out = []
    for r in sorted(df.itertuples(), key=lambda r: order.get(r.run_id, 99)):
        res = json.loads(r.result)
        out.append({"run_id": r.run_id, "name": r.name, "params": json.loads(r.params), "metrics": res["metrics"],
                    "series": res["series"], "yearly": res.get("yearly", []), "created_at": str(r.created_at)[:19]})
    return out


class RenameReq(BaseModel):
    name: str


@app.patch("/api/backtests/{run_id}")
def rename_backtest(run_id: str, req: RenameReq):
    with connect(read_only=False) as con:
        con.execute("UPDATE backtest_run SET name = ? WHERE run_id = ?", [req.name, run_id])
    return {"ok": True}


@app.delete("/api/backtests/{run_id}")
def delete_backtest(run_id: str):
    with connect(read_only=False) as con:
        con.execute("DELETE FROM backtest_run WHERE run_id = ?", [run_id])
    return {"ok": True}


@app.get("/api/backtests/{run_id}")
def get_backtest(run_id: str):
    df = query_df("SELECT run_id, name, params, result FROM backtest_run WHERE run_id = ?", [run_id])
    if df.empty:
        raise HTTPException(404)
    r = df.iloc[0]
    return {"run_id": r.run_id, "name": r["name"], "params": json.loads(r.params), **json.loads(r.result)}


# ---------------- 财报 ----------------
@app.get("/api/financials/periods")
def fin_periods():
    df = query_df("SELECT report_date, count(*) n FROM financial_report GROUP BY 1 ORDER BY 1 DESC")
    return records(df)


@app.get("/api/financials")
def financials(report_date: dt.date, q: str = "", universe_only: bool = True,
               sort: str = "revenue", desc: bool = True, limit: int = 300):
    allowed = {"revenue", "revenue_yoy", "net_profit", "net_profit_yoy", "op_profit", "total_expense",
               "sell_exp", "admin_exp", "fin_exp", "roe", "gross_margin", "eps"}
    sort = sort if sort in allowed else "revenue"
    df = query_df(f"""
        SELECT f.code, coalesce(s.name, f.name) AS name, coalesce(s.industry, f.industry_em) AS industry,
               f.announce_date, f.effective_date, f.revenue, f.revenue_yoy, f.net_profit, f.net_profit_yoy,
               f.op_profit, f.total_expense, f.op_cost, f.sell_exp, f.admin_exp, f.fin_exp, f.eps, f.roe, f.gross_margin
        FROM financial_report f LEFT JOIN stock_basic s USING (code)
        WHERE f.report_date = ? AND (? = '' OR f.code ILIKE ? OR coalesce(s.name, f.name) ILIKE ?)
          {"AND s.in_universe" if universe_only else ""}
        ORDER BY {sort} {"DESC" if desc else "ASC"} NULLS LAST LIMIT ?""",
                  [report_date, q, f"%{q}%", f"%{q}%", limit])
    return {"report_date": str(report_date), "rows": records(df)}


_etl_lock = threading.Lock()


class FinDownloadReq(BaseModel):
    report_date: dt.date


@app.post("/api/etl/financials")
def download_financials(req: FinDownloadReq):
    """按报告期下载全市场财报（后台线程）。"""
    if req.report_date.month not in (3, 6, 9, 12) or req.report_date.day not in (30, 31):
        raise HTTPException(400, "报告期须为季末日期，如 2024-12-31")
    if not _etl_lock.acquire(blocking=False):
        raise HTTPException(409, "已有下载任务在运行")

    def job():
        from backend.db.conn import log_etl
        from backend.etl.pipeline import sync_financial_period
        task = f"financials:{req.report_date}"
        try:
            log_etl(task, "running", "")
            n = sync_financial_period(req.report_date)
            log_etl(task, "ok", f"{n} rows")
        except Exception as e:  # noqa: BLE001
            log_etl(task, "error", repr(e))
        finally:
            _etl_lock.release()

    threading.Thread(target=job, daemon=True).start()
    return {"started": True}


@app.get("/api/etl/status")
def etl_status():
    return records(query_df("SELECT * FROM etl_log ORDER BY updated_at DESC"))


# ---------------- 公式因子 ----------------
class FormulaReq(BaseModel):
    name: str
    label: str | None = None
    expr: str
    better: str = "high"


class ExprReq(BaseModel):
    expr: str
    name: str | None = None


def _expr_preview(expr: str, name: str | None = None) -> dict:
    """在最新截面上试算公式：覆盖率、分布、前 10 名。"""
    from backend.formula import evaluate, validate
    validate(expr, name)
    df = screener.snapshot()
    df = df[df.is_st != 1]
    v = evaluate(expr, df, by=None)
    ok = v.dropna()
    is_bool = bool(len(ok)) and set(ok.unique()) <= {0.0, 1.0}
    q = ok.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).tolist() if len(ok) else []
    top = df.assign(value=v).dropna(subset=["value"]).sort_values("value", ascending=False).head(10)
    return {"ok": True, "date": str(_latest()), "n": int(len(df)), "coverage": int(len(ok)), "is_bool": is_bool,
            "true_count": int((ok != 0).sum()) if is_bool else None,
            "mean": float(ok.mean()) if len(ok) else None, "quantiles": q,
            "top": records(top[["code", "name", "industry", "value"]])}


@app.post("/api/formulas/validate")
def validate_formula(req: ExprReq):
    try:
        return _expr_preview(req.expr, req.name)
    except FormulaError as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/formulas")
def list_formulas():
    return records(query_df("SELECT name, label, expr, better, created_at FROM custom_factor ORDER BY created_at"))


@app.post("/api/formulas")
def save_formula(req: FormulaReq):
    from backend.formula import NAME_RE, EXTRA_FIELDS, invalidate, validate
    if not NAME_RE.match(req.name):
        raise HTTPException(400, "名称须为小写字母开头，只含小写字母/数字/下划线，2–32 位")
    if req.name in FACTORS or req.name in EXTRA_FIELDS:
        raise HTTPException(400, "名称与内置因子重复")
    if req.better not in ("high", "low"):
        raise HTTPException(400, "better 须为 high 或 low")
    try:
        validate(req.expr, req.name)
    except FormulaError as e:
        raise HTTPException(400, str(e))
    with connect(read_only=False) as con:
        con.execute("DELETE FROM custom_factor WHERE name = ?", [req.name])
        con.execute("INSERT INTO custom_factor (name, label, expr, better) VALUES (?, ?, ?, ?)",
                    [req.name, req.label or req.name, req.expr.strip(), req.better])
    invalidate()
    _analysis_cache.clear()
    return {"ok": True}


@app.delete("/api/formulas/{name}")
def delete_formula(name: str):
    from backend.formula import invalidate, referenced
    others = query_df("SELECT name, expr FROM custom_factor WHERE name <> ?", [name])
    users = [r.name for r in others.itertuples() if name in referenced(r.expr, exclude=r.name)]
    if users:
        raise HTTPException(400, f"以下公式因子引用了它：{', '.join(users)}")
    with connect(read_only=False) as con:
        con.execute("DELETE FROM custom_factor WHERE name = ?", [name])
    invalidate()
    _analysis_cache.clear()
    return {"ok": True}


# ---------------- 因子分析 ----------------
_analysis_cache: dict = {}


def _cached_analysis(key: str, fn):
    from backend.backtest.universe import _panel_version
    from backend.formula import custom_factors
    full = f"{_panel_version()}|{sorted((k, v['expr']) for k, v in custom_factors().items())}|{key}"
    if full not in _analysis_cache:
        if len(_analysis_cache) > 64:
            _analysis_cache.clear()
        _analysis_cache[full] = fn()
    return _analysis_cache[full]


class AnalysisReq(BaseModel):
    factor: str
    direction: str | None = None
    start: dt.date = dt.date(2015, 1, 1)
    end: dt.date | None = None
    freq: str = "M"
    groups: int = Field(5, ge=2, le=10)
    universe: str = "all"
    neutralize: list[str] = []
    pool_id: str | None = None
    expr: str | None = None
    min_amount: float = 0.0


@app.post("/api/analysis/factor")
def analysis_factor(req: AnalysisReq):
    from backend.analysis import AnalysisParams, analyze_factor
    rules, industries, expr = _pool_filters(req.pool_id, [], [], req.expr)
    p = AnalysisParams(factor=req.factor, direction=req.direction, start=req.start, end=req.end, freq=req.freq,
                       groups=req.groups, universe=req.universe, neutralize=req.neutralize, rules=rules,
                       industries=industries, expr=expr, min_amount=req.min_amount)
    try:
        return _cached_analysis("factor:" + req.model_dump_json(), lambda: analyze_factor(p))
    except (ValueError, FormulaError) as e:
        raise HTTPException(400, str(e))


class ScoreboardReq(BaseModel):
    start: dt.date = dt.date(2015, 1, 1)
    end: dt.date | None = None
    freq: str = "M"
    universe: str = "all"
    neutralize: list[str] = []


@app.post("/api/analysis/scoreboard")
def analysis_scoreboard(req: ScoreboardReq):
    from backend.analysis import factor_scoreboard
    try:
        return _cached_analysis("board:" + req.model_dump_json(), lambda: factor_scoreboard(
            req.start, req.end, req.universe, req.freq, req.neutralize))
    except (ValueError, FormulaError) as e:
        raise HTTPException(400, str(e))


class CorrReq(BaseModel):
    factors: list[str]
    start: dt.date = dt.date(2015, 1, 1)
    end: dt.date | None = None
    universe: str = "all"


@app.post("/api/analysis/correlation")
def analysis_correlation(req: CorrReq):
    from backend.analysis import factor_correlation
    try:
        return _cached_analysis("corr:" + req.model_dump_json(), lambda: factor_correlation(
            req.factors, req.start, req.end, req.universe))
    except (ValueError, FormulaError) as e:
        raise HTTPException(400, str(e))


# ---------------- 数据管理 ----------------
ETL_TASKS = {
    "daily": (["etl"], "日常更新：指数 + 行情(增量) + 财报/分红(最近几期) + 因子"),
    "prices": (["prices"], "仅更新行情（增量）"),
    "financials": (["financials"], "补齐全部历史财报"),
    "dividends": (["dividends"], "补齐分红送配"),
    "members": (["members"], "沪深300/中证500 历史成分股"),
    "st": (["st"], "历史 ST 状态（较慢，约 30–40 分钟）"),
    "shares": (["shares"], "退市股流通股本回填（baostock）"),
    "factors": (["factors"], "重建因子表与情绪指数"),
}
_procs: dict = {}


@app.get("/api/data/status")
def data_status():
    from backend.config import DB_PATH
    with connect() as con:
        tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}

        def one(sql):
            try:
                return con.execute(sql).fetchone()
            except Exception:  # noqa: BLE001
                return None

        q = {
            "stock_basic": "SELECT count(*), count(*) FILTER (WHERE status = 1), count(*) FILTER (WHERE status = 0), NULL FROM stock_basic",
            "daily_bar": "SELECT count(*), count(DISTINCT code), min(date), max(date) FROM daily_bar",
            "adj_factor": "SELECT count(*), count(DISTINCT code), min(date), max(date) FROM adj_factor",
            "index_daily": "SELECT count(*), count(DISTINCT code), min(date), max(date) FROM index_daily",
            "financial_report": "SELECT count(*), count(DISTINCT report_date), min(report_date), max(report_date) FROM financial_report",
            "dividend": "SELECT count(*), count(DISTINCT report_date), min(report_date), max(report_date) FROM dividend",
            "index_member": "SELECT count(*), count(DISTINCT date), min(date), max(date) FROM index_member",
            "st_daily": "SELECT count(*), count(DISTINCT code), min(date), max(date) FROM st_daily",
            "factor_daily": "SELECT count(*), count(DISTINCT code), min(date), max(date) FROM factor_daily",
            "market_sentiment": "SELECT count(*), NULL, min(date), max(date) FROM market_sentiment",
        }
        labels = {
            "stock_basic": ("股票列表", "全部 / 上市 / 退市"), "daily_bar": ("日线行情", "股票数"),
            "adj_factor": ("复权因子", "股票数"), "index_daily": ("指数日线", "指数数"),
            "financial_report": ("财报", "报告期数"), "dividend": ("分红送配", "报告期数"),
            "index_member": ("历史成分股", "快照数"), "st_daily": ("历史 ST", "涉及股票数"),
            "factor_daily": ("因子宽表", "股票数"), "market_sentiment": ("情绪指数", ""),
        }
        rows = []
        for t, sql in q.items():
            r = one(sql) if t in tables else None
            rows.append({"table": t, "label": labels[t][0], "unit": labels[t][1],
                         "rows": r[0] if r else 0, "count": r[1] if r else None,
                         "extra": r[2] if (r and t == "stock_basic") else None,
                         "start": str(r[2])[:10] if (r and r[2] is not None and t != "stock_basic") else None,
                         "end": str(r[3])[:10] if (r and r[3] is not None) else None})
        coverage = one("""SELECT count(*) FILTER (WHERE s.status = 1), count(*) FILTER (WHERE s.status = 0)
                          FROM (SELECT DISTINCT code FROM daily_bar) b JOIN stock_basic s USING (code)""") if "daily_bar" in tables else None
        etl = con.execute("SELECT task, status, message, updated_at FROM etl_log ORDER BY updated_at DESC").df()
    running = {k: v["started"] for k, v in _procs.items() if v["proc"].poll() is None}
    return {"tables": rows, "etl": records(etl), "db_size_mb": round(DB_PATH.stat().st_size / 2**20, 1),
            "coverage": {"listed": coverage[0], "delisted": coverage[1]} if coverage else None,
            "tasks": [{"key": k, "label": v[1], "running": k in running, "started": running.get(k)}
                      for k, v in ETL_TASKS.items()]}


class EtlReq(BaseModel):
    task: str


@app.post("/api/data/run")
def data_run(req: EtlReq):
    """以子进程运行 ETL 任务，日志写入 logs/<task>.log。"""
    import subprocess
    import sys
    if req.task not in ETL_TASKS:
        raise HTTPException(400, "未知任务")
    if any(v["proc"].poll() is None for v in _procs.values()):
        raise HTTPException(409, "已有任务在运行，请等待完成")
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    f = open(logs / f"{req.task}.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "backend.cli", *ETL_TASKS[req.task][0]], cwd=ROOT,
                            stdout=f, stderr=subprocess.STDOUT)
    _procs[req.task] = {"proc": proc, "started": dt.datetime.now().isoformat(timespec="seconds")}
    return {"started": True}


@app.get("/api/data/log/{task}")
def data_log(task: str, lines: int = 40):
    if task not in ETL_TASKS:
        raise HTTPException(404)
    path = ROOT / "logs" / f"{task}.log"
    if not path.exists():
        return {"lines": []}
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    text = [t for t in text if " INFO " in t or "ERROR" in t or "WARNING" in t or "Traceback" in t]
    return {"lines": text[-lines:]}


# 生产模式：直接托管前端构建产物
_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
