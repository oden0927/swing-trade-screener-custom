"""Phase 4: 買いトリガー判定（V2カラム名対応、検出窓を緩和）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd


@dataclass
class TriggerSignal:
    triggered: bool
    signal_type: str
    description: str
    book_reference: str


def evaluate_triggers(df: pd.DataFrame, resistances: List[float], supports: List[float]) -> List[TriggerSignal]:
    signals: List[TriggerSignal] = []
    if df.empty or len(df) < 5:
        return signals

    latest = df.iloc[-1]
    close = latest["AdjC"]
    open_ = latest["AdjO"]
    low = latest["AdjL"]
    high = latest["AdjH"]
    ma5 = latest.get("MA5")

    # トリガー1: 5日MAを陽線で上抜け（直近5日内）かつ 現在も5日MAの上に滞在
    if ma5 is not None and pd.notna(ma5):
        last_n = df.tail(6)
        cross_day = None
        for i in range(1, len(last_n)):
            prev_c = last_n["AdjC"].iloc[i - 1]
            prev_m = last_n["MA5"].iloc[i - 1]
            cur_c = last_n["AdjC"].iloc[i]
            cur_m = last_n["MA5"].iloc[i]
            cur_o = last_n["AdjO"].iloc[i]
            if pd.notna(prev_m) and pd.notna(cur_m) and prev_c < prev_m and cur_c > cur_m and cur_c > cur_o:
                cross_day = i
        # 現在価格が5日MAの上にあることを必須にする（一度上抜けてから下に戻った銘柄を除外）
        if cross_day is not None and close > ma5:
            days_ago = len(last_n) - 1 - cross_day
            signals.append(TriggerSignal(
                True,
                "MA5_BREAK",
                f"5日MA({ma5:.0f})を陽線で上抜け（{days_ago}日前）、現在も上に滞在、終値{close:.0f}",
                "4時限目02③ p.137-139",
            ))

    # トリガー2: サポートライン付近で下ヒゲ大陽線（距離2→3%に緩和、直近3日内）
    last3 = df.tail(3)
    for i in range(len(last3)):
        row = last3.iloc[i]
        b_close = row["AdjC"]
        b_open = row["AdjO"]
        b_low = row["AdjL"]
        b_high = row["AdjH"]
        body = abs(b_close - b_open)
        lower_wick = (min(b_open, b_close) - b_low)
        full_range = b_high - b_low
        if full_range <= 0:
            continue
        # 陽線、下ヒゲが本体以上、本体が範囲の30%以上
        if b_close > b_open and lower_wick >= body * 0.8 and body / full_range > 0.30:
            for sup in supports:
                if sup > 0 and abs(b_low - sup) / sup < 0.03:
                    days_ago = len(last3) - 1 - i
                    signals.append(TriggerSignal(
                        True,
                        "SUPPORT_BOUNCE",
                        f"サポート {sup:.0f} 付近で下ヒゲ大陽線（{days_ago}日前、安値{b_low:.0f}、終値{b_close:.0f}）",
                        "4時限目02 p.142-143 / 1時限目02⑧ p.43-44",
                    ))
                    break
            break  # 直近の1本だけで判定

    # トリガー3: 新高値ブレイク後の戻し→反発
    if len(df) >= 60:
        rolling_high = df["AdjH"].rolling(60).max().shift(1).iloc[-1]
        if pd.notna(rolling_high):
            recent5 = df.tail(5)
            broke = (recent5["AdjC"] > rolling_high).any()
            prev_close = df["AdjC"].iloc[-2]
            if broke and close > open_ and close > prev_close:
                signals.append(TriggerSignal(
                    True,
                    "NEW_HIGH_REENTRY",
                    f"60日高値ブレイク後の反発陽線（終値{close:.0f}）",
                    "4時限目03 p.144-148",
                ))

    return signals
