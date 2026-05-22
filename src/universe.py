"""Phase 0: ユニバース絞り込み（V2 API カラム名対応）。"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

import config

logger = logging.getLogger(__name__)


def is_in_universe(master_row: pd.Series) -> bool:
    """銘柄マスタ1行からユニバース対象かを判定。"""
    scale = master_row.get("ScaleCat", "") or ""
    if config.UNIVERSE == "NIKKEI225":
        target = {"TOPIX Core30", "TOPIX Large70"}
    elif config.UNIVERSE == "JPX400":
        target = {"TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"}
    else:
        target = {"TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"}
    return scale in target


def passes_volume_filter(daily_df: pd.DataFrame) -> bool:
    """直近20日平均出来高が閾値以上か（AdjVo を使う）。"""
    if "Vol_MA20" not in daily_df.columns or daily_df["Vol_MA20"].dropna().empty:
        return False
    avg_vol = daily_df["Vol_MA20"].dropna().iloc[-1]
    return avg_vol >= config.MIN_AVG_VOLUME


def passes_financial_filter(code: str, financials: pd.DataFrame) -> bool:
    """直近4期で赤字続きでないかをチェック。"""
    if financials.empty:
        return True
    code_col = "LocalCode" if "LocalCode" in financials.columns else "Code"
    sub = financials[financials[code_col].astype(str) == str(code)] if code_col in financials.columns else pd.DataFrame()
    if sub.empty:
        return True
    np_col = None
    for cand in ("NetIncome", "NP", "Profit"):
        if cand in sub.columns:
            np_col = cand
            break
    if np_col is None:
        return True
    recent = sub.tail(4)
    if recent.empty:
        return True
    deficit_count = (pd.to_numeric(recent[np_col], errors="coerce") < 0).sum()
    return deficit_count < 3


def is_earnings_blackout(code: str, announcements: pd.DataFrame, today: Optional[date] = None) -> bool:
    """直近 N 営業日以内に決算発表予定があるか。"""
    if announcements.empty:
        return False
    if today is None:
        today = date.today()
    if "Code" not in announcements.columns:
        return False
    sub = announcements[announcements["Code"].astype(str) == str(code)]
    if sub.empty or "Date" not in sub.columns:
        return False
    dates = pd.to_datetime(sub["Date"], errors="coerce").dt.date
    cutoff = today + timedelta(days=config.EARNINGS_AVOIDANCE_DAYS)
    return any((d >= today and d <= cutoff) for d in dates if pd.notna(d))


def is_earnings_sensitive_sector(master_row: pd.Series) -> bool:
    """サプライズ業種かを判定。"""
    s33 = str(master_row.get("S33") or "")
    return s33 in config.EARNINGS_SENSITIVE_S33_CODES
