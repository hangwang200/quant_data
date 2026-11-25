"""绩效指标。"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _max_dd(nav: pd.Series):
    peak = nav.cummax()
    dd = nav / peak - 1
    trough = dd.idxmin()
    peak_date = nav.loc[:trough].idxmax()
    return float(dd.min()), peak_date, trough, dd


def _ann(nav: pd.Series) -> float:
    n = len(nav) - 1
    return float(nav.iloc[-1] ** (TRADING_DAYS / n) - 1) if n > 0 else 0.0


def _clean(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 6)


def summarize(nav: pd.Series, bench: pd.Series, turnovers: list[float]) -> dict:
    ret = nav.pct_change().dropna()
    bret = bench.pct_change().dropna()
    ann_ret, bench_ann = _ann(nav), _ann(bench)
    ann_vol = float(ret.std() * np.sqrt(TRADING_DAYS))
    mdd, peak_d, trough_d, dd = _max_dd(nav)
    bmdd, *_ = _max_dd(bench)
    excess = (ret - bret.reindex(ret.index).fillna(0))
    te = float(excess.std() * np.sqrt(TRADING_DAYS))
    m_nav = nav.resample("ME").last()
    m_bench = bench.resample("ME").last()
    m_ret = m_nav.pct_change().dropna()
    m_bret = m_bench.pct_change().reindex(m_ret.index)
    y_nav = nav.resample("YE").last()
    y_bench = bench.resample("YE").last()
    y_ret = (y_nav / pd.concat([pd.Series([1.0], index=[nav.index[0]]), y_nav.iloc[:-1]]).values - 1)
    y_bret = (y_bench / pd.concat([pd.Series([1.0], index=[bench.index[0]]), y_bench.iloc[:-1]]).values - 1)

    metrics = {
        "total_return": nav.iloc[-1] - 1,
        "annual_return": ann_ret,
        "annual_vol": ann_vol,
        "sharpe": (ret.mean() * TRADING_DAYS) / ann_vol if ann_vol else None,
        "max_drawdown": mdd,
        "max_dd_start": str(peak_d.date()),
        "max_dd_end": str(trough_d.date()),
        "calmar": ann_ret / abs(mdd) if mdd else None,
        "bench_annual_return": bench_ann,
        "bench_max_drawdown": bmdd,
        "excess_annual": ann_ret - bench_ann,
        "info_ratio": (excess.mean() * TRADING_DAYS) / te if te else None,
        "monthly_win_rate": float((m_ret > m_bret).mean()) if len(m_ret) else None,
        "avg_turnover": float(np.mean(turnovers)) if turnovers else 0.0,
        "start": str(nav.index[0].date()),
        "end": str(nav.index[-1].date()),
    }
    metrics = {k: (_clean(v) if not isinstance(v, str) else v) for k, v in metrics.items()}

    # 降采样到周频以减小传输量（10 年约 520 点）
    weekly = pd.DataFrame({"nav": nav, "bench": bench, "dd": dd}).resample("W-FRI").last().dropna()
    monthly = [{"year": d.year, "month": d.month, "ret": _clean(r)} for d, r in m_ret.items()]
    yearly = [{"year": d.year, "ret": _clean(r), "bench": _clean(b)}
              for d, r, b in zip(y_nav.index, y_ret, y_bret)]
    return {
        "metrics": metrics,
        "series": {
            "dates": [str(d.date()) for d in weekly.index],
            "nav": [round(x, 4) for x in weekly.nav],
            "bench": [round(x, 4) for x in weekly.bench],
            "drawdown": [round(x, 4) for x in weekly.dd],
        },
        "monthly": monthly,
        "yearly": yearly,
    }
