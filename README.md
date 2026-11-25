# Factor Lab · A 股因子实验室

本地运行的 A 股量化因子系统：数据 ETL → 财报/分红提取 → 可视化/选股池 → 因子分析（IC/IR、分层）→ 因子回测。
覆盖全 A 股（含 2014 年以来退市股票），按历史成分股与历史 ST 状态回测，消除幸存者偏差。

## 快速开始

```bash
# 1. 后端依赖
pip install -r requirements.txt

# 2. 拉取数据（首次全 A 股约 1–1.5 小时；之后每日增量约 5–6 分钟：行情用全市场快照约 1 分钟 + 因子重建约 3 分钟）
python -m backend.cli etl --with-st     # 首次：含历史 ST、退市股股本、历史成分股
python -m backend.cli etl               # 日常：指数 + 行情增量 + 最近几期财报/分红 + 因子

# 3. 启动后端
python -m uvicorn backend.api.main:app --port 8000

# 4. 启动前端（开发模式）
cd frontend && npm install && npm run dev      # 打开 http://localhost:5173
#    或构建后由后端直接托管：npm run build，然后访问 http://localhost:8000
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `python -m backend.cli etl` | 全流程：股票列表(首次) → 指数 → 行情(增量) → 财报/分红(补齐) → 因子 |
| `python -m backend.cli etl --with-st` | 同上，并更新历史 ST、退市股股本、历史成分股（较慢，建议每月一次） |
| `python -m backend.cli etl --refresh-stocks` | 同上，并强制刷新股票列表 / 当前成分股 |
| `python -m backend.cli etl --scope core` | 只更新当前沪深300+中证500（约 800 只） |
| `python -m backend.cli prices` | 仅增量更新行情（全 A 股，已退市且已有数据的跳过） |
| `python -m backend.cli st` / `shares` / `members` / `dividends` | 历史 ST / 退市股流通股本 / 历史成分股 / 分红送配 |
| `python -m backend.cli financials --date 2024-12-31` | 下载指定报告期财报（可多次 `--date`） |
| `python -m backend.cli factors` | 仅重建因子表和情绪指数 |
| `python -m pytest tests` | 运行测试（使用临时数据库，不影响本地数据） |

## 数据源

| 数据 | 来源 | 说明 |
|---|---|---|
| 股票列表、证监会行业、沪深300/中证500 成分股 | Baostock | 免费，无需 token |
| 日线（不复权）、后复权因子、指数 | 新浪（经 AkShare） | 约 3 秒/只；停牌日无数据行 |
| 财报（营收/利润/费用/ROE/EPS/BPS…） | 东方财富（经 AkShare） | 按报告期一次拉全市场 |
| 分红送配（每股派息、预案/除息日） | 东方财富（经 AkShare） | 按报告期一次拉全市场 |
| 历史成分股（每月末快照）、历史 ST、退市股换手率 | Baostock | 较慢，按月更新即可 |

所有数据写入 `data/quant.duckdb`（DuckDB 单文件）。

## 关键设计

- **防未来函数**：财报按 `effective_date = min(公告日, 法定披露截止日)` 对齐。东方财富给的是"最新公告日"，
  报告被更正时会晚于原始披露，因此用截止日兜底。
- **PE/PB 由财报自行计算**：`PE = 后复权价 / (TTM EPS × 财报可用日的复权因子)`，送转股前后不会跳变。
- **回测**：信号日收盘打分 → 次日开盘调仓；停牌不可交易、一字跌停不可卖、一字涨停不可买；
  佣金万 2.5 + 滑点 + 印花税（2023-08-28 起 0.05%）。股票池规则在每个信号日按当时数据动态筛选。
- **股票池**：全 A 股 / 沪深300 / 中证500 / 300+500 均按**信号日当时**的成分股（每月末快照）；ST 按历史逐日状态；
  退市股在最后交易日后按最后价格卖出。
- **分红因子**：股息率(TTM) = 过去 365 天已除息的每股现金分红（后复权口径）/ 后复权价；
  年度现金分红率 = 当年各期每股现金分红合计 / 年报 EPS，年报与分红预案都公告后才可用。
- **公式因子**：在「公式因子」页用表达式组合因子，如 `rank(ep) + rank(roe_ann)`、
  `(dividend_yield > 3) and (roe_ann > 10)`；支持四则运算、比较、and/or/not、where、rank/zscore/行业内排名等。
  表达式经 AST 白名单校验，不执行任意代码。
- **因子分析**：Rank IC / ICIR / t 值、N 分组分层回测（多空、单调性、换手）、IC 衰减、因子相关性矩阵，可行业/市值中性化。
- **市场指标与融合指标**：总览页可查看情绪各分项、成交额、换手中位数、大涨/大跌家数，以及
  **近一周成交额前 5% 个股占总成交额比例**（每只股票近 5 个交易日成交额合计，全市场排名前 5% 的占比，衡量资金集中/拥挤）。
  可用时间序列公式融合，如 `ts_rank(amt_top5, 250) * 0.5 + ts_rank(turnover_med, 250) * 0.5`
  （函数：ma / ema / ts_rank / ts_zscore / ts_max / ts_min / ts_std / diff / lag / pct_change / where）。
  市场字段也以 `mkt_` 前缀注入个股截面，可在选股/回测公式中择时，如 `where(mkt_amt_top5 < 40, rank(ep), 1 / 0)`。
- **时间窗口**：总览、回测、策略对比、因子分析的图表都支持 3 月～全部及自定义区间；净值类曲线按窗口起点重新归一。
- **市场情绪指数**：上涨家数占比、站上 20 日均线比例、60 日新高/新低比、成交活跃度分位、沪深300 动量分位，等权合成 0–100。

## 已知限制

- 2014 年以前退市的股票不在范围内；北交所股票未纳入。
- 历史 ST 来自 baostock，最近一次 `st` 任务之后的日期退回按当前名称判断。
- 分红数据按报告期归属年度；个别"一年多次分红 + 送转"的情况每股口径可能有偏差。
- 东方财富利润表不含研发费用；ROE 为报告期累计值按季度年化。

## 目录

```
backend/
  etl/          数据源适配（baostock_src / sina_src / akshare_src）与编排 pipeline
  factors/      因子宽表 factor_daily + 市场情绪 market_sentiment
  backtest/     回测引擎 engine + 股票池/中性化/价格面板 universe + 绩效指标 metrics
  analysis.py   因子分析（IC/IR、分层、相关性、看板）
  formula.py    公式因子（安全表达式解析与截面求值）
  screener.py   选股规则
  api/main.py   FastAPI
  cli.py        命令行
frontend/       React + Vite + Tailwind + ECharts
tests/          合成数据测试
```
