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


# =====================================================================
# 【カスタム版・2026-05-23】上位足→下位足分析（本書 1時限目03 P49）
# =====================================================================
# 「上位足で方向感を把握 → 下位足でトレード判断」
# 月足・週足の環境を計算して、日足判定との整合性を確認するための関数。
# =====================================================================

def _resample_ohlcv(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """日足 DataFrame を週足 ('W-FRI') または月足 ('ME') に集約。

    OHLCV を適切に集約し、その上で MA・slope を計算できる形に整える。
    """
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    work["Date"] = pd.to_datetime(work["Date"])
    work = work.set_index("Date").sort_index()

    # AdjC が必須。他の列は存在する場合のみ集約
    agg_map = {}
    for col in ("AdjO", "AdjH", "AdjL", "AdjC", "AdjVo"):
        if col in work.columns:
            if col == "AdjO":
                agg_map[col] = "first"
            elif col == "AdjH":
                agg_map[col] = "max"
            elif col == "AdjL":
                agg_map[col] = "min"
            elif col == "AdjC":
                agg_map[col] = "last"
            elif col == "AdjVo":
                agg_map[col] = "sum"

    if not agg_map:
        return pd.DataFrame()

    resampled = work.resample(freq).agg(agg_map).dropna(subset=["AdjC"])
    resampled = resampled.reset_index()
    return resampled


def judge_environment_at_timeframe(
    daily_df: pd.DataFrame,
    timeframe: str = "weekly",
) -> EnvironmentResult:
    """指定タイムフレームでの相場環境を判定。

    timeframe: 'weekly' または 'monthly'
    内部では daily を resample し、MA5/MA20 を計算して judge_environment と同じ
    ロジックで UPTREND/BOX/DOWNTREND を判定する。

    必要データ目安:
      weekly  : 最低 20週分（≒ 140日）以上
      monthly : 最低 20か月分（≒ 600日）以上
    """
    if timeframe == "weekly":
        freq = "W-FRI"  # 週足は金曜終値ベース
        min_required = 20  # 最低 20週
    elif timeframe == "monthly":
        freq = "ME"     # 月足は月末ベース
        min_required = 20  # 最低 20か月
    else:
        return EnvironmentResult("UNCLEAR", 0.0, np.nan, np.nan, np.nan, False, f"不明なtimeframe: {timeframe}")

    resampled = _resample_ohlcv(daily_df, freq)
    if resampled.empty or len(resampled) < min_required:
        return EnvironmentResult(
            "UNCLEAR", 0.0, np.nan, np.nan, np.nan, False,
            f"{timeframe}データ不足（{len(resampled)}本）"
        )

    # MA5 / MA20 を計算（このタイムフレームでの 5/20 期間）
    resampled["MA5"] = resampled["AdjC"].rolling(5, min_periods=5).mean()
    resampled["MA20"] = resampled["AdjC"].rolling(20, min_periods=20).mean()
    # 60期間は週足だと60週=15か月、月足だと60か月=5年 → データ的に厳しいので
    # 上位足では 5/20 のみで判定
    # slope は MA20 の直近 5本での変化率
    if len(resampled) < min_required + 5:
        return EnvironmentResult(
            "UNCLEAR", 0.0, np.nan, np.nan, np.nan, False,
            f"{timeframe}slope計算不足"
        )

    latest = resampled.iloc[-1]
    close = latest["AdjC"]
    ma5 = latest.get("MA5", np.nan)
    ma20 = latest.get("MA20", np.nan)

    if pd.isna(ma5) or pd.isna(ma20):
        return EnvironmentResult(
            "UNCLEAR", 0.0, np.nan, np.nan, np.nan, False,
            f"{timeframe} MA未計算"
        )

    # MA20 の直近 5本での変化率（slope）
    ma20_series = resampled["MA20"].dropna()
    if len(ma20_series) < 6:
        ma20_slope = 0.0
    else:
        recent = ma20_series.tail(6).to_numpy()
        ma20_slope = float((recent[-1] - recent[0]) / recent[0]) if recent[0] else 0.0

    price_vs_ma20 = (close - ma20) / ma20 if ma20 else 0.0

    # 環境判定（judge_environment と同じロジック、ただし MA60 は使わない）
    UPTREND_SLOPE = 0.005
    DOWNTREND_SLOPE = -0.005
    notes = []
    perfect_order = bool(ma5 > ma20 and ma20_slope > 0)

    if ma20_slope > UPTREND_SLOPE and ma5 > ma20:
        label = "UPTREND"
        confidence = 0.75 if perfect_order else 0.65
        notes.append(f"{timeframe} MA20上向き")
    elif ma20_slope < DOWNTREND_SLOPE and ma5 < ma20:
        label = "DOWNTREND"
        confidence = 0.75
        notes.append(f"{timeframe} MA20下向き")
    elif abs(ma20_slope) <= UPTREND_SLOPE:
        label = "BOX"
        confidence = 0.65
        notes.append(f"{timeframe} MA20横ばい")
    else:
        label = "UNCLEAR"
        confidence = 0.4
        notes.append(f"{timeframe} 方向感不明確")

    return EnvironmentResult(
        label=label,
        confidence=confidence,
        ma20_slope=ma20_slope,
        ma60_slope=np.nan,  # 上位足では使わない
        price_vs_ma20=price_vs_ma20,
        perfect_order=perfect_order,
        notes="; ".join(notes),
    )


def evaluate_multi_timeframe(daily_df: pd.DataFrame) -> dict:
    """日足DataFrameから 月足/週足/日足 の3階層環境を一括判定して dict で返す。

    Returns:
        {
            "monthly": EnvironmentResult,
            "weekly": EnvironmentResult,
            "daily": EnvironmentResult,
            "alignment": str,  # "ALIGNED_UP" / "ALIGNED_DOWN" / "MIXED" / "PARTIAL_UP"
            "alignment_score": int,  # 上向き一致度（0-3、3が全て上向き）
        }
    """
    monthly = judge_environment_at_timeframe(daily_df, "monthly")
    weekly = judge_environment_at_timeframe(daily_df, "weekly")

    # 日足は既存 enrich_one + judge_environment を使用
    from .indicators import enrich_one
    daily_enriched = enrich_one(daily_df)
    daily_env = judge_environment(daily_enriched)

    # アライメント判定
    labels = [monthly.label, weekly.label, daily_env.label]
    up_count = sum(1 for L in labels if L == "UPTREND")
    down_count = sum(1 for L in labels if L == "DOWNTREND")

    if up_count == 3:
        alignment = "ALIGNED_UP"      # 月・週・日 全て上昇 → 最強買い場
    elif down_count == 3:
        alignment = "ALIGNED_DOWN"    # 全て下落 → 買い禁止
    elif up_count >= 2 and down_count == 0:
        alignment = "PARTIAL_UP"      # 2つが上、残りはBOX/UNCLEAR → 良い
    elif down_count >= 2:
        alignment = "PARTIAL_DOWN"    # 2つが下 → 危険
    else:
        alignment = "MIXED"           # 方向感バラバラ → 中立

    return {
        "monthly": monthly,
        "weekly": weekly,
        "daily": daily_env,
        "alignment": alignment,
        "alignment_score": up_count - down_count,  # -3 〜 +3
    }
