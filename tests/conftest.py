"""测试使用独立的临时 DuckDB，并灌入可手算结果的合成数据。"""
import datetime as dt
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp()) / "test.duckdb"
os.environ["QUANT_DB"] = str(_tmp)  # 必须在导入 backend 之前设置

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backend.db.conn import connect, upsert_df  # noqa: E402
from backend.factors.build import build_all  # noqa: E402

CODES = ["sh.600001", "sh.600002", "sh.600003"]


def trading_days(start: dt.date, n: int) -> list[dt.date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


@pytest.fixture(scope="session")
def synth_db():
    days = trading_days(dt.date(2019, 1, 2), 420)
    basic = pd.DataFrame({
        "code": CODES, "name": ["稳涨", "持平", "下跌"], "industry": ["A", "A", "B"],
        "ipo_date": [dt.date(2010, 1, 1)] * 3, "out_date": [None] * 3, "status": [1] * 3,
        "in_universe": [True] * 3, "universe_src": ["hs300"] * 3,
    })
    upsert_df("stock_basic", basic, ["code"])
    rows = []
    # 稳涨: 每日 +0.1%；持平: 10 元不变；下跌: 每日 -0.1%
    for i, d in enumerate(days):
        for code, px in zip(CODES, [10 * 1.001 ** i, 10.0, 10 * 0.999 ** i]):
            rows.append(dict(code=code, date=d, open=px, high=px * 1.01, low=px * 0.99, close=px,
                             volume=1e6, amount=1e7, turnover=1.0, pct_chg=None, float_share=1e8, trade_status=1))
    bars = pd.DataFrame(rows)
    # sh.600002 在第 300 天 10 送 10：不复权价减半，复权因子翻倍 —— 后复权价保持连续
    split = days[300]
    m = (bars.code == "sh.600002") & (bars.date >= split)
    bars.loc[m, ["open", "high", "low", "close"]] /= 2
    upsert_df("daily_bar", bars, ["code", "date"])
    upsert_df("adj_factor", pd.DataFrame({"code": ["sh.600002"] * 2, "date": [dt.date(1900, 1, 1), split],
                                          "back_factor": [1.0, 2.0]}), ["code", "date"])
    upsert_df("index_daily", pd.DataFrame({"code": "sh.000300", "date": days, "open": 1000.0, "high": 1000.0,
                                           "low": 1000.0, "close": [1000 * 1.0005 ** i for i in range(len(days))],
                                           "amount": None, "pct_chg": 0.05}), ["code", "date"])
    # 财报：sh.600001 ROE 高，但 2019 年报到 2020-04-30 才可用
    fin = []
    for code, roe in zip(CODES, [30.0, 10.0, 5.0]):
        fin.append(dict(code=code, report_date=dt.date(2018, 12, 31), name=code, announce_date=dt.date(2019, 3, 1),
                        effective_date=dt.date(2019, 3, 1), eps=1.0, bps=5.0, roe=roe, roe_ann=roe,
                        revenue=1e9, revenue_yoy=10.0, net_profit=1e8, net_profit_yoy=10.0, gross_margin=30.0))
    fin.append(dict(code="sh.600003", report_date=dt.date(2019, 12, 31), name="x", announce_date=dt.date(2020, 4, 20),
                    effective_date=dt.date(2020, 4, 20), eps=1.0, bps=5.0, roe=99.0, roe_ann=99.0,
                    revenue=1e9, revenue_yoy=10.0, net_profit=1e8, net_profit_yoy=10.0, gross_margin=30.0))
    upsert_df("financial_report", pd.DataFrame(fin), ["code", "report_date"])
    # 分红：sh.600002 送转后每股派 0.5（后复权口径 = 0.5 × 2 = 1.0，股价后复权 10 → 股息率 10%）
    #       sh.600003 2019 年报每股派 0.3，EPS 1.0 → 分红率 30%，预案 2020-04-25 公告
    ex = days[350]
    upsert_df("dividend", pd.DataFrame([
        dict(code="sh.600002", report_date=dt.date(2019, 12, 31), dps=0.5, plan_date=days[340], ex_date=ex,
             progress="实施分配"),
        dict(code="sh.600003", report_date=dt.date(2019, 12, 31), dps=0.3, plan_date=dt.date(2020, 4, 25),
             ex_date=None, progress="股东大会预案"),
    ]), ["code", "report_date"])
    build_all()
    return {"days": days, "split": split, "ex": ex}


@pytest.fixture()
def con():
    with connect() as c:
        yield c
