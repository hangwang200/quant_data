"""Baostock 数据源：股票列表、行业、成分股、日线(含估值)、复权因子、指数。

注意：baostock 的 ResultSet.get_data() 在 pandas>=2 下多页结果会报错，统一用 _to_df 逐行读取。
"""
from __future__ import annotations

import datetime as dt

import baostock as bs
import pandas as pd

BAR_FIELDS = "date,code,open,high,low,close,volume,amount,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,isST"
INDEX_FIELDS = "date,code,open,high,low,close,amount,pctChg"


def login():
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")


def logout():
    bs.logout()


def _to_df(rs) -> pd.DataFrame:
    if rs.error_code != "0":
        raise RuntimeError(f"baostock error {rs.error_code}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


def _num(df: pd.DataFrame, cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")
    return df


def fetch_stock_list() -> pd.DataFrame:
    """全部 A 股（type=1）基础信息 + 证监会行业。"""
    basic = _to_df(bs.query_stock_basic())
    basic = basic[basic["type"] == "1"].copy()
    ind = _to_df(bs.query_stock_industry())[["code", "industry"]]
    # "J66货币金融服务" -> "货币金融服务"
    ind["industry"] = ind["industry"].str.replace(r"^[A-Z]\d*", "", regex=True).replace("", None)
    df = basic.merge(ind, on="code", how="left")
    df = df.rename(columns={"code_name": "name", "ipoDate": "ipo_date", "outDate": "out_date"})
    df["ipo_date"] = pd.to_datetime(df["ipo_date"].replace("", None), errors="coerce").dt.date
    df["out_date"] = pd.to_datetime(df["out_date"].replace("", None), errors="coerce").dt.date
    df["status"] = df["status"].astype(int)
    return df[["code", "name", "industry", "ipo_date", "out_date", "status"]]


def fetch_universe() -> pd.DataFrame:
    hs = _to_df(bs.query_hs300_stocks())[["code"]].assign(universe_src="hs300")
    zz = _to_df(bs.query_zz500_stocks())[["code"]].assign(universe_src="zz500")
    return pd.concat([hs, zz]).drop_duplicates("code")


def fetch_bars(code: str, start: str, end: str | None = None) -> pd.DataFrame:
    end = end or dt.date.today().isoformat()
    df = _to_df(bs.query_history_k_data_plus(code, BAR_FIELDS, start_date=start, end_date=end,
                                             frequency="d", adjustflag="3"))
    if df.empty:
        return df
    df = df.rename(columns={"turn": "turnover", "tradestatus": "trade_status", "pctChg": "pct_chg",
                            "peTTM": "pe_ttm", "pbMRQ": "pb", "psTTM": "ps_ttm", "isST": "is_st"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    _num(df, ["open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg",
              "pe_ttm", "pb", "ps_ttm", "is_st", "trade_status"])
    return df[["code", "date", "open", "high", "low", "close", "volume", "amount", "turnover",
               "pct_chg", "pe_ttm", "pb", "ps_ttm", "is_st", "trade_status"]]


def fetch_adj_factor(code: str) -> pd.DataFrame:
    df = _to_df(bs.query_adjust_factor(code=code, start_date="1990-01-01",
                                       end_date=dt.date.today().isoformat()))
    if df.empty:
        return pd.DataFrame(columns=["code", "date", "back_factor"])
    df = df.rename(columns={"dividOperateDate": "date", "backAdjustFactor": "back_factor"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["back_factor"] = pd.to_numeric(df["back_factor"], errors="coerce")
    return df[["code", "date", "back_factor"]].drop_duplicates(["code", "date"], keep="last")


def fetch_index(code: str, start: str) -> pd.DataFrame:
    df = _to_df(bs.query_history_k_data_plus(code, INDEX_FIELDS, start_date=start,
                                             end_date=dt.date.today().isoformat(), frequency="d"))
    if df.empty:
        return df
    df = df.rename(columns={"pctChg": "pct_chg"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    _num(df, ["open", "high", "low", "close", "amount", "pct_chg"])
    return df


def fetch_index_members(index: str, date: str) -> pd.DataFrame:
    """某日的历史成分股（baostock 返回该日之前最近一次调整后的名单）。"""
    fn = {"hs300": bs.query_hs300_stocks, "zz500": bs.query_zz500_stocks}[index]
    df = _to_df(fn(date=date))
    return pd.DataFrame({"index_code": index, "date": dt.date.fromisoformat(date), "code": df["code"]})


# ---- 多进程 worker（baostock 会话是进程级全局状态，不能多线程共用）----
def worker_init():
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        login()


def worker_st(args):
    """返回 (code, st_dates, share_df, error)。share_df 仅在 need_share 时返回：date, turnover, volume。"""
    import time
    code, start, need_share = args
    try:
        fields = "date,isST,turn,volume" if need_share else "date,isST"
        for attempt in range(4):  # 连接被重置时重新登录重试
            try:
                df = _to_df(bs.query_history_k_data_plus(code, fields, start_date=start,
                                                         end_date=dt.date.today().isoformat(), frequency="d"))
                break
            except Exception:  # noqa: BLE001
                if attempt == 3:
                    raise
                time.sleep(3 * (attempt + 1))
                try:
                    bs.logout()
                except Exception:  # noqa: BLE001
                    pass
                worker_init()
        if df.empty:
            return code, [], None, None
        df["date"] = pd.to_datetime(df["date"]).dt.date
        st = df.loc[df["isST"] == "1", "date"].tolist()
        share = None
        if need_share:
            _num(df, ["turn", "volume"])
            share = df[["date", "turn", "volume"]].rename(columns={"turn": "turnover"})
        return code, st, share, None
    except Exception as e:  # noqa: BLE001
        return code, None, None, repr(e)[:200]
