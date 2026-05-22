"""Phase 5: リスクリワード設計（5時限目、V2カラム名対応）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd

import config


@dataclass
class RiskReward:
    entry: float
    stop_loss: float
    take_profit: float
    risk_pct: float
    reward_pct: float
    rr_ratio: float
    stop_basis: str
    target_basis: str
    valid: bool


def _tick_size(price: float) -> float:
    if price < 3000:
        return 1
    if price < 5000:
        return 5
    if price < 30000:
        return 10
    if price < 50000:
        return 50
    return 100


def compute_risk_reward(
    df: pd.DataFrame,
    supports: List[float],
    resistances: List[float],
    rr_target: float = config.DEFAULT_RR_RATIO,
) -> RiskReward:
    if df.empty:
        return RiskReward(0, 0, 0, 0, 0, 0, "", "", False)

    latest = df.iloc[-1]
    entry = float(latest["AdjC"])
    ma5 = latest.get("MA5", np.nan)
    ma60 = latest.get("MA60", np.nan)

    candidates: List[Tuple[float, str]] = []
    for sup in supports:
        if sup < entry:
            candidates.append((sup, f"サポートライン({sup:.0f})"))
    if not pd.isna(ma5) and ma5 < entry:
        candidates.append((float(ma5), f"5日MA({ma5:.0f})"))
    if not pd.isna(ma60) and ma60 < entry:
        candidates.append((float(ma60), f"60日MA({ma60:.0f})"))
    recent_low = float(df["AdjL"].tail(20).min())
    candidates.append((recent_low, f"直近20日安値({recent_low:.0f})"))

    if not candidates:
        return RiskReward(entry, 0, 0, 0, 0, 0, "なし", "", False)

    candidates.sort(key=lambda x: entry - x[0])
    raw_stop, stop_basis_name = candidates[0]
    tick = _tick_size(entry)
    stop_loss = raw_stop - tick * config.LOSS_CUT_TICKS
    if stop_loss <= 0:
        stop_loss = raw_stop * 0.95
    risk_pct = (entry - stop_loss) / entry if entry else 0.0

    rr_target_pct = risk_pct * rr_target
    rr_target_price = entry * (1 + rr_target_pct)
    take_profit = rr_target_price
    target_basis = f"リスク幅 {risk_pct:.1%} の {rr_target:.1f}倍上"
    for res in resistances:
        if res > entry and res >= rr_target_price * 0.95:
            take_profit = res
            target_basis = f"レジスタンスライン({res:.0f})"
            break

    reward_pct = (take_profit - entry) / entry if entry else 0.0
    rr_ratio = reward_pct / risk_pct if risk_pct else 0.0

    return RiskReward(
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_pct=risk_pct,
        reward_pct=reward_pct,
        rr_ratio=rr_ratio,
        stop_basis=f"{stop_basis_name} から {config.LOSS_CUT_TICKS}ティック下",
        target_basis=target_basis,
        valid=rr_ratio >= rr_target,
    )
