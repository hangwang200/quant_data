"""个股资产负债表（东方财富 F10，按需拉取最近若干报告期并缓存到 balance_sheet 表）。

明细科目很多且银行/保险/券商口径不同，这里归并为十几个"结构项"：
已知科目按组相加，剩余部分用 流动/非流动 合计减去已归类部分得到"其他"，保证各项之和等于合计。
"""
from __future__ import annotations

import datetime as dt
import json
import math

import pandas as pd

from backend.db.conn import connect, query_df

_BASE = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis"
TTL_DAYS = 3

# (显示名, [科目])：科目写作 "A|B+C" 表示优先用 A，A 缺失时用 B 与 C 之和（避免合计科目与明细重复相加）
ASSET_ITEMS = [
    ("货币资金", ["MONETARYFUNDS", "SETTLE_EXCESS_RESERVE", "TIME_DEPOSIT"]),
    ("存放央行", ["CASH_DEPOSIT_PBC"]),
    ("交易性金融资产", ["TRADE_FINASSET_NOTFVTPL|TRADE_FINASSET", "DERIVE_FINASSET", "FVTPL_FINASSET"]),
    ("拆出及返售", ["LEND_FUND", "BUY_RESALE_FINASSET", "DEPOSIT_INTERBANK"]),
    ("应收账款及票据", ["NOTE_ACCOUNTS_RECE|ACCOUNTS_RECE+NOTE_RECE", "FINANCE_RECE", "CONTRACT_ASSET", "RECEIVABLES"]),
    ("预付及其他应收", ["PREPAYMENT", "TOTAL_OTHER_RECE|OTHER_RECE"]),
    ("存货", ["INVENTORY"]),
    ("发放贷款及融出", ["LOAN_ADVANCE", "FIN_FUND"]),
    ("债权及长期投资", ["LONG_EQUITY_INVEST", "AMORTIZE_COST_FINASSET", "FVTOCI_FINASSET", "CREDITOR_INVEST", "OTHER_CREDITOR_INVEST", "OTHER_EQUITY_INVEST",
              "OTHER_NONCURRENT_FINASSET", "AVAILABLE_SALE_FINASSET", "HOLD_MATURITY_INVEST", "INVEST_REALESTATE"]),
    ("固定资产及在建", ["FIXED_ASSET", "CIP", "USERIGHT_ASSET"]),
    ("无形资产", ["INTANGIBLE_ASSET", "DEVELOP_EXPENSE"]),
    ("商誉", ["GOODWILL"]),
]
LIAB_ITEMS = [
    ("短期借款", ["SHORT_LOAN", "BORROW_FUND", "SHORT_FIN_PAYABLE"]),
    ("交易性金融负债", ["TRADE_FINLIAB_NOTFVTPL|TRADE_FINLIAB", "FVTPL_FINLIAB", "DERIVE_FINLIAB"]),
    ("存款及代理客户款", ["ACCEPT_DEPOSIT", "AGENT_TRADE_SECURITY", "ACCEPT_DEPOSIT_INTERBANK", "FUND_INTERBANK", "SELL_REPO_FINASSET", "LOAN_PBC", "IOFI_DEPOSIT"]),
    ("应付账款及票据", ["NOTE_ACCOUNTS_PAYABLE|ACCOUNTS_PAYABLE+NOTE_PAYABLE"]),
    ("合同负债及预收", ["CONTRACT_LIAB", "ADVANCE_RECEIVABLES"]),
    ("薪酬及税费", ["STAFF_SALARY_PAYABLE", "TAX_PAYABLE"]),
    ("其他应付", ["TOTAL_OTHER_PAYABLE|OTHER_PAYABLE"]),
    ("一年内到期", ["NONCURRENT_LIAB_1YEAR"]),
    ("长期借款", ["LONG_LOAN"]),
    ("应付债券", ["BOND_PAYABLE"]),
    ("租赁负债", ["LEASE_LIAB"]),
]
# 这些科目属于流动部分（用于把剩余项拆成"其他流动/其他非流动"）
_CURRENT_ASSET = {"货币资金", "交易性金融资产", "拆出及返售", "应收账款及票据", "预付及其他应收", "存货"}
_CURRENT_LIAB = {"短期借款", "交易性金融负债", "存款及代理客户款", "应付账款及票据", "合同负债及预收", "薪酬及税费", "其他应付", "一年内到期"}


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pick(raw: dict, cand: str) -> float:
    for alt in cand.split("|"):
        vals = [v for v in (_num(raw.get(k)) for k in alt.split("+")) if v is not None]
        if vals:
            return sum(vals)
    return 0.0


def _group(raw: dict, items, total_key, cur_key, ncur_key, cur_names, other_cur, other_ncur, other_all):
    out, cur_sum, ncur_sum = [], 0.0, 0.0
    for label, cands in items:
        v = sum(_pick(raw, cand) for cand in cands)
        if v:
            out.append({"name": label, "value": v})
            if label in cur_names:
                cur_sum += v
            else:
                ncur_sum += v
    total = _num(raw.get(total_key))
    cur, ncur = _num(raw.get(cur_key)), _num(raw.get(ncur_key))
    tol = abs(total or 0) * 0.002
    if cur is not None and ncur is not None:
        if cur - cur_sum > tol:
            out.append({"name": other_cur, "value": cur - cur_sum})
        if ncur - ncur_sum > tol:
            out.append({"name": other_ncur, "value": ncur - ncur_sum})
    elif total is not None and total - cur_sum - ncur_sum > tol:  # 银行等金融企业不分流动/非流动
        out.append({"name": other_all, "value": total - cur_sum - ncur_sum})
    return out, total


def structure(raw: dict) -> dict:
    assets, ta = _group(raw, ASSET_ITEMS, "TOTAL_ASSETS", "TOTAL_CURRENT_ASSETS", "TOTAL_NONCURRENT_ASSETS",
                        _CURRENT_ASSET, "其他流动资产", "其他非流动资产", "其他资产")
    liabs, tl = _group(raw, LIAB_ITEMS, "TOTAL_LIABILITIES", "TOTAL_CURRENT_LIAB", "TOTAL_NONCURRENT_LIAB",
                       _CURRENT_LIAB, "其他流动负债", "其他非流动负债", "其他负债")
    eq = _num(raw.get("TOTAL_EQUITY"))
    return {
        "assets": assets, "liabilities": liabs, "total_assets": ta, "total_liabilities": tl, "equity": eq,
        "parent_equity": _num(raw.get("TOTAL_PARENT_EQUITY")),
        "current_assets": _num(raw.get("TOTAL_CURRENT_ASSETS")), "current_liab": _num(raw.get("TOTAL_CURRENT_LIAB")),
        "debt_ratio": (tl / ta * 100) if ta and tl is not None else None,
        "current_ratio": (_num(raw.get("TOTAL_CURRENT_ASSETS")) / _num(raw.get("TOTAL_CURRENT_LIAB"))
                          if _num(raw.get("TOTAL_CURRENT_LIAB")) and _num(raw.get("TOTAL_CURRENT_ASSETS")) is not None
                          else None),
    }


def _em_code(code: str) -> str:
    return code.replace(".", "").upper()  # sh.600519 -> SH600519


def fetch(code: str, periods: int = 12) -> pd.DataFrame:
    """拉取最近 periods 个报告期的资产负债表原始科目。"""
    from akshare.stock.finance.stock_three_report_em import _stock_balance_sheet_by_report_ctype_em
    import requests

    sym = _em_code(code)
    ctype = _stock_balance_sheet_by_report_ctype_em(symbol=sym)
    s = requests.Session()
    r = s.get(f"{_BASE}/zcfzbDateAjaxNew", params={"companyType": ctype, "reportDateType": "0", "code": sym},
              timeout=15)
    dates = [str(d["REPORT_DATE"])[:10] for d in r.json().get("data", [])][:periods]
    rows = []
    for i in range(0, len(dates), 5):
        r = s.get(f"{_BASE}/zcfzbAjaxNew", params={"companyType": ctype, "reportDateType": "0", "reportType": "1",
                                                   "dates": ",".join(dates[i:i + 5]), "code": sym}, timeout=15)
        rows += r.json().get("data", []) or []
    if not rows:
        return pd.DataFrame(columns=["code", "report_date", "data", "fetched_at"])
    now = dt.datetime.now()
    out = [{"code": code, "report_date": dt.date.fromisoformat(str(x["REPORT_DATE"])[:10]),
            "data": json.dumps({k: v for k, v in x.items() if _num(v) is not None}), "fetched_at": now} for x in rows]
    return pd.DataFrame(out).drop_duplicates("report_date")


def get(code: str, refresh: bool = False) -> list[dict]:
    """返回各报告期结构（新→旧）。缓存超过 TTL_DAYS 天才重新拉取；拉取失败时回退到缓存。"""
    have = query_df("SELECT report_date, data, fetched_at FROM balance_sheet WHERE code = ? ORDER BY report_date DESC",
                    [code])
    stale = have.empty or refresh or (dt.datetime.now() - pd.Timestamp(have.fetched_at.max()).to_pydatetime()
                                      > dt.timedelta(days=TTL_DAYS))
    if stale:
        try:
            df = fetch(code)
            if not df.empty:
                with connect(read_only=False) as con:
                    con.register("bs_new", df)
                    con.execute("DELETE FROM balance_sheet WHERE code = ?", [code])
                    con.execute("INSERT INTO balance_sheet SELECT code, report_date, data, fetched_at FROM bs_new")
                have = df.sort_values("report_date", ascending=False)
        except Exception:  # noqa: BLE001  数据源不可用时用缓存
            if have.empty:
                raise
    out = []
    for r in have.itertuples():
        raw = json.loads(r.data) if isinstance(r.data, str) else r.data
        out.append({"report_date": str(r.report_date)[:10], "fetched_at": str(r.fetched_at)[:19], **structure(raw)})
    return out
