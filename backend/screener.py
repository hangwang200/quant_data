"""选股器：按规则过滤截面。规则格式 {"field": "roe_ann", "min": 15, "max": null}。
同一套规则既用于选股器（最新截面），也用于回测（每个信号日动态筛选，避免用未来数据）。
"""
from __future__ import annotations

import pandas as pd

from backend.db.conn import query_df
from backend.factors.build import FACTORS, MARKET_FIELDS

SNAPSHOT_COLS = ["code", "name", "industry", "close", "pct_chg", "amount", "listed_days", "is_st",
                 "close_hfq", "fin_report_date"] + list(FACTORS) + list(MARKET_FIELDS)


def apply_rules(df: pd.DataFrame, rules: list[dict], industries: list[str] | None = None) -> pd.DataFrame:
    from backend.formula import all_factors, materialize

    known = all_factors()
    for r in rules or []:
        if r.get("field") not in known:
            raise ValueError(f"未知字段: {r.get('field')}")
    df = materialize(df, [r["field"] for r in rules or []], by=None)
    mask = pd.Series(True, index=df.index)
    for r in rules or []:
        f = r.get("field")
        col = df[f]
        if r.get("min") is not None:
            mask &= col >= float(r["min"])
        if r.get("max") is not None:
            mask &= col <= float(r["max"])
    if industries:
        mask &= df["industry"].isin(industries)
    return df[mask]


def latest_date():
    return query_df("SELECT max(date) d FROM factor_daily").d.iloc[0]


def snapshot(date=None, with_custom: bool = True) -> pd.DataFrame:
    """最新截面（含全部公式因子列）。"""
    from backend.formula import custom_factors, materialize

    date = date or latest_date()
    df = query_df(f"SELECT {', '.join(SNAPSHOT_COLS)} FROM factor_view WHERE date = ?", [date])
    if with_custom:
        for name in custom_factors():
            try:
                df = materialize(df, [name], by=None)
            except Exception:  # noqa: BLE001 — 单个公式出错不影响整体
                df[name] = None
    return df


def screen(rules: list[dict], industries: list[str] | None = None, exclude_st: bool = True,
           date=None, sort: str | None = None, desc: bool = True, expr: str | None = None) -> pd.DataFrame:
    from backend.formula import evaluate

    df = snapshot(date)
    if exclude_st:
        df = df[df.is_st != 1]
    df = apply_rules(df, rules, industries)
    if expr:
        df = df[evaluate(expr, df, by=None).fillna(0) != 0]
    if sort and sort in df.columns:
        df = df.sort_values(sort, ascending=not desc, na_position="last")
    return df
