import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backend.backtest import universe as U
from backend.backtest.engine import BacktestParams, FactorSpec, run_backtest
from backend.db.conn import connect, upsert_df
from backend.formula import FormulaError, base_columns, evaluate, invalidate, validate


@pytest.fixture()
def df():
    return pd.DataFrame({
        "date": [1, 1, 1, 2, 2, 2],
        "industry": ["A", "A", "B", "A", "A", "B"],
        "pe_ttm": [10.0, 20.0, np.nan, 5.0, -3.0, 40.0],
        "roe_ann": [20.0, 10.0, 5.0, 30.0, 8.0, 1.0],
        "ep": [10.0, 5.0, 2.0, 20.0, 1.0, 2.5],
    })


def test_formula_arithmetic_and_nan(df):
    v = evaluate("ep * 2 + roe_ann / 10", df)
    assert v.tolist() == pytest.approx([22, 11, 4.5, 43, 2.8, 5.1])
    v = evaluate("1 / pe_ttm", df)
    assert np.isnan(v.iloc[2])
    assert evaluate("where(pe_ttm > 0, 1 / pe_ttm, 0)", df).iloc[4] == 0


def test_formula_logic(df):
    v = evaluate("(roe_ann > 9) and (pe_ttm < 15)", df)
    assert v.tolist()[:2] == [1.0, 0.0]
    assert np.isnan(v.iloc[2]) is False or v.iloc[2] == 0.0  # roe 5 不满足 → 假，与缺失无关
    assert evaluate("10 < roe_ann <= 20", df).tolist() == [1, 0, 0, 0, 0, 0]
    # Python 优先级：not a | b == not (a | b)
    assert evaluate("not (roe_ann > 9) | (ep > 15)", df).tolist() == [0, 0, 1, 0, 1, 1]
    assert evaluate("(not roe_ann > 9) or ep > 15", df).tolist() == [0, 0, 1, 1, 1, 1]


def test_formula_cross_section_by_date(df):
    r = evaluate("rank(roe_ann)", df)
    assert r.tolist() == pytest.approx([1, 2 / 3, 1 / 3, 1, 2 / 3, 1 / 3])
    r = evaluate("ind_rank(roe_ann)", df)
    assert r.tolist() == pytest.approx([1, 0.5, 1, 1, 0.5, 1])


@pytest.mark.parametrize("bad", ["__import__('os')", "ep.real", "foo + 1", "lambda: 1", "rank(ep, 2)", "ep[0]",
                                 "'abc'", "open('x')"])
def test_formula_rejects_unsafe(df, bad):
    with pytest.raises(FormulaError):
        evaluate(bad, df)


def test_custom_factor_cycle_and_backtest(synth_db):
    with connect(read_only=False) as con:
        con.execute("DELETE FROM custom_factor")
        con.execute("INSERT INTO custom_factor (name, label, expr, better) VALUES "
                    "('neg_mom', '反向动量', '-mom_60', 'high'), ('neg2', 'x', 'neg_mom * 2', 'high')")
    invalidate()
    assert base_columns(["neg2"]) == {"mom_60"}
    with pytest.raises(FormulaError, match="循环"):
        validate("neg2 + 1", "neg_mom")
    r = run_backtest(BacktestParams(factors=[FactorSpec("neg2")], start=dt.date(2019, 6, 1), top_n=1,
                                    commission=0, slippage=0))
    assert [s["code"] for s in r["holdings"]["stocks"]] == ["sh.600003"]
    with connect(read_only=False) as con:
        con.execute("DELETE FROM custom_factor")
    invalidate()


def test_dividend_yield_and_payout(synth_db, con):
    ex = synth_db["ex"]
    y = con.execute("SELECT date, dividend_yield FROM factor_daily WHERE code = 'sh.600002' ORDER BY date").df()
    y["date"] = pd.to_datetime(y.date).dt.date
    assert y[y.date < ex].dividend_yield.max() == 0
    assert y[y.date == ex].dividend_yield.iloc[0] == pytest.approx(10.0)
    pr = con.execute("SELECT date, payout_ratio FROM factor_daily WHERE code = 'sh.600003' ORDER BY date").df()
    pr["date"] = pd.to_datetime(pr.date).dt.date
    assert pr[pr.date >= dt.date(2020, 4, 27)].payout_ratio.iloc[0] == pytest.approx(30.0)
    # 2018 年报（无分红）公告后分红率为 0；之前无数据
    assert pr[pr.date < dt.date(2019, 3, 1)].payout_ratio.isna().all()
    assert (pr[(pr.date >= dt.date(2019, 3, 1)) & (pr.date < dt.date(2020, 4, 25))].payout_ratio == 0).all()


def test_historical_universe(synth_db):
    upsert_df("index_member", pd.DataFrame({"index_code": "hs300", "date": [dt.date(2019, 5, 31)] * 2,
                                            "code": ["sh.600002", "sh.600003"]}), ["index_code", "date", "code"])
    U.clear_cache()
    assert U.universe_codes("hs300", dt.date(2019, 7, 31)) == {"sh.600002", "sh.600003"}
    r = run_backtest(BacktestParams(factors=[FactorSpec("mom_60")], start=dt.date(2019, 6, 1), top_n=1,
                                    universe="hs300", commission=0, slippage=0))
    assert [s["code"] for s in r["holdings"]["stocks"]] == ["sh.600002"]  # 600001 不在历史成分中
    with connect(read_only=False) as con:
        con.execute("DELETE FROM index_member")
    U.clear_cache()


def test_neutralize_removes_industry_mean():
    df = pd.DataFrame({"industry": ["A"] * 10 + ["B"] * 10, "float_mv": np.linspace(10, 100, 20)})
    z = pd.Series([1.0] * 10 + [-1.0] * 10) + np.random.default_rng(0).normal(0, 0.01, 20)
    r = U.neutralize(z, df, ["industry"])
    assert abs(r[:10].mean() - r[10:].mean()) < 1e-6


def test_ts_formula_and_concentration(synth_db, con):
    from backend.formula import evaluate_ts
    m = con.execute("SELECT * FROM market_sentiment ORDER BY date").df()
    # 3 只股票成交额相同 → 前 5%（ceil = 1 只）占 1/3
    assert m.amt_top5.dropna().iloc[-1] == pytest.approx(100 / 3)
    v = evaluate_ts("ma(amt_top5, 5) - lag(amt_top5, 1)", m)
    assert v.iloc[-1] == pytest.approx(0)
    v = evaluate_ts("where(score > 50, 1, 0) + mix * 0", m, {"mix": "ts_zscore(amount_yi, 20)"})
    assert set(v.dropna().unique()) <= {0.0, 1.0}
    with pytest.raises(FormulaError):
        evaluate_ts("ma(amt_top5, x)", m)
    with pytest.raises(FormulaError):
        evaluate_ts("rank(score)", m)  # 截面函数不可用于时间序列


def test_market_field_in_stock_formula(synth_db):
    from backend import screener
    df = screener.screen([], expr="mkt_amt_top5 > 30")
    assert len(df) == 3
    df = screener.screen([], expr="mkt_amt_top5 > 50")
    assert len(df) == 0
