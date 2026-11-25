"""新浪数据源（经 AkShare）：日线(不复权)、后复权因子、指数日线。

速度约 3 秒/只，远快于 baostock；但没有估值字段，PE/PB 在因子层用财报 PIT 计算。
停牌日新浪不返回数据行 —— 回测中表现为当日无价格，不可交易。
"""
from __future__ import annotations

import datetime as dt
import time

import pandas as pd

BAR_COLS = ["code", "date", "open", "high", "low", "close", "volume", "amount", "turnover",
            "pct_chg", "float_share", "trade_status"]


def _sym(code: str) -> str:
    return code.replace(".", "")  # sh.600519 -> sh600519


def _retry(fn, tries=3, wait=3.0):
    for i in range(tries):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(wait * (i + 1))


def fetch_bars(code: str, start: str) -> pd.DataFrame:
    import akshare as ak

    s = start.replace("-", "")
    e = dt.date.today().strftime("%Y%m%d")
    df = _retry(lambda: ak.stock_zh_a_hist_sina(symbol=_sym(code), start_date=s, end_date=e, adjust=""))
    if df is None or df.empty:
        return pd.DataFrame(columns=BAR_COLS)
    df = df.rename(columns={"outstanding_share": "float_share"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["code"] = code
    df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce") * 100  # 小数 -> %
    df["trade_status"] = 1
    df["pct_chg"] = None  # 需要复权因子，入库后在因子层计算
    return df[BAR_COLS]


def fetch_adj_factor(code: str) -> pd.DataFrame:
    import akshare as ak

    df = _retry(lambda: ak.stock_zh_a_hist_sina(symbol=_sym(code), adjust="hfq-factor"))
    if df is None or df.empty:
        return pd.DataFrame(columns=["code", "date", "back_factor"])
    df = df.rename(columns={"hfq_factor": "back_factor"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["back_factor"] = pd.to_numeric(df["back_factor"], errors="coerce")
    df["code"] = code
    return df[["code", "date", "back_factor"]].drop_duplicates(["code", "date"], keep="last")


def fetch_index(code: str, start: str) -> pd.DataFrame:
    import akshare as ak

    df = _retry(lambda: ak.index_zh_daily_sina(symbol=_sym(code)))
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["pct_chg"] = df["close"].pct_change() * 100
    df = df[df["date"] >= dt.date.fromisoformat(start)].copy()
    df["code"] = code
    df["amount"] = None
    return df[["code", "date", "open", "high", "low", "close", "amount", "pct_chg"]]


def fetch_one(args):
    code, start, need_adj = args
    try:
        bars = fetch_bars(code, start)
        try:
            adj = fetch_adj_factor(code) if need_adj else None
        except ValueError:  # 部分股票(如 CDR)新浪无复权因子，按因子 1 处理
            adj = None
        return code, bars, adj, None
    except Exception as e:  # noqa: BLE001
        return code, None, None, repr(e)[:300]


def fetch_spot() -> pd.DataFrame:
    """全市场实时快照（新浪，一次请求约 1 分钟）。收盘后即为当日完整日线。"""
    import akshare as ak

    df = _retry(lambda: ak.stock_zh_a_spot_sina())
    df = df.rename(columns={"今开": "open", "最高": "high", "最低": "low", "最新价": "close", "成交量": "volume",
                            "成交额": "amount", "昨收": "pre_close", "时间戳": "ts"})
    df["code"] = df["代码"].str[:2] + "." + df["代码"].str[2:]
    for c in ["open", "high", "low", "close", "volume", "amount", "pre_close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["code", "open", "high", "low", "close", "volume", "amount", "pre_close", "ts"]]
