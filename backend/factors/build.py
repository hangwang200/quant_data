"""因子构建：从 daily_bar / adj_factor / financial_report 生成日频因子宽表 factor_daily，
以及市场情绪表 market_sentiment。

防未来函数：财务数据按 effective_date（min(公告日, 法定截止日)）ASOF 对齐。
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from backend.db.conn import connect, log_etl

log = logging.getLogger("factors")

# 因子元数据：前端展示、选股器、回测共用
FACTORS = {
    "pe_ttm":         {"label": "市盈率 PE(TTM)", "group": "估值", "unit": "x", "better": "low"},
    "pb":             {"label": "市净率 PB", "group": "估值", "unit": "x", "better": "low"},
    "ep":             {"label": "盈利收益率 EP", "group": "估值", "unit": "%", "better": "high"},
    "bp":             {"label": "账面市值比 BP", "group": "估值", "unit": "%", "better": "high"},
    "dividend_yield": {"label": "股息率(TTM)", "group": "分红", "unit": "%", "better": "high"},
    "payout_ratio":   {"label": "年度现金分红率", "group": "分红", "unit": "%", "better": "high"},
    "roe_ann":        {"label": "ROE(年化)", "group": "质量", "unit": "%", "better": "high"},
    "roe_delta":      {"label": "ROE 同比变化", "group": "质量", "unit": "pct", "better": "high"},
    "gross_margin":   {"label": "毛利率", "group": "质量", "unit": "%", "better": "high"},
    "ocf_to_eps":     {"label": "经营现金流/EPS", "group": "质量", "unit": "x", "better": "high"},
    "revenue_yoy":    {"label": "营收同比", "group": "成长", "unit": "%", "better": "high"},
    "net_profit_yoy": {"label": "净利润同比", "group": "成长", "unit": "%", "better": "high"},
    "mom_5":          {"label": "5日反转", "group": "动量", "unit": "%", "better": "low"},
    "mom_20":         {"label": "20日动量", "group": "动量", "unit": "%", "better": "high"},
    "mom_60":         {"label": "60日动量", "group": "动量", "unit": "%", "better": "high"},
    "mom_120":        {"label": "120日动量", "group": "动量", "unit": "%", "better": "high"},
    "mom_12_1":       {"label": "12-1月动量", "group": "动量", "unit": "%", "better": "high"},
    "vol_20":         {"label": "20日波动率", "group": "风险", "unit": "%", "better": "low"},
    "vol_60":         {"label": "60日波动率", "group": "风险", "unit": "%", "better": "low"},
    "max_ret_20":     {"label": "20日最大日涨幅", "group": "风险", "unit": "%", "better": "low"},
    "beta_60":        {"label": "60日 Beta", "group": "风险", "unit": "x", "better": "low"},
    "turnover":       {"label": "换手率", "group": "流动性", "unit": "%", "better": "low"},
    "turnover_20":    {"label": "20日平均换手", "group": "流动性", "unit": "%", "better": "low"},
    "amount_20":      {"label": "20日均成交额", "group": "流动性", "unit": "亿", "better": "high"},
    "amihud_20":      {"label": "非流动性 Amihud", "group": "流动性", "unit": "x", "better": "high"},
    "float_mv":       {"label": "流通市值", "group": "规模", "unit": "亿", "better": "low"},
}

FACTOR_SQL = """
CREATE OR REPLACE TABLE factor_daily AS
WITH fin_ttm AS (        -- TTM EPS = 当期累计 + 上年年报 - 上年同期累计
    SELECT f.*,
           CASE WHEN month(f.report_date) = 12 THEN f.eps
                ELSE f.eps + a.eps - p.eps END AS eps_ttm,
           f.roe_ann - p.roe_ann AS roe_delta,
           CASE WHEN f.eps > 0 THEN f.ocf_ps / f.eps END AS ocf_to_eps
    FROM financial_report f
    LEFT JOIN financial_report a ON a.code = f.code AND a.report_date = make_date(year(f.report_date) - 1, 12, 31)
    LEFT JOIN financial_report p ON p.code = f.code AND p.report_date = f.report_date - INTERVAL 1 YEAR
),
fin AS (                 -- 每个可用日只保留"当时已知的最新报告期"，并记录当时的复权因子
    SELECT x.*, coalesce(af.back_factor, 1.0) AS fin_bf FROM (
        SELECT code, effective_date, report_date, eps_ttm, bps, roe_ann, gross_margin, revenue_yoy, net_profit_yoy,
               roe_delta, ocf_to_eps,
               max(report_date) OVER (PARTITION BY code ORDER BY effective_date, report_date
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS max_rd,
               row_number() OVER (PARTITION BY code, effective_date ORDER BY report_date DESC) AS rn
        FROM fin_ttm
    ) x
    ASOF LEFT JOIN adj_factor af ON x.code = af.code AND x.effective_date >= af.date
    WHERE x.report_date = x.max_rd AND x.rn = 1
),
adj AS (
    SELECT b.*, coalesce(a.back_factor, 1.0) AS bf
    FROM daily_bar b
    ASOF LEFT JOIN adj_factor a ON b.code = a.code AND b.date >= a.date
),
div_ev AS (             -- 已实施的现金分红，折算成后复权口径（除息前一日的复权因子）
    SELECT d.code, d.ex_date, sum(d.dps * coalesce(af.back_factor, 1.0)) AS dps_hfq
    FROM (SELECT code, ex_date, sum(dps) AS dps FROM dividend
          WHERE ex_date IS NOT NULL AND dps > 0 GROUP BY 1, 2) d
    ASOF LEFT JOIN adj_factor af ON d.code = af.code AND d.ex_date > af.date
    GROUP BY 1, 2
),
div_cum AS (
    SELECT code, ex_date, sum(dps_hfq) OVER (PARTITION BY code ORDER BY ex_date) AS cum_div FROM div_ev
),
pay AS (                -- 年度现金分红率 = 当年各期每股现金分红合计 / 年报 EPS；年报与分红预案都公告后可用
    SELECT f.code, greatest(f.effective_date, coalesce(d.plan, f.effective_date)) AS pay_date,
           CASE WHEN f.eps > 0 THEN coalesce(d.dps_y, 0) / f.eps * 100 END AS payout_ratio
    FROM financial_report f
    LEFT JOIN (SELECT code, year(report_date) AS y, sum(dps) AS dps_y, max(plan_date) AS plan
               FROM dividend WHERE dps > 0 AND coalesce(progress, '') NOT SIMILAR TO '.*(停止|未通过|取消).*'
               GROUP BY 1, 2) d ON d.code = f.code AND d.y = year(f.report_date)
    WHERE month(f.report_date) = 12
    QUALIFY row_number() OVER (PARTITION BY f.code, pay_date ORDER BY f.report_date DESC) = 1
),
mkt AS (
    SELECT date, close / lag(close) OVER (ORDER BY date) - 1 AS mret
    FROM index_daily WHERE code = 'sh.000300'
),
px AS (
    SELECT adj.*, m.mret, close * bf AS close_hfq, open * bf AS open_hfq,
           close * bf / lag(close * bf) OVER w - 1 AS ret
    FROM adj LEFT JOIN mkt m USING (date)
    WINDOW w AS (PARTITION BY code ORDER BY date)
),
tech AS (
    SELECT *,
        close_hfq / lag(close_hfq, 5)   OVER w - 1 AS mom_5,
        close_hfq / lag(close_hfq, 20)  OVER w - 1 AS mom_20,
        lag(close_hfq, 20) OVER w / lag(close_hfq, 240) OVER w - 1 AS mom_12_1,
        max(ret)         OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS max_ret_20,
        regr_slope(ret, mret) OVER (w ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS beta_60,
        avg(turnover)    OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS turnover_20,
        avg(abs(ret) / nullif(amount, 0)) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * 1e8 AS amihud_20,
        close_hfq / lag(close_hfq, 60)  OVER w - 1 AS mom_60,
        close_hfq / lag(close_hfq, 120) OVER w - 1 AS mom_120,
        stddev_samp(ret) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * sqrt(252) AS vol_20,
        stddev_samp(ret) OVER (w ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) * sqrt(252) AS vol_60,
        avg(close_hfq)   OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20_hfq,
        max(close_hfq)   OVER (w ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS hi60_hfq,
        min(close_hfq)   OVER (w ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS lo60_hfq,
        avg(amount)      OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) / 1e8 AS amount_20,
        count(*)         OVER (w ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS n_bars,
        date - INTERVAL 365 DAY AS date_1y
    FROM px
    WINDOW w AS (PARTITION BY code ORDER BY date)
)
SELECT t.code, t.date, s.name, s.industry,
       t.open, t.high, t.low, t.close, t.ret * 100 AS pct_chg, t.volume, t.amount, t.turnover,
       t.close * t.float_share / 1e8 AS float_mv,
       CASE WHEN f.eps_ttm > 0 THEN t.close_hfq / (f.eps_ttm * f.fin_bf) END AS pe_ttm,
       CASE WHEN f.bps > 0 THEN t.close_hfq / (f.bps * f.fin_bf) END AS pb,
       f.eps_ttm * f.fin_bf / t.close_hfq * 100 AS ep,
       f.bps * f.fin_bf / t.close_hfq * 100 AS bp,
       -- 历史 ST（baostock 逐日）；st_daily 覆盖范围之后的日期退回用当前名称判断
       (CASE WHEN t.date <= (SELECT max(date) FROM st_daily) THEN st.code IS NOT NULL
             ELSE s.name LIKE '%ST%' END)::INTEGER AS is_st,
       t.trade_status, t.close_hfq, t.open_hfq, t.ret,
       (t.high = t.low) AS one_price,              -- 一字板/全天一个价
       date_diff('day', s.ipo_date, t.date) AS listed_days,
       t.mom_5 * 100 AS mom_5, t.mom_20 * 100 AS mom_20, t.mom_60 * 100 AS mom_60, t.mom_120 * 100 AS mom_120,
       t.mom_12_1 * 100 AS mom_12_1,
       CASE WHEN t.n_bars >= 20 THEN t.vol_20 * 100 END AS vol_20,
       CASE WHEN t.n_bars >= 60 THEN t.vol_60 * 100 END AS vol_60,
       CASE WHEN t.n_bars >= 20 THEN t.max_ret_20 * 100 END AS max_ret_20,
       CASE WHEN t.n_bars >= 60 THEN t.beta_60 END AS beta_60,
       t.turnover_20, t.amount_20, t.amihud_20, t.ma20_hfq, t.hi60_hfq, t.lo60_hfq,
       f.report_date AS fin_report_date, f.roe_ann, f.roe_delta, f.gross_margin, f.ocf_to_eps,
       f.revenue_yoy, f.net_profit_yoy,
       (coalesce(c1.cum_div, 0) - coalesce(c0.cum_div, 0)) / t.close_hfq * 100 AS dividend_yield,
       pay.payout_ratio
FROM tech t
JOIN stock_basic s USING (code)
LEFT JOIN st_daily st ON st.code = t.code AND st.date = t.date
ASOF LEFT JOIN fin f ON t.code = f.code AND t.date >= f.effective_date
ASOF LEFT JOIN div_cum c1 ON t.code = c1.code AND t.date >= c1.ex_date
ASOF LEFT JOIN div_cum c0 ON t.code = c0.code AND t.date_1y >= c0.ex_date
ASOF LEFT JOIN pay ON t.code = pay.code AND t.date >= pay.pay_date
ORDER BY t.date, t.code
"""

BREADTH_SQL = """
SELECT date,
       count(*) FILTER (WHERE trade_status = 1) AS n,
       count(*) FILTER (WHERE trade_status = 1 AND pct_chg > 0) AS up,
       count(*) FILTER (WHERE trade_status = 1 AND pct_chg < 0) AS down,
       count(*) FILTER (WHERE trade_status = 1 AND pct_chg = 0) AS flat,
       sum(amount) AS amount,
       avg(CASE WHEN close_hfq > ma20_hfq THEN 1.0 ELSE 0.0 END) FILTER (WHERE trade_status = 1) AS above_ma20,
       count(*) FILTER (WHERE close_hfq >= hi60_hfq AND listed_days > 90) AS new_high,
       count(*) FILTER (WHERE close_hfq <= lo60_hfq AND listed_days > 90) AS new_low,
       count(*) FILTER (WHERE pct_chg >= 9.5) AS big_up,
       count(*) FILTER (WHERE pct_chg <= -9.5) AS big_down,
       median(turnover) AS turnover_med
FROM factor_daily GROUP BY date ORDER BY date
"""

# 成交额集中度：每只股票近 5 个交易日（约一周）成交额合计，取全市场前 5% 的股票占总成交额的比例。
# 只用当日及以前的数据，可直接作为择时信号。同时给出单日口径。
CONCENTRATION_SQL = """
WITH a AS (
    SELECT code, date, amount,
           sum(amount) OVER (PARTITION BY code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS amt5
    FROM factor_daily WHERE amount > 0
),
r AS (
    SELECT date, amount, amt5,
           row_number() OVER (PARTITION BY date ORDER BY amt5 DESC) AS rk5,
           row_number() OVER (PARTITION BY date ORDER BY amount DESC) AS rk1,
           count(*) OVER (PARTITION BY date) AS n
    FROM a
)
SELECT date,
       sum(amt5) FILTER (WHERE rk5 <= ceil(n * 0.05)) / sum(amt5) * 100 AS amt_top5,
       sum(amount) FILTER (WHERE rk1 <= ceil(n * 0.05)) / sum(amount) * 100 AS amt_top5_d
FROM r GROUP BY date ORDER BY date
"""

# 市场指标：总览页展示，可用于融合指标公式（时间序列）；带 mkt_ 前缀注入因子截面，用于择时
MARKET_INDICATORS = {
    "score":        {"label": "市场情绪指数", "unit": "0-100", "group": "情绪"},
    "breadth":      {"label": "上涨家数占比(5日均)", "unit": "%", "group": "情绪"},
    "above_ma20":   {"label": "站上20日均线比例", "unit": "%", "group": "情绪"},
    "high_low":     {"label": "60日新高占新高+新低", "unit": "%", "group": "情绪"},
    "volume":       {"label": "成交活跃度分位", "unit": "0-100", "group": "情绪"},
    "momentum":     {"label": "沪深300动量分位", "unit": "0-100", "group": "情绪"},
    "amt_top5":     {"label": "近一周成交额前5%个股占比", "unit": "%", "group": "成交结构"},
    "amt_top5_d":   {"label": "当日成交额前5%个股占比", "unit": "%", "group": "成交结构"},
    "amount_yi":    {"label": "全市场成交额", "unit": "亿", "group": "成交结构"},
    "turnover_med": {"label": "换手率中位数", "unit": "%", "group": "成交结构"},
    "up_ratio":     {"label": "当日上涨家数占比", "unit": "%", "group": "涨跌"},
    "big_up":       {"label": "涨幅≥9.5%家数", "unit": "只", "group": "涨跌"},
    "big_down":     {"label": "跌幅≤-9.5%家数", "unit": "只", "group": "涨跌"},
    "hs300":        {"label": "沪深300", "unit": "点", "group": "指数"},
    "zz500":        {"label": "中证500", "unit": "点", "group": "指数"},
}
# 注入个股截面供公式使用的市场字段：公式名 -> market_sentiment 列
MARKET_FIELDS = {"mkt_amt_top5": "amt_top5", "mkt_sentiment": "score", "mkt_above_ma20": "above_ma20",
                 "mkt_breadth": "breadth", "mkt_amount": "amount_yi"}


def _rolling_pct_rank(s: pd.Series, window: int = 250) -> pd.Series:
    return s.rolling(window, min_periods=60).apply(lambda x: (x[:-1] < x[-1]).mean() * 100, raw=True)


def compute_sentiment(breadth: pd.DataFrame, index: pd.DataFrame) -> pd.DataFrame:
    """合成 0-100 的市场情绪指数（类 Fear & Greed）。5 个分项等权：
    1. 上涨家数占比(5日均)  2. 站上20日均线比例  3. 60日新高/新低比  4. 成交额相对强度(分位)
    5. 沪深300 相对 125 日均线偏离(分位)
    """
    b = breadth.copy().set_index("date")
    comp = pd.DataFrame(index=b.index)
    comp["breadth"] = (b.up / b.n.replace(0, np.nan)).rolling(5, min_periods=1).mean() * 100
    comp["above_ma20"] = b.above_ma20 * 100
    hl = b.new_high + b.new_low
    comp["high_low"] = (b.new_high / hl.replace(0, np.nan)).fillna(0.5).rolling(5, min_periods=1).mean() * 100
    vol_ratio = b.amount.rolling(5).mean() / b.amount.rolling(60).mean()
    comp["volume"] = _rolling_pct_rank(vol_ratio)
    idx = index.set_index("date").close
    mom = idx / idx.rolling(125).mean() - 1
    comp["momentum"] = _rolling_pct_rank(mom).reindex(comp.index)
    comp = comp.clip(0, 100)
    comp["score"] = comp.mean(axis=1, skipna=True)
    extra = ["n", "up", "down", "flat", "amount"] + [c for c in ("big_up", "big_down", "turnover_med", "amt_top5",
                                                                  "amt_top5_d") if c in b.columns]
    out = comp.join(b[extra])
    out["amount_yi"] = out["amount"] / 1e8
    out["up_ratio"] = out["up"] / out["n"].replace(0, np.nan) * 100
    return out.reset_index()


def build_all():
    with connect(read_only=False) as con:
        log.info("building factor_daily ...")
        con.execute(FACTOR_SQL)
        n = con.execute("SELECT count(*) FROM factor_daily").fetchone()[0]
        breadth = con.execute(BREADTH_SQL).df()
        conc = con.execute(CONCENTRATION_SQL).df()
        breadth = breadth.merge(conc, on="date", how="left")
        index = con.execute("SELECT date, close FROM index_daily WHERE code='sh.000300' ORDER BY date").df()
        sent = compute_sentiment(breadth, index)
        idx = con.execute("SELECT date, code, close FROM index_daily WHERE code IN ('sh.000300', 'sh.000905')").df()
        idx = idx.pivot(index="date", columns="code", values="close").rename(
            columns={"sh.000300": "hs300", "sh.000905": "zz500"}).reset_index()
        sent = sent.merge(idx, on="date", how="left")
        con.register("_sent", sent)
        con.execute("CREATE OR REPLACE TABLE market_sentiment AS SELECT * FROM _sent")
        con.unregister("_sent")
        # 因子截面 + 市场字段（同一日所有股票相同），供公式择时：如 mkt_amt_top5 < 40
        mf = ", ".join(f"m.{col} AS {name}" for name, col in MARKET_FIELDS.items())
        con.execute(f"CREATE OR REPLACE VIEW factor_view AS SELECT f.*, {mf} "
                    "FROM factor_daily f LEFT JOIN market_sentiment m USING (date)")
    log_etl("factors", "ok", f"{n} rows")
    log.info("factor_daily: %d rows", n)
