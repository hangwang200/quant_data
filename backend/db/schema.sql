CREATE TABLE IF NOT EXISTS stock_basic (
    code        VARCHAR PRIMARY KEY,   -- sh.600519
    name        VARCHAR,
    industry    VARCHAR,
    ipo_date    DATE,
    out_date    DATE,
    status      INTEGER,               -- 1 上市 0 退市
    in_universe BOOLEAN DEFAULT FALSE,
    universe_src VARCHAR               -- hs300 / zz500
);

CREATE TABLE IF NOT EXISTS daily_bar (
    code        VARCHAR,
    date        DATE,
    open        DOUBLE,  high DOUBLE,  low DOUBLE,  close DOUBLE,   -- 不复权
    volume      DOUBLE,
    amount      DOUBLE,
    turnover    DOUBLE,  -- %
    pct_chg     DOUBLE,  -- % (新浪源为空，因子层用复权价计算)
    float_share DOUBLE,  -- 流通股本
    trade_status INTEGER, -- 1 正常（停牌日无数据行）
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS adj_factor (
    code        VARCHAR,
    date        DATE,       -- 除权除息日
    back_factor DOUBLE,     -- 后复权因子: 后复权价 = 不复权价 * back_factor
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS index_daily (
    code   VARCHAR,
    date   DATE,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    amount DOUBLE,
    pct_chg DOUBLE,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS financial_report (
    code          VARCHAR,
    report_date   DATE,       -- 报告期
    name          VARCHAR,
    announce_date DATE,       -- 数据源给出的(最新)公告日
    effective_date DATE,      -- 回测可用日 = min(公告日, 法定披露截止日)
    revenue       DOUBLE,     -- 营业总收入
    revenue_yoy   DOUBLE,     -- %
    net_profit    DOUBLE,
    net_profit_yoy DOUBLE,    -- %
    op_profit     DOUBLE,     -- 营业利润
    total_profit  DOUBLE,     -- 利润总额
    total_expense DOUBLE,     -- 营业总支出
    op_cost       DOUBLE,     -- 营业支出
    sell_exp      DOUBLE,
    admin_exp     DOUBLE,
    fin_exp       DOUBLE,
    eps           DOUBLE,
    bps           DOUBLE,
    roe           DOUBLE,     -- 报告期累计 ROE %
    roe_ann       DOUBLE,     -- 年化 ROE %
    gross_margin  DOUBLE,     -- %
    ocf_ps        DOUBLE,     -- 每股经营现金流
    industry_em   VARCHAR,
    PRIMARY KEY (code, report_date)
);

CREATE TABLE IF NOT EXISTS stock_pool (
    pool_id    VARCHAR PRIMARY KEY,
    name       VARCHAR,
    rules      JSON,
    created_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS backtest_run (
    run_id     VARCHAR PRIMARY KEY,
    name       VARCHAR,
    params     JSON,
    metrics    JSON,
    result     JSON,
    created_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS etl_log (
    task       VARCHAR PRIMARY KEY,
    status     VARCHAR,
    message    VARCHAR,
    updated_at TIMESTAMP DEFAULT current_timestamp
);

-- Phase 2：历史成分股快照（每月末），回测按信号日取最近一次快照
CREATE TABLE IF NOT EXISTS index_member (
    index_code VARCHAR,   -- hs300 / zz500
    date       DATE,      -- 快照日（月末）
    code       VARCHAR,
    PRIMARY KEY (index_code, date, code)
);

-- Phase 2：历史 ST 状态（仅存 ST 日），来自 baostock isST
CREATE TABLE IF NOT EXISTS st_daily (
    code VARCHAR,
    date DATE,
    PRIMARY KEY (code, date)
);

-- Phase 2：分红送配（东方财富，按报告期），dps = 每股现金分红(元，税前)
CREATE TABLE IF NOT EXISTS dividend (
    code        VARCHAR,
    report_date DATE,
    name        VARCHAR,
    dps         DOUBLE,
    bonus_per10 DOUBLE,     -- 每 10 股送转
    plan_date   DATE,       -- 预案公告日
    record_date DATE,
    ex_date     DATE,       -- 除权除息日（已实施）
    progress    VARCHAR,
    total_share DOUBLE,
    PRIMARY KEY (code, report_date)
);

-- Phase 2：公式因子（因子之间的算术/逻辑组合）
CREATE TABLE IF NOT EXISTS custom_factor (
    name       VARCHAR PRIMARY KEY,   -- 标识符，如 my_value
    label      VARCHAR,
    expr       VARCHAR,
    better     VARCHAR,               -- high / low
    created_at TIMESTAMP DEFAULT current_timestamp
);

-- 融合市场指标（市场指标的时间序列公式组合）
CREATE TABLE IF NOT EXISTS market_formula (
    name       VARCHAR PRIMARY KEY,
    label      VARCHAR,
    expr       VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp
);

-- 个股资产负债表（按需拉取缓存；data 为东方财富原始科目 JSON）
CREATE TABLE IF NOT EXISTS balance_sheet (
    code        VARCHAR,
    report_date DATE,
    data        JSON,
    fetched_at  TIMESTAMP,
    PRIMARY KEY (code, report_date)
);
