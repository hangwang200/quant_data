import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backend.backtest.engine import BacktestParams, FactorSpec, run_backtest
from backend.backtest.metrics import _max_dd
from backend.etl.akshare_src import deadline, to_bs_code
from backend.screener import apply_rules


def test_code_mapping():
    assert to_bs_code("600519") == "sh.600519"
    assert to_bs_code("1") == "sz.000001"
    assert to_bs_code("300750") == "sz.300750"
    assert to_bs_code("920001") == "bj.920001"
    assert to_bs_code("830799") == "bj.830799"


def test_deadline():
    assert deadline(dt.date(2023, 12, 31)) == dt.date(2024, 4, 30)
    assert deadline(dt.date(2024, 6, 30)) == dt.date(2024, 8, 31)


def test_financials_point_in_time(synth_db, con):
    """2019 年报(ROE=99) 在 2020-04-20 之前不可见。"""
    before = con.execute("SELECT roe_ann FROM factor_daily WHERE code='sh.600003' AND date='2020-04-17'").fetchone()[0]
    after = con.execute("SELECT roe_ann FROM factor_daily WHERE code='sh.600003' AND date='2020-04-20'").fetchone()[0]
    assert before == 5.0 and after == 99.0


def test_adjusted_price_continuous_through_split(synth_db, con):
    split = synth_db["split"]
    df = con.execute("SELECT date, close, close_hfq, pe_ttm FROM factor_daily WHERE code='sh.600002' ORDER BY date").df()
    assert df.close_hfq.round(6).nunique() == 1  # 后复权价恒为 10
    # PE 用"复权价 / (EPS × 公告时复权因子)"，送转后不应跳变
    i = df.index[df.date == pd.Timestamp(split)][0]
    assert df.pe_ttm.iloc[i - 1] == pytest.approx(10.0)
    assert df.pe_ttm.iloc[i] == pytest.approx(10.0)


def test_rules():
    df = pd.DataFrame({"roe_ann": [5, 15, 25], "pe_ttm": [10, 30, 8], "industry": ["A", "B", "A"]})
    assert len(apply_rules(df, [{"field": "roe_ann", "min": 10, "max": None}])) == 2
    assert len(apply_rules(df, [{"field": "roe_ann", "min": 10}, {"field": "pe_ttm", "max": 10}])) == 1
    assert len(apply_rules(df, [], ["A"])) == 2
    with pytest.raises(ValueError):
        apply_rules(df, [{"field": "drop table", "min": 1}])


def test_backtest_picks_momentum_winner(synth_db):
    p = BacktestParams(factors=[FactorSpec("mom_60", 1, "high")], start=dt.date(2019, 6, 1), top_n=1,
                       commission=0, slippage=0)
    r = run_backtest(p)
    assert r["holdings"]["stocks"][0]["code"] == "sh.600001"
    m = r["metrics"]
    # 每日 +0.1%，零成本时年化 ≈ 1.001^252 - 1；首个持有日从开盘价买入
    assert m["annual_return"] == pytest.approx(1.001 ** 252 - 1, rel=0.02)
    assert m["max_drawdown"] == pytest.approx(0, abs=1e-6)


def test_backtest_costs_reduce_return(synth_db):
    base = dict(factors=[FactorSpec("mom_20", 1, "low")], start=dt.date(2019, 6, 1), top_n=1)
    free = run_backtest(BacktestParams(**base, commission=0, slippage=0))["metrics"]["total_return"]
    paid = run_backtest(BacktestParams(**base, commission=0.001, slippage=0.002))["metrics"]["total_return"]
    assert paid < free


def test_backtest_rules_filter_pool(synth_db):
    # 只允许行业 B（仅下跌股），即使动量最差也只能持有它
    p = BacktestParams(factors=[FactorSpec("mom_60", 1, "high")], start=dt.date(2019, 6, 1), top_n=3,
                       industries=["B"])
    r = run_backtest(p)
    assert [s["code"] for s in r["holdings"]["stocks"]] == ["sh.600003"]
    assert r["metrics"]["total_return"] < 0


def test_max_drawdown():
    nav = pd.Series([1.0, 1.2, 0.9, 1.1, 1.3], index=pd.date_range("2020-01-01", periods=5))
    dd, peak, trough, _ = _max_dd(nav)
    assert dd == pytest.approx(0.9 / 1.2 - 1)
    assert peak == nav.index[1] and trough == nav.index[2]


def test_limit_up_blocks_buy(synth_db):
    """执行日一字涨停的目标股不能买入，资金留在现金。"""
    import backend.backtest.universe as U

    U.clear_cache()
    P = U.price_panel()
    P["limup"][:, P["cidx"]["sh.600001"]] = True  # 稳涨股每天一字涨停
    r = run_backtest(BacktestParams(factors=[FactorSpec("mom_60", 1, "high")], start=dt.date(2019, 6, 1), top_n=1,
                                    commission=0, slippage=0))
    assert r["metrics"]["total_return"] == pytest.approx(0, abs=1e-9)
    assert r["holdings"]["stocks"] == []
    U.clear_cache()
