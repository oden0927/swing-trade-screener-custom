"""保有銘柄の売り判定ロジック（カスタム版 2026-05-24）。

書籍5時限目01-04 に基づき、エントリー後の銘柄について以下を機械的に判定:
  - C1: 過去高値到達 (20日/60日/250日高値)
  - C2: 上昇日数 7-9日 (5時限目「短期トレーダーが多く利確する時期」)
  - C3: 5日MA陰線割れ
  - C4: 弱いローソク足出現 (包み足/否定陰線/宵の明星)
  - C5: 損切ライン到達 (即時損切)
  - C6: 利確目標到達 (RR比達成)

これにより、感情的判断を排除した機械的な売り判断ができる。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls
from typing import List, Optional

import pandas as pd

from .indicators import enrich_one
from .patterns import _has_engulfing_bearish, _has_evening_star


@dataclass
class SellSignal:
    """個別の売りシグナル。"""
    signal_id: str
    label: str
    description: str
    severity: str  # "URGENT" / "STRONG" / "MODERATE" / "MILD"
    book_reference: str


@dataclass
class SellAnalysis:
    """銘柄の総合売り判定。"""
    code: str
    name: str
    entry_date: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    eval_date: pd.Timestamp
    current_price: float
    current_high: float
    current_low: float
    days_held: int  # 営業日数
    signals: List[SellSignal] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def pct_change(self) -> float:
        """エントリーからの現在の損益（%）。"""
        if self.entry_price <= 0:
            return 0.0
        return (self.current_price - self.entry_price) / self.entry_price * 100

    @property
    def recommendation(self) -> str:
        """総合的な推奨度を返す。"""
        if any(s.severity == "URGENT" for s in self.signals):
            return "🔴 即時損切"
        urgent_count = sum(1 for s in self.signals if s.severity in ("STRONG", "URGENT"))
        moderate_count = sum(1 for s in self.signals if s.severity == "MODERATE")
        if urgent_count >= 2 or (urgent_count >= 1 and moderate_count >= 1):
            return "🟠 強い売り推奨"
        elif urgent_count >= 1 or moderate_count >= 2:
            return "🟡 売り検討"
        elif moderate_count >= 1 or self.signals:
            return "🟢 様子見継続（兆候あり）"
        else:
            return "✅ 様子見継続（兆候なし）"

    @property
    def has_immediate_sell(self) -> bool:
        return any(s.severity == "URGENT" for s in self.signals)


def evaluate_sell_signals(
    daily_df: pd.DataFrame,
    code: str,
    name: str,
    entry_date: date_cls,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    eval_date: Optional[date_cls] = None,
) -> Optional[SellAnalysis]:
    """指定銘柄のエントリー後の売りシグナルを判定。

    Args:
        daily_df: 全銘柄の日足DataFrame（Code列でフィルタする）
        code: 5桁の銘柄コード
        name: 銘柄名
        entry_date: エントリー日
        entry_price: エントリー価格
        stop_loss: 損切ライン（逆指値）
        take_profit: 利確目標
        eval_date: 評価日（None なら最新営業日）
    """
    code_str = str(code).strip()
    sub = daily_df[daily_df["Code"].astype(str) == code_str].sort_values("Date").copy()
    if sub.empty:
        return None

    # 評価日設定
    entry_ts = pd.Timestamp(entry_date)
    eval_ts = pd.Timestamp(eval_date) if eval_date else sub["Date"].max()

    sub["Date"] = pd.to_datetime(sub["Date"])
    sub_until_eval = sub[sub["Date"] <= eval_ts]
    if sub_until_eval.empty:
        return None

    enriched = enrich_one(sub_until_eval)
    if enriched.empty or len(enriched) < 60:
        return None

    latest = enriched.iloc[-1]
    close = float(latest["AdjC"])
    high = float(latest["AdjH"])
    low = float(latest["AdjL"])
    ma5 = latest.get("MA5")

    # 営業日数の算出
    days_held_df = enriched[enriched["Date"] > entry_ts]
    days_held = len(days_held_df)

    signals: List[SellSignal] = []

    # === C5: 損切ライン到達（最優先） ===
    if stop_loss > 0 and low <= stop_loss:
        signals.append(SellSignal(
            "C5_StopLoss", "損切ライン到達（即時損切）",
            f"安値 {low:.0f}円 が損切ライン {stop_loss:.0f}円 を割り込んだ。逆指値で自動執行",
            "URGENT",
            "5時限目02④ p.170-176",
        ))

    # === C6: 利確目標到達 ===
    if take_profit > 0 and high >= take_profit:
        signals.append(SellSignal(
            "C6_TakeProfit", "利確目標到達",
            f"高値 {high:.0f}円 が利確目標 {take_profit:.0f}円 に到達。RR比達成",
            "STRONG",
            "5時限目01② p.162-167",
        ))

    # === C1: 過去高値到達 ===
    # 過去20日/60日/250日の高値（エントリー以前）に到達したか
    sub_before_entry = enriched[enriched["Date"] < entry_ts]
    if not sub_before_entry.empty:
        if len(sub_before_entry) >= 20:
            high_20d = sub_before_entry["AdjH"].tail(20).max()
            if high >= high_20d:
                signals.append(SellSignal(
                    "C1_HighReached_20d", "過去20日高値到達",
                    f"高値 {high:.0f}円 がエントリー前20日高値 {high_20d:.0f}円 に到達",
                    "MODERATE",
                    "5時限目01② p.162-167",
                ))
        if len(sub_before_entry) >= 60:
            high_60d = sub_before_entry["AdjH"].tail(60).max()
            if high >= high_60d:
                signals.append(SellSignal(
                    "C1_HighReached_60d", "過去60日高値到達",
                    f"高値 {high:.0f}円 がエントリー前60日高値 {high_60d:.0f}円 に到達（強い抵抗線）",
                    "STRONG",
                    "5時限目01② p.162-167",
                ))
        if len(sub_before_entry) >= 250:
            high_250d = sub_before_entry["AdjH"].tail(250).max()
            if high >= high_250d:
                signals.append(SellSignal(
                    "C1_HighReached_1y", "過去1年高値到達",
                    f"高値 {high:.0f}円 がエントリー前1年高値 {high_250d:.0f}円 に到達（年高値ブレイク）",
                    "STRONG",
                    "5時限目01② p.162-167 / 4時限目03 p.144",
                ))

    # === C2: 上昇日数 7-9日 ===
    if 7 <= days_held <= 9:
        signals.append(SellSignal(
            "C2_HoldPeriod_7to9", f"上昇 {days_held}日目（短期利確時期）",
            f"エントリーから{days_held}営業日経過。短期トレーダーが利確する時期で売り圧力増す",
            "MODERATE",
            "5時限目01② p.162-167",
        ))
    elif days_held > 9:
        signals.append(SellSignal(
            "C2_HoldPeriod_overweight", f"上昇 {days_held}日目（持ちすぎ警戒）",
            f"エントリーから{days_held}営業日経過。9日超は持ちすぎ気味、利確検討タイミング過ぎ",
            "STRONG",
            "5時限目01② p.162-167",
        ))

    # === C3: 5MA陰線割れ ===
    if ma5 is not None and not pd.isna(ma5):
        latest_close = float(latest["AdjC"])
        latest_open = float(latest["AdjO"])
        is_bearish = latest_close < latest_open
        below_ma5 = latest_close < ma5
        if is_bearish and below_ma5:
            signals.append(SellSignal(
                "C3_MA5_Break", "5MA陰線割れ",
                f"終値 {latest_close:.0f} が5MA {ma5:.0f} を陰線で割り込んだ。短期トレンド崩れ",
                "STRONG",
                "5時限目01③ p.162-167",
            ))

    # === C4: 弱いローソク足出現 ===
    tail3 = enriched.tail(3)
    if _has_engulfing_bearish(tail3):
        signals.append(SellSignal(
            "C4_Engulfing_Bearish", "包み足出現",
            "前日陽線を完全に包む大陰線が出現。買い圧力後退の警告",
            "MODERATE",
            "5時限目01④ p.167-168",
        ))
    if _has_evening_star(tail3):
        signals.append(SellSignal(
            "C4_Evening_Star", "宵の明星出現",
            "陽線→小コマ→陰線の組み合わせ。天井圏の反転シグナル",
            "MODERATE",
            "5時限目01④ p.167-168",
        ))

    return SellAnalysis(
        code=code_str,
        name=name,
        entry_date=entry_ts,
        entry_price=float(entry_price),
        stop_loss=float(stop_loss),
        take_profit=float(take_profit),
        eval_date=eval_ts,
        current_price=close,
        current_high=high,
        current_low=low,
        days_held=days_held,
        signals=signals,
    )
