"""相場環境判定（2時限目・4時限目に準拠）。

V2 API カラム名（AdjC）を使う。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

import config

EnvLabel = Literal["UPTREND", "BOX", "DOWNTREND", "UNCLEAR"]


@dataclass
class EnvironmentResult:
    label: EnvLabel
    confidence: float
    ma20_slope: float
    ma60_slope: float
    price_vs_ma20: float
    perfect_order: bool
    notes: str


def _slope(series: pd.Series, window: int = 5) -> float:
    if len(series.dropna()) < window + 1:
        return float("nan")
    recent = series.dropna().tail(window + 1).to_numpy()
    return float((recent[-1] - recent[0]) / recent[0]) if recent[0] else 0.0


def judge_environment(df: pd.DataFrame) -> EnvironmentResult:
    if df.empty or len(df) < config.LONG_MA:
        return EnvironmentResult("UNCLEAR", 0.0, np.nan, np.nan, np.nan, False, "データ不足")

    latest = df.iloc[-1]
    close = latest["AdjC"]
    ma5 = latest.get("MA5", np.nan)
    ma20 = latest.get("MA20", np.nan)
    ma60 = latest.get("MA60", np.nan)

    if pd.isna(ma20) or pd.isna(ma60):
        return EnvironmentResult("UNCLEAR", 0.0, np.nan, np.nan, np.nan, False, "MA未計算")

    ma20_slope = _slope(df["MA20"])
    ma60_slope = _slope(df["MA60"])
    price_vs_ma20 = (close - ma20) / ma20 if ma20 else 0.0

    perfect_order = bool(
        not pd.isna(ma5) and ma5 > ma20 > ma60 and ma20_slope > 0 and ma60_slope >= 0
    )

    UPTREND_SLOPE = 0.005
    DOWNTREND_SLOPE = -0.005
    notes = []

    if ma20_slope > UPTREND_SLOPE and ma60_slope >= 0 and price_vs_ma20 > -0.02:
        label = "UPTREND"
        confidence = 0.8 if perfect_order else 0.65
        notes.append("20MA上向き")
        if perfect_order:
            notes.append("パーフェクトオーダー成立")
    elif ma20_slope < DOWNTREND_SLOPE and ma60_slope <= 0 and price_vs_ma20 < 0.02:
        label = "DOWNTREND"
        confidence = 0.8 if (not pd.isna(ma5) and ma5 < ma20 < ma60) else 0.65
        notes.append("20MA下向き")
    elif abs(ma20_slope) <= UPTREND_SLOPE:
        label = "BOX"
        confidence = 0.7
        notes.append("20MA横ばい")
    else:
        label = "UNCLEAR"
        confidence = 0.4
        notes.append("MAの方向が混在")

    if price_vs_ma20 > 0.10:
        notes.append("20MAから大きく上方乖離（パターン④警戒）")
    elif price_vs_ma20 < -0.10:
        notes.append("20MAから大きく下方乖離")

    return EnvironmentResult(
        label=label,
        confidence=confidence,
        ma20_slope=ma20_slope,
        ma60_slope=ma60_slope,
        price_vs_ma20=price_vs_ma20,
        perfect_order=perfect_order,
        notes="; ".join(notes),
    )


def judge_market_regime(topix_df: pd.DataFrame) -> EnvironmentResult:
    """TOPIX から全体地合いを判定。"""
    if topix_df.empty:
        return EnvironmentResult("UNCLEAR", 0.0, np.nan, np.nan, np.nan, False, "TOPIXデータなし")

    from .indicators import enrich_one
    df = enrich_one(topix_df)
    return judge_environment(df)
