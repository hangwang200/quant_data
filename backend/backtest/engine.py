"""因子选股回测引擎。

流程（每个调仓周期）：
  1. 信号日 T（月末/周末/季末最后一个交易日）收盘后，用 T 日及之前可知的数据：
     股票池（历史成分股）→ 过滤（ST/上市天数/规则/公式）→ 因子去极值标准化（可行业市值中性化）→ 加权打分取 Top N
  2. T+1 开盘价执行调仓：
     - 停牌（无行情）的持仓无法卖出，继续持有
     - 一字跌停的待卖股票无法卖出；一字涨停的新股票无法买入
     - 退市股票在最后交易日之后按最后价格卖出
     - 其余资金在可买的目标股票间等权分配
  3. 持有期内按收盘价逐日计算净值（买入持有，权重自然漂移）
成本：佣金(双边) + 滑点(双边) + 印花税(卖出，2023-08-28 起减半)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.backtest import universe as U
from backend.db.conn import query_df
from backend.formula import all_factors

STAMP_CUT = dt.date(2023, 8, 28)


@dataclass
class FactorSpec:
    name: str
    weight: float = 1.0
    direction: str | None = None  # "high" 越大越好 / "low" 越小越好；None 用默认

    def sign(self) -> float:
        return U.factor_sign(self.name, self.direction)


@dataclass
class BacktestParams:
    factors: list[FactorSpec]
    start: dt.date = dt.date(2015, 1, 1)
    end: dt.date | None = None
    freq: str = "M"                 # M 月度 / W 周度 / Q 季度
    top_n: int = 30
    rules: list[dict] = field(default_factory=list)       # 股票池条件，同选股器
    industries: list[str] = field(default_factory=list)
    expr: str | None = None         # 过滤公式（结果为真的股票入池）
    universe: str = "all"
    neutralize: list[str] = field(default_factory=list)   # industry / size
    benchmark: str = "sh.000300"
    commission: float = 0.00025
    slippage: float = 0.001
    min_listed_days: int = 365
    min_amount: float = 0.0         # 20 日均成交额下限（亿元）
    exclude_st: bool = True


def _stamp(d: dt.date) -> float:
    return 0.0005 if d >= STAMP_CUT else 0.001


def score_cross_section(snap: pd.DataFrame, p: BacktestParams, d: dt.date | None = None) -> pd.DataFrame:
    """对单个截面：过滤 → 去极值标准化(→中性化) → 加权打分。返回按得分降序的 DataFrame。"""
    d = d or (snap.date.iloc[0] if len(snap) else dt.date.today())
    df = U.filter_cross_section(snap, d, p.universe, p.exclude_st, p.min_listed_days, p.rules, p.industries,
                                p.expr, p.min_amount)
    names = [f.name for f in p.factors]
    from backend.formula import materialize
    df = materialize(df, names, by=None)
    df = df.dropna(subset=names)
    if df.empty:
        return df.assign(score=pd.Series(dtype=float))
    score = U.composite_score(df, [(f.name, f.weight, f.direction) for f in p.factors], p.neutralize)
    return df.assign(score=score).sort_values("score", ascending=False)


def run_backtest(p: BacktestParams) -> dict:
    known = all_factors()
    for f in p.factors:
        if f.name not in known:
            raise ValueError(f"未知因子: {f.name}")
    end = p.end or dt.date.today()
    P = U.price_panel()
    cal_all = P["cal"]
    i0 = next((i for i, d in enumerate(cal_all) if d >= p.start), len(cal_all))
    i1 = max((i for i, d in enumerate(cal_all) if d <= end), default=-1) + 1
    cal_list = cal_all[i0:i1]
    if len(cal_list) < 30:
        raise ValueError("回测区间交易日不足")
    sig_dates = U.signal_dates(cal_list, p.freq)[:-1]  # 最后一个信号日无下一交易日执行，丢弃

    cols = U.snapshot_columns([f.name for f in p.factors], p.rules, p.expr)
    snaps = U.load_snapshots(sig_dates, cols)

    codes, cidx = P["codes"], P["cidx"]
    open_ = P["open"][i0:i1]
    close_ff = P["close_ff"][i0:i1]
    limup, limdn = P["limup"][i0:i1], P["limdn"][i0:i1]
    didx = {d: i for i, d in enumerate(cal_list)}

    # 信号 -> 执行日的目标持仓
    exec_targets: dict[int, list[str]] = {}
    for d in sig_dates:
        i = didx.get(d)
        if i is None or i + 1 >= len(cal_list) or d not in snaps:
            continue
        ranked = score_cross_section(snaps[d], p, d)
        exec_targets[i + 1] = ranked.code.head(p.top_n).tolist()

    cash, units = 1.0, np.zeros(len(codes))
    nav = np.empty(len(cal_list))
    turnovers, holdings_log = [], []
    started = False
    for i, d in enumerate(cal_list):
        if i in exec_targets:
            started = True
            tgt = np.zeros(len(codes), bool)
            for c in exec_targets[i]:
                if c in cidx:
                    tgt[cidx[c]] = True
            o = open_[i].astype(float)
            tradable = ~np.isnan(o)
            ref_px = np.where(tradable, o, close_ff[i - 1] if i > 0 else o)
            ref_px = np.nan_to_num(ref_px)
            val = units * ref_px
            held = units > 0
            locked = held & (~tradable | (~tgt & limdn[i]))
            buyable = tgt & tradable & ~locked & (~limup[i] | held)
            total = cash + val.sum()
            free = total - val[locked].sum()
            new_val = np.zeros(len(codes))
            nb = buyable.sum()
            if nb > 0:
                new_val[buyable] = free / nb
            movable = ~locked
            diff = new_val[movable] - val[movable]
            buys, sells = diff[diff > 0].sum(), -diff[diff < 0].sum()
            cost = buys * (p.commission + p.slippage) + sells * (p.commission + p.slippage + _stamp(d))
            if nb > 0:
                new_val *= (free - cost) / free if free > 0 else 0
                cash = 0.0
            else:
                cash = free - cost
            new_units = np.where(locked, units, 0.0)
            with np.errstate(divide="ignore", invalid="ignore"):
                new_units[buyable] = new_val[buyable] / o[buyable]
            units = new_units
            turnovers.append((buys + sells) / 2 / total if total > 0 else 0)
            holdings_log.append({"date": str(d), "codes": [codes[k] for k in np.flatnonzero(units > 0)]})
        nav[i] = cash + np.nansum(units * close_ff[i]) if started else 1.0

    nav_s = pd.Series(nav, index=pd.to_datetime(cal_list))
    first_exec = min(exec_targets) if exec_targets else 0
    nav_s = nav_s.iloc[max(first_exec - 1, 0):]
    nav_s = nav_s / nav_s.iloc[0]

    bench = query_df("SELECT date, close FROM index_daily WHERE code = ? AND date BETWEEN ? AND ? ORDER BY date",
                     [p.benchmark, nav_s.index[0].date(), end])
    bench_s = pd.Series(bench.close.values, index=pd.to_datetime(bench.date)).reindex(nav_s.index).ffill()
    bench_s = bench_s / bench_s.iloc[0]

    from backend.backtest.metrics import summarize
    result = summarize(nav_s, bench_s, turnovers)
    result["holdings"] = _last_holdings(holdings_log)
    result["n_rebalance"] = len(turnovers)
    return result


def _last_holdings(log: list[dict]) -> dict:
    if not log:
        return {"date": None, "stocks": []}
    last = log[-1]
    if not last["codes"]:
        return {"date": last["date"], "stocks": []}
    info = query_df("SELECT code, name, industry FROM stock_basic WHERE code IN (SELECT unnest(?::VARCHAR[]))",
                    [last["codes"]])
    return {"date": last["date"], "stocks": info.to_dict("records")}
