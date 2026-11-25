"""因子分析：IC / IR、分层回测、IC 衰减、因子相关性、全因子看板。

口径：
- 信号日 T 收盘计算因子（同回测：股票池 → 过滤 → 去极值标准化 → 可选中性化，并乘以方向使"越大越好"）
- 前瞻收益 = T 到下一个信号日的后复权收盘价收益（停牌沿用最后价，退市按最后价）
- IC = 因子值与前瞻收益的 Spearman 秩相关；IR = IC 均值 / IC 标准差（年化乘以 sqrt(每年期数)）
- 分层：按方向调整后的因子值分 N 组等权，G1 最差，GN 最好；多空 = GN − G1；不计交易成本
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.backtest import universe as U
from backend.formula import all_factors, materialize

PERIODS_PER_YEAR = {"W": 52, "M": 12, "Q": 4}


@dataclass
class AnalysisParams:
    factor: str
    direction: str | None = None
    start: dt.date = dt.date(2015, 1, 1)
    end: dt.date | None = None
    freq: str = "M"
    groups: int = 5
    universe: str = "all"
    neutralize: list[str] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    expr: str | None = None
    exclude_st: bool = True
    min_listed_days: int = 365
    min_amount: float = 0.0


def _rank_ic(x: np.ndarray, y: np.ndarray) -> float:
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 20:
        return np.nan
    xr = pd.Series(x[m]).rank().values
    yr = pd.Series(y[m]).rank().values
    if xr.std() == 0 or yr.std() == 0:
        return np.nan
    return float(np.corrcoef(xr, yr)[0, 1])


def _clean(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return round(f, 6) if np.isfinite(f) else None


def _setup(start, end, freq):
    P = U.price_panel()
    cal = [d for d in P["cal"] if d >= start and (end is None or d <= end)]
    if len(cal) < 60:
        raise ValueError("分析区间交易日不足")
    sig = U.signal_dates(cal, freq)
    return P, sig


def _forward_returns(P, sig) -> dict:
    """{信号日: Series(code -> 下一期收益)}，最后一个信号日没有前瞻收益。"""
    cf, didx, codes = P["close_ff"], P["didx"], P["codes"]
    out = {}
    for a, b in zip(sig[:-1], sig[1:]):
        ia, ib = didx[a], didx[b]
        with np.errstate(all="ignore"):
            r = cf[ib].astype(float) / cf[ia].astype(float) - 1
        out[a] = pd.Series(r, index=codes)
    return out


def _factor_panel(p_like, names, sig, directions=None, with_neutral=True) -> dict:
    """{信号日: DataFrame(code, 各因子标准化值[方向已调整], industry, float_mv)}"""
    cols = U.snapshot_columns(names, p_like.rules, p_like.expr)
    snaps = U.load_snapshots(sig, cols)
    out = {}
    for d in sig:
        if d not in snaps:
            continue
        df = U.filter_cross_section(snaps[d], d, p_like.universe, p_like.exclude_st, p_like.min_listed_days,
                                    p_like.rules, p_like.industries, p_like.expr, p_like.min_amount)
        df = materialize(df, names, by=None)
        if len(df) < 20:
            continue
        z = pd.DataFrame(index=df.index)
        for n in names:
            x = df[n].astype(float)
            ok = x.notna()
            v = pd.Series(np.nan, index=df.index)
            if ok.sum() >= 20:
                zz = U.winsor_z(x[ok])
                if with_neutral and p_like.neutralize:
                    zz = U.neutralize(zz, df.loc[ok], p_like.neutralize)
                sign = U.factor_sign(n, (directions or {}).get(n))
                v[ok] = zz * sign
            z[n] = v
        z["code"] = df.code.values
        z["industry"] = df.industry.values
        out[d] = z
    return out


def analyze_factor(p: AnalysisParams) -> dict:
    if p.factor not in all_factors():
        raise ValueError(f"未知因子: {p.factor}")
    if p.freq not in PERIODS_PER_YEAR:
        raise ValueError("频率须为 W / M / Q")
    P, sig = _setup(p.start, p.end, p.freq)
    fwd = _forward_returns(P, sig)
    panel = _factor_panel(p, [p.factor], sig, {p.factor: p.direction})
    dates = [d for d in sig[:-1] if d in panel]
    if len(dates) < 6:
        raise ValueError("有效截面不足（检查股票池或过滤条件）")

    ppy = PERIODS_PER_YEAR[p.freq]
    ic, coverage, grp_ret, top_sets, turnover = [], [], [], [], []
    G = max(2, min(int(p.groups), 10))
    for d in dates:
        z = panel[d]
        x = z[p.factor].values
        y = fwd[d].reindex(z.code).values
        ic.append(_rank_ic(x, y))
        m = np.isfinite(x) & np.isfinite(y)
        coverage.append(int(m.sum()))
        if m.sum() >= G * 3:
            q = pd.qcut(pd.Series(x[m]).rank(method="first"), G, labels=False)
            yr = pd.Series(y[m])
            grp_ret.append([float(yr[q == g].mean()) for g in range(G)])
            top = set(z.code.values[m][q.values == G - 1])
        else:
            grp_ret.append([np.nan] * G)
            top = set()
        if top_sets and top and top_sets[-1]:
            turnover.append(1 - len(top & top_sets[-1]) / max(len(top), 1))
        top_sets.append(top)

    ic_s = pd.Series(ic, index=dates)
    icv = ic_s.dropna()
    gr = pd.DataFrame(grp_ret, index=dates, columns=[f"G{g + 1}" for g in range(G)]).fillna(0)
    ls = gr[f"G{G}"] - gr["G1"]
    nav = (1 + gr).cumprod()
    ls_nav = (1 + ls).cumprod()
    # 基准：池内等权平均
    univ = pd.Series([float(np.nanmean(fwd[d].reindex(panel[d].code).values)) for d in dates], index=dates).fillna(0)
    univ_nav = (1 + univ).cumprod()

    def ann(r: pd.Series):
        n = len(r)
        tot = float((1 + r).prod())
        return tot ** (ppy / n) - 1 if n and tot > 0 else None

    def mdd(navs: pd.Series):
        return float((navs / navs.cummax() - 1).min())

    # 行情结束日（最后一期前瞻收益的终点）作为曲线末端
    end_dates = [str(sig[sig.index(d) + 1]) for d in dates]
    group_ann = [ann(gr[c]) for c in gr.columns]
    mono = pd.Series(group_ann).corr(pd.Series(range(G)), method="spearman") if None not in group_ann else None

    # IC 衰减：因子与第 k 期之后收益的 IC
    decay = []
    for k in range(1, 7):
        vals = []
        for i, d in enumerate(dates):
            j = sig.index(d) + k - 1
            if j >= len(sig) - 1:
                break
            z = panel[d]
            vals.append(_rank_ic(z[p.factor].values, fwd[sig[j]].reindex(z.code).values))
        v = pd.Series(vals).dropna()
        decay.append({"lag": k, "ic": _clean(v.mean()) if len(v) else None})

    yearly = []
    for y, g in ic_s.groupby([d.year for d in ic_s.index]):
        lsy = ls[[d.year == y for d in ls.index]]
        yearly.append({"year": int(y), "ic": _clean(g.mean()), "ls_return": _clean((1 + lsy).prod() - 1),
                       "top_return": _clean((1 + gr[f"G{G}"][[d.year == y for d in gr.index]]).prod() - 1)})

    std = icv.std()
    stats = {
        "ic_mean": icv.mean(), "ic_std": std, "ir": icv.mean() / std if std else None,
        "ir_annual": icv.mean() / std * np.sqrt(ppy) if std else None,
        "t_stat": icv.mean() / std * np.sqrt(len(icv)) if std else None,
        "ic_positive": (icv > 0).mean(), "ic_abs_gt_002": (icv.abs() > 0.02).mean(),
        "ls_annual": ann(ls), "ls_max_drawdown": mdd(ls_nav), "ls_sharpe":
            ls.mean() / ls.std() * np.sqrt(ppy) if ls.std() else None,
        "top_annual": group_ann[-1], "bottom_annual": group_ann[0], "universe_annual": ann(univ),
        "top_excess": (group_ann[-1] - ann(univ)) if group_ann[-1] is not None and ann(univ) is not None else None,
        "monotonicity": mono, "top_turnover": float(np.mean(turnover)) if turnover else None,
        "avg_coverage": float(np.mean(coverage)), "periods": len(dates),
        "start": str(dates[0]), "end": end_dates[-1],
    }
    return {
        "factor": p.factor, "label": all_factors()[p.factor]["label"], "groups": G,
        "stats": {k: _clean(v) if not isinstance(v, str) else v for k, v in stats.items()},
        "ic": {"dates": [str(d) for d in dates], "values": [_clean(v) for v in ic_s],
               "cum": [_clean(v) for v in ic_s.fillna(0).cumsum()],
               "ma12": [_clean(v) for v in ic_s.rolling(12, min_periods=3).mean()]},
        "quantiles": {"dates": [str(dates[0])] + end_dates,
                      "nav": {c: [1.0] + [_clean(v) for v in nav[c]] for c in nav.columns},
                      "long_short": [1.0] + [_clean(v) for v in ls_nav],
                      "universe": [1.0] + [_clean(v) for v in univ_nav],
                      "annual": [_clean(v) for v in group_ann]},
        "decay": decay,
        "yearly": yearly,
        "coverage": coverage,
    }


def factor_correlation(names: list[str], start: dt.date, end: dt.date | None, universe: str = "all",
                       freq: str = "M", sample: int = 48) -> dict:
    """因子间截面 Spearman 相关系数的时间均值（为速度只抽样最多 sample 个截面）。"""
    known = all_factors()
    names = [n for n in dict.fromkeys(names) if n in known]
    if len(names) < 2:
        raise ValueError("至少选择 2 个因子")
    _, sig = _setup(start, end, freq)
    if len(sig) > sample:
        idx = np.linspace(0, len(sig) - 1, sample).round().astype(int)
        sig = [sig[i] for i in sorted(set(idx))]
    p_like = AnalysisParams(factor=names[0], universe=universe)
    panel = _factor_panel(p_like, names, sig, with_neutral=False)
    mats = []
    for z in panel.values():
        r = z[names].rank().corr()
        mats.append(r.values)
    if not mats:
        raise ValueError("没有有效截面")
    m = np.nanmean(np.stack(mats), axis=0)
    return {"factors": names, "labels": [known[n]["label"] for n in names],
            "matrix": [[_clean(v) for v in row] for row in m], "samples": len(mats)}


def factor_scoreboard(start: dt.date, end: dt.date | None, universe: str = "all", freq: str = "M",
                      neutralize: list[str] | None = None, groups: int = 5) -> list[dict]:
    """全部因子一次性计算 IC / IR / 多空收益，用于因子看板排序。"""
    names = list(all_factors())
    P, sig = _setup(start, end, freq)
    fwd = _forward_returns(P, sig)
    p_like = AnalysisParams(factor=names[0], universe=universe, neutralize=neutralize or [])
    ok_names = []
    for n in names:  # 跳过计算出错的公式因子
        try:
            U.snapshot_columns([n])
            ok_names.append(n)
        except Exception:  # noqa: BLE001
            pass
    panel = _factor_panel(p_like, ok_names, sig)
    dates = [d for d in sig[:-1] if d in panel]
    ppy = PERIODS_PER_YEAR.get(freq, 12)
    meta = all_factors()
    rows = []
    for n in ok_names:
        ics, ls = [], []
        for d in dates:
            z = panel[d]
            x = z[n].values
            y = fwd[d].reindex(z.code).values
            ics.append(_rank_ic(x, y))
            m = np.isfinite(x) & np.isfinite(y)
            if m.sum() >= groups * 3:
                q = pd.qcut(pd.Series(x[m]).rank(method="first"), groups, labels=False).values
                yy = y[m]
                ls.append(float(yy[q == groups - 1].mean() - yy[q == 0].mean()))
            else:
                ls.append(0.0)
        icv = pd.Series(ics).dropna()
        lsr = pd.Series(ls)
        tot = float((1 + lsr).prod())
        std = icv.std()
        rows.append({
            "factor": n, "label": meta[n]["label"], "group": meta[n]["group"], "better": meta[n]["better"],
            "ic_mean": _clean(icv.mean()), "ir": _clean(icv.mean() / std) if std else None,
            "ir_annual": _clean(icv.mean() / std * np.sqrt(ppy)) if std else None,
            "ic_positive": _clean((icv > 0).mean()),
            "t_stat": _clean(icv.mean() / std * np.sqrt(len(icv))) if std else None,
            "ls_annual": _clean(tot ** (ppy / len(lsr)) - 1) if len(lsr) and tot > 0 else None,
            "periods": len(icv),
            "spark": [_clean(v) for v in pd.Series(ics).fillna(0).cumsum()],
        })
    rows.sort(key=lambda r: -(abs(r["ir"]) if r["ir"] is not None else -1))
    return rows
