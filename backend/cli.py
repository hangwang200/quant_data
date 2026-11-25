"""命令行入口。

python -m backend.cli etl                 # 全流程：股票列表 → 指数 → 行情 → 财报 → 因子
python -m backend.cli etl --limit 20      # 只拉 20 只股票做快速验证
python -m backend.cli prices              # 仅增量更新行情
python -m backend.cli financials --date 2024-12-31   # 下载指定报告期财报
python -m backend.cli factors             # 仅重建因子表
python -m backend.cli st                  # 历史 ST 状态（baostock，较慢，建议每月一次）
python -m backend.cli dividends           # 分红送配（全部历史报告期）
python -m backend.cli members             # 沪深300/中证500 历史成分股（每月末快照）
"""
import argparse
import datetime as dt
import logging
import sys


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="quant")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("etl")
    e.add_argument("--limit", type=int)
    e.add_argument("--skip-financials", action="store_true")
    e.add_argument("--refresh-stocks", action="store_true", help="强制刷新股票列表/成分股")
    e.add_argument("--scope", choices=["all", "core"], default="all", help="all 全 A 股(含退市) / core 当前 800 只")
    e.add_argument("--with-st", action="store_true", help="同时更新历史 ST 与成分股（较慢）")
    sub.add_parser("stocks")
    sub.add_parser("index")
    pr = sub.add_parser("prices")
    pr.add_argument("--limit", type=int)
    pr.add_argument("--scope", choices=["all", "core"], default="all")
    st = sub.add_parser("st")
    st.add_argument("--full", action="store_true")
    sub.add_parser("members")
    sub.add_parser("shares")
    sub.add_parser("dividends")
    f = sub.add_parser("financials")
    f.add_argument("--date", action="append", help="报告期 YYYY-MM-DD，可多次指定；不指定则补齐全部历史")
    sub.add_parser("factors")
    a = p.parse_args(argv)

    from backend.etl import pipeline
    from backend.factors.build import build_all

    if a.cmd == "etl":
        pipeline.run_all(limit=a.limit, skip_financials=a.skip_financials, refresh_stocks=a.refresh_stocks,
                         scope=a.scope, with_st=a.with_st)
    elif a.cmd == "stocks":
        pipeline.sync_stock_list()
    elif a.cmd == "index":
        pipeline.sync_index()
    elif a.cmd == "prices":
        pipeline.sync_prices(limit=a.limit, scope=a.scope)
    elif a.cmd == "st":
        pipeline.sync_st(full=a.full)
    elif a.cmd == "dividends":
        pipeline.sync_dividends()
    elif a.cmd == "shares":
        pipeline.sync_st(shares_only=True)
    elif a.cmd == "members":
        pipeline.sync_index_members()
    elif a.cmd == "financials":
        periods = [dt.date.fromisoformat(d) for d in a.date] if a.date else None
        pipeline.sync_financials(periods)
    elif a.cmd == "factors":
        build_all()


if __name__ == "__main__":
    main()
