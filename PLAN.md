# AI 量化因子系统 —— 开发计划 & Outline

> 状态：待确认。确认后先做 MVP，再分阶段完善。

## 0. 目标与范围

| 模块 | 要做什么 | 验收标准 |
|---|---|---|
| ① 数据 ETL | 拉取 A 股基础信息、日线行情、估值指标、行业分类，写入本地 DuckDB | 一条命令完成全量/增量更新，重复执行不产生重复数据 |
| ② 财报 | 按报告期（如 `2024-12-31`）下载全市场财报，提取营收、利润、支出 | 可按日期下载，字段入库，带公告日期（用于防止未来函数） |
| ③ 可视化 & 选股池 | 个股看板、多公司对比、按 ROE / PE / 波动率 / 行业筛选并保存股票池 | 筛选条件可组合，股票池可保存/复用 |
| ④ 因子回测 | 用因子在股票池里选股，回测过去 10 年 | 输出净值曲线、年化、最大回撤、夏普、换手，并与沪深300对比 |
| ⑤ AI（加分项） | 用大模型生成个股/财报摘要、策略问答 | 在看板中一键生成报告 |

## 1. 技术选型

| 层 | 选择 | 理由 |
|---|---|---|
| 数据源 | **Baostock**（行情 + PE/PB + 季度财务 + 行业，免费、无需 token、有公告日期）<br>**AkShare**（按报告期拉全市场业绩报表/利润表，含销售/管理/研发/财务费用） | 都是参考项目 daily_stock_analysis 用的免费源；Tushare 作为可选源（需 token） |
| 存储 | **DuckDB** 单文件 `data/quant.duckdb` | 列式存储，适合因子计算和十年日线的批量查询，比 SQLite 快很多 |
| 计算 | pandas + numpy（因子、回测自己写，向量化） | 逻辑透明、可控；不依赖重型回测框架 |
| 后端 | **FastAPI** | 给前端提供 REST API |
| 前端 | **React + Vite + TypeScript + Tailwind + ECharts** | 参考图那种卡片式看板 / 仪表盘 / 估值带图，ECharts 都能做 |
| AI | Claude API（可配置模型和 key，不配置时该功能隐藏） | 财报摘要、策略问答 |

## 2. 目录结构

```
quant_data/
├── backend/
│   ├── etl/            # 数据源适配器 + 入库（baostock_src.py, akshare_src.py, pipeline.py）
│   ├── db/             # DuckDB 连接、建表 schema.sql
│   ├── factors/        # 因子定义与计算（估值/质量/动量/波动）
│   ├── screener/       # 选股池筛选与保存
│   ├── backtest/       # 回测引擎 + 绩效指标
│   ├── ai/             # LLM 报告生成
│   ├── api/            # FastAPI 路由
│   └── cli.py          # 命令行：etl / report / backtest
├── frontend/           # React 应用
├── data/quant.duckdb
└── tests/
```

## 3. 数据模型（DuckDB）

| 表 | 主要字段 |
|---|---|
| `stock_basic` | code, name, industry, list_date, delist_date, status |
| `daily_bar` | code, date, open, high, low, close, volume, amount, turnover, pct_chg, adj_factor, pe_ttm, pb, ps_ttm, is_st, trade_status |
| `financial_report` | code, report_date（报告期）, **pub_date（公告日）**, revenue, net_profit, op_profit, total_cost, sell_exp, admin_exp, rd_exp, fin_exp, roe, eps, gross_margin |
| `index_daily` | index_code, date, close（沪深300/中证500，作基准） |
| `factor_value` | code, date, factor_name, value（月末截面） |
| `stock_pool` | pool_id, name, rules(JSON), created_at |
| `backtest_run` | run_id, params(JSON), metrics(JSON), nav(JSON) |
| `etl_log` | task, last_date, status（用于增量更新） |

## 4. 关键设计（保证回测可信）

1. **防未来函数**：财务数据按 `pub_date` 对齐，而不是按报告期对齐；调仓日只用此前已公告的数据。
2. **幸存者偏差**：股票列表包含已退市股票（MVP 阶段先说明偏差，后续补齐）。
3. **交易约束**：剔除 ST、停牌、上市不满 1 年；一字涨停不买入、一字跌停不卖出。
4. **成本**：佣金万 2.5 + 卖出印花税（按历史税率）+ 滑点，参数可调。
5. **复权**：收益用后复权价计算，展示用前复权价。

## 5. 因子库（第一批）

| 类别 | 因子 |
|---|---|
| 估值 | PE_TTM、PB、PS、EP、股息率 |
| 质量 | ROE、毛利率、净利率、营收增速、净利润增速 |
| 动量/反转 | 20/60/120 日收益率 |
| 风险 | 20/60 日波动率、Beta |
| 流动性 | 换手率、成交额、市值 |

预处理：去极值（MAD）→ 标准化（Z-score）→ 可选行业/市值中性化；多因子按权重打分。

## 6. 回测引擎

- 月度/周度调仓，按因子打分选 Top N（或分层 5 组），等权或按市值加权
- 输出：净值曲线 vs 基准、年化收益、年化波动、最大回撤、夏普、卡玛、胜率、换手率、年度收益表、分层收益（IC/IR 检验因子有效性）
- 回测区间默认 2015-01 至今（约 10 年）

## 7. UI 页面（统一设计语言：浅色卡片 + 深色模式切换，红涨绿跌）

| 页面 | 内容 | 对应参考 |
|---|---|---|
| 市场总览 | 涨/跌/平家数、成交额卡片；市场情绪仪表盘（0–100）；全市场表格（搜索、行业筛选、排序） | image3、image4 |
| 个股看板 | K 线 + 成交量；PE/PB/股息率历史分位带（均值 / ±1σ 线）；财报营收、利润、费用柱状图；AI 摘要 | image1、image2 |
| 公司对比 | 选 2–5 家：归一化走势、财务指标雷达图、关键指标对比表 | — |
| 选股器 | 条件构建器（ROE > x、PE 区间、波动率、行业…）→ 结果表 → 保存为股票池 | — |
| 回测 | 选股票池 + 因子 + 权重 + 调仓频率 → 净值曲线、回撤图、指标卡、年度收益热力图 | — |
| 数据管理 | ETL 状态、最近更新时间、手动触发更新 / 按报告期下载财报 | — |

## 8. 分阶段计划

### Phase 1 — MVP（快速验证全链路）
- 股票范围：**沪深300 + 中证500 当前成分股（约 800 只）**，2015 年至今日线
- ETL：Baostock 日线 + 估值 + 行业，增量更新；AkShare 按报告期下载财报（营收/利润/费用）
- 因子：PE、PB、ROE、营收增速、60 日动量、60 日波动率
- 回测：月度调仓、Top N 等权、含交易成本、对比沪深300
- UI：市场总览、个股看板、选股器、回测 4 个页面
- 交付：`python -m backend.cli etl` 一键拉数据；`npm run dev` + `uvicorn` 启动

### Phase 2 — 完善数据与回测 ✅
- 全 A 股（含退市股，消除幸存者偏差）、历史成分股、历史 ST
- 完整因子库（26 个，含股息率/分红率）+ 公式因子（算术/逻辑组合）
- IC/IR 分析、分层回测、IC 衰减、相关性矩阵、行业/市值中性化
- 数据管理页、回测结果保存/删除与多策略对比

### Phase 3 — AI 与体验
- AI 个股/财报摘要、策略问答
- 市场情绪指数（涨跌比、成交额、新高新低等合成）
- 定时任务（每日收盘后增量更新）、深色模式、性能优化

## 9. 待确认事项（括号内为默认方案）

1. 市场范围：**A 股**（是否需要港股/美股？）
2. MVP 股票范围：**沪深300 + 中证500 约 800 只**（全 A 股首次拉取约需 1–2 小时）
3. 前端：**React + ECharts**（更美观、可扩展）；如果只想最快验证，可改用 Streamlit
4. AI 功能：**放在 Phase 3**；是否有 Claude / 其他 LLM 的 API key
