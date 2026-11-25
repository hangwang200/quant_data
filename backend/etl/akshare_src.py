"""AkShare 数据源：按报告期下载全市场财报（东方财富 业绩报表 + 利润表）。"""
from __future__ import annotations

import datetime as dt

import pandas as pd

# 法定披露截止：一季报 4/30，半年报 8/31，三季报 10/31，年报次年 4/30
_DEADLINE = {3: (0, 4, 30), 6: (0, 8, 31), 9: (0, 10, 31), 12: (1, 4, 30)}
_ROE_ANN = {3: 4.0, 6: 2.0, 9: 4.0 / 3.0, 12: 1.0}


def to_bs_code(c: str) -> str:
    c = str(c).zfill(6)
    if c.startswith("92"):  # 北交所新代码
        return f"bj.{c}"
    if c.startswith(("6", "9")):
        return f"sh.{c}"
    if c.startswith(("0", "2", "3")):
        return f"sz.{c}"
    return f"bj.{c}"


def deadline(report_date: dt.date) -> dt.date:
    dy, m, d = _DEADLINE[report_date.month]
    return dt.date(report_date.year + dy, m, d)


def report_periods(start_year: int, until: dt.date | None = None) -> list[dt.date]:
    """所有已经过了截止日或者可能已有数据的报告期。"""
    until = until or dt.date.today()
    out = []
    for y in range(start_year, until.year + 1):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            p = dt.date(y, m, d)
            if p < until:
                out.append(p)
    return out


def fetch_report(report_date: dt.date) -> pd.DataFrame:
    import akshare as ak

    ds = report_date.strftime("%Y%m%d")
    yj = ak.stock_yjbb_em(date=ds)
    yj = yj.rename(columns={
        "股票代码": "code", "股票简称": "name", "每股收益": "eps",
        "营业总收入-营业总收入": "revenue", "营业总收入-同比增长": "revenue_yoy",
        "净利润-净利润": "net_profit", "净利润-同比增长": "net_profit_yoy",
        "每股净资产": "bps", "净资产收益率": "roe", "每股经营现金流量": "ocf_ps",
        "销售毛利率": "gross_margin", "所处行业": "industry_em", "最新公告日期": "announce_date",
    })
    yj = yj[["code", "name", "eps", "revenue", "revenue_yoy", "net_profit", "net_profit_yoy",
             "bps", "roe", "ocf_ps", "gross_margin", "industry_em", "announce_date"]]

    try:
        lr = ak.stock_lrb_em(date=ds)
        lr = lr.rename(columns={
            "股票代码": "code", "营业总支出-营业支出": "op_cost", "营业总支出-销售费用": "sell_exp",
            "营业总支出-管理费用": "admin_exp", "营业总支出-财务费用": "fin_exp",
            "营业总支出-营业总支出": "total_expense", "营业利润": "op_profit", "利润总额": "total_profit",
        })[["code", "op_cost", "sell_exp", "admin_exp", "fin_exp", "total_expense", "op_profit", "total_profit"]]
        df = yj.merge(lr.drop_duplicates("code"), on="code", how="left")
    except Exception:  # 利润表缺失时仍保留业绩报表
        df = yj
        for c in ["op_cost", "sell_exp", "admin_exp", "fin_exp", "total_expense", "op_profit", "total_profit"]:
            df[c] = None

    df = df.drop_duplicates("code")
    df["code"] = df["code"].map(to_bs_code)
    df["report_date"] = report_date
    df["announce_date"] = pd.to_datetime(df["announce_date"], errors="coerce").dt.date
    dl = deadline(report_date)
    # 公告日晚于截止日通常是"更正/重述"后的最新日期，原始报告在截止日前已披露
    df["effective_date"] = df["announce_date"].map(lambda d: dl if pd.isna(d) or d > dl else d)
    num = ["eps", "revenue", "revenue_yoy", "net_profit", "net_profit_yoy", "bps", "roe", "ocf_ps",
           "gross_margin", "op_cost", "sell_exp", "admin_exp", "fin_exp", "total_expense",
           "op_profit", "total_profit"]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["roe_ann"] = df["roe"] * _ROE_ANN[report_date.month]
    return df


def fetch_dividend(report_date: dt.date) -> pd.DataFrame:
    """东方财富 分红送配：按报告期一次拉全市场。现金分红比例单位为"元/10股"。"""
    import akshare as ak

    try:
        df = ak.stock_fhps_em(date=report_date.strftime("%Y%m%d"))
    except TypeError:  # 该报告期无任何分红记录时 AkShare 内部返回 None（常见于早年一季报/三季报）
        df = None
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        "代码": "code", "名称": "name", "现金分红-现金分红比例": "cash_per10", "送转股份-送转总比例": "bonus_per10",
        "预案公告日": "plan_date", "股权登记日": "record_date", "除权除息日": "ex_date", "方案进度": "progress",
        "总股本": "total_share",
    })
    df = df[["code", "name", "cash_per10", "bonus_per10", "plan_date", "record_date", "ex_date", "progress",
             "total_share"]].drop_duplicates("code").copy()
    df["code"] = df["code"].map(to_bs_code)
    df["report_date"] = report_date
    for c in ["cash_per10", "bonus_per10", "total_share"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["dps"] = df["cash_per10"] / 10
    for c in ["plan_date", "record_date", "ex_date"]:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    return df[["code", "report_date", "name", "dps", "bonus_per10", "plan_date", "record_date", "ex_date",
               "progress", "total_share"]]
