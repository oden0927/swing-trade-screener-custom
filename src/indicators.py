"""テクニカル指標の計算（V2 API カラム名対応）。

V2 API: AdjC, AdjH, AdjL, AdjO, AdjVo を使用。
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd

import config


# ----------------- 移動平均線 -----------------
def add_moving_averages(df: pd.DataFrame, price_col: str = "AdjC") -> pd.DataFrame:
    """5日/20日/60日/200日MAを追加。"""
    out = df.copy()
    for period in (config.SHORT_MA, config.MID_MA, config.LONG_MA, config.ULTRA_LONG_MA):
        out[f"MA{period}"] = out[price_col].rolling(window=period, min_periods=period).mean()
    return out


# ----------------- 一目均衡表 -----------------
def add_ichimoku(
    df: pd.DataFrame,
    high_col: str = "AdjH",
    low_col: str = "AdjL",
    close_col: str = "AdjC",
) -> pd.DataFrame:
    """一目均衡表の5本線を追加（3時限目06）。"""
    out = df.copy()
    tenkan = config.ICHIMOKU_TENKAN
    kijun = config.ICHIMOKU_KIJUN
    senkou_b = config.ICHIMOKU_SENKOU_B

    out["Ichimoku_Tenkan"] = (
        out[high_col].rolling(tenkan).max() + out[low_col].rolling(tenkan).min()
    ) / 2
    out["Ichimoku_Kijun"] = (
        out[high_col].rolling(kijun).max() + out[low_col].rolling(kijun).min()
    ) / 2
    out["Ichimoku_SenkouA"] = ((out["Ichimoku_Tenkan"] + out["Ichimoku_Kijun"]) / 2).shift(kijun)
    out["Ichimoku_SenkouB"] = (
        (out[high_col].rolling(senkou_b).max() + out[low_col].rolling(senkou_b).min()) / 2
    ).shift(kijun)
    out["Ichimoku_Chikou"] = out[close_col].shift(-kijun)
    return out


# ----------------- RSI -----------------
def add_rsi(df: pd.DataFrame, price_col: str = "AdjC", period: int = config.RSI_PERIOD) -> pd.DataFrame:
    out = df.copy()
    delta = out[price_col].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    out[f"RSI{period}"] = 100 - (100 / (1 + rs))
    return out


# ----------------- MACD（移動平均収束発散） -----------------
def add_macd(
    df: pd.DataFrame,
    price_col: str = "AdjC",
    fast: int = config.MACD_FAST,
    slow: int = config.MACD_SLOW,
    signal: int = config.MACD_SIGNAL,
) -> pd.DataFrame:
    """MACDを追加。

    標準設定: 12期間EMA - 26期間EMA = MACD線、その9期間EMA = シグナル線。
    ヒストグラム = MACD - Signal。
    """
    out = df.copy()
    ema_fast = out[price_col].ewm(span=fast, adjust=False).mean()
    ema_slow = out[price_col].ewm(span=slow, adjust=False).mean()
    out[f"EMA{fast}"] = ema_fast
    out[f"EMA{slow}"] = ema_slow
    out["MACD"] = ema_fast - ema_slow
    out["MACD_Signal"] = out["MACD"].ewm(span=signal, adjust=False).mean()
    out["MACD_Hist"] = out["MACD"] - out["MACD_Signal"]
    return out


# ----------------- 出来高指標 -----------------
def add_volume_metrics(df: pd.DataFrame, volume_col: str = "AdjVo", period: int = 20) -> pd.DataFrame:
    out = df.copy()
    out[f"Vol_MA{period}"] = out[volume_col].rolling(period).mean()
    out[f"Vol_Ratio{period}"] = out[volume_col] / out[f"Vol_MA{period}"]
    # 出来高比の20日移動平均（直近の出来高傾向）
    # = 直近20日が長期平均比でどれだけ盛り上がっていたかを示す
    # 1.0 = 平均的、1.2+ = じわじわ買われている、1.5+ = 急増
    out[f"Vol_Ratio{period}_avg{period}"] = out[f"Vol_Ratio{period}"].rolling(period).mean()
    return out


# ----------------- ライン分析（自動レジサポ検出） -----------------
def detect_recent_levels(
    df: pd.DataFrame,
    lookback: int = 120,
    pivot_window: int = 5,
    top_n: int = 5,
    high_col: str = "AdjH",
    low_col: str = "AdjL",
) -> Tuple[list, list]:
    """直近のピボット高値/安値からレジスタンス/サポート候補を返す。"""
    if len(df) < lookback:
        return [], []
    window = df.tail(lookback).reset_index(drop=True)

    highs = []
    lows = []
    for i in range(pivot_window, len(window) - pivot_window):
        high = window.loc[i, high_col]
        low = window.loc[i, low_col]
        left_high = window.loc[i - pivot_window:i, high_col].max()
        right_high = window.loc[i:i + pivot_window, high_col].max()
        left_low = window.loc[i - pivot_window:i, low_col].min()
        right_low = window.loc[i:i + pivot_window, low_col].min()
        if high == max(left_high, right_high):
            highs.append((window.loc[i, "Date"], high))
        if low == min(left_low, right_low):
            lows.append((window.loc[i, "Date"], low))

    resistances = sorted({round(h, 1) for _, h in highs}, reverse=True)[:top_n]
    supports = sorted({round(l, 1) for _, l in lows})[:top_n]
    return resistances, supports


# ----------------- カラム名の正規化 -----------------
def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """V1 互換カラム名（AdjustmentClose 等）も V2 短縮形に統一する。"""
    rename_map = {
        "AdjustmentOpen": "AdjO",
        "AdjustmentHigh": "AdjH",
        "AdjustmentLow": "AdjL",
        "AdjustmentClose": "AdjC",
        "AdjustmentVolume": "AdjVo",
        "Open": "O",
        "High": "H",
        "Low": "L",
        "Close": "C",
        "Volume": "Vo",
    }
    rename = {k: v for k, v in rename_map.items() if k in df.columns and v not in df.columns}
    if rename:
        df = df.rename(columns=rename)
    return df


# ----------------- すべて適用 -----------------
def enrich_one(df: pd.DataFrame) -> pd.DataFrame:
    """1銘柄の日足DataFrameに全指標を付与。"""
    df = df.copy().sort_values("Date").reset_index(drop=True)
    df = _normalize_columns(df)
    # TOPIX等で AdjC がないケース → C で代用
    if "AdjC" not in df.columns and "C" in df.columns:
        df["AdjC"] = df["C"]
        df["AdjH"] = df.get("H", df["AdjC"])
        df["AdjL"] = df.get("L", df["AdjC"])
        df["AdjO"] = df.get("O", df["AdjC"])
        df["AdjVo"] = df.get("Vo", 0)
    df = add_moving_averages(df)
    df = add_ichimoku(df)
    df = add_rsi(df)
    df = add_macd(df)
    df = add_volume_metrics(df)
    return df
