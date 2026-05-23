"""Phase 3: 買いパターン該当判定（4時限目、V2カラム名対応）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

import config
from .environment import EnvironmentResult


@dataclass
class PatternMatch:
    pattern_id: str
    label: str
    description: str
    book_reference: str
    score: float


@dataclass
class PatternResult:
    matches: List[PatternMatch] = field(default_factory=list)
    bonus: List[PatternMatch] = field(default_factory=list)
    penalties: List[PatternMatch] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        return (
            sum(m.score for m in self.matches)
            + sum(b.score for b in self.bonus)
            - sum(p.score for p in self.penalties)
        )


def _trend_duration_days(df: pd.DataFrame) -> int:
    above = df["AdjC"] > df["MA20"]
    if above.empty:
        return 0
    if (~above).any():
        # 直近で False になった位置
        flipped = (~above)[::-1].idxmax()
        pos = above.index.get_loc(flipped)
        return len(above) - pos - 1
    return len(above)


def evaluate(df: pd.DataFrame, env: EnvironmentResult) -> PatternResult:
    result = PatternResult()
    if df.empty or len(df) < config.LONG_MA:
        return result

    latest = df.iloc[-1]
    close = latest["AdjC"]
    ma5 = latest.get("MA5")
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")

    # パターン①: 底値ボックスから上昇転換
    # 3年10,426件バックテストで勝率52.0%（ベース52.8%）と平均並み → 復活させて +15点
    # （12か月では44.4%だったが、上昇相場で逆機能していただけ。下落後反発期で機能）
    if env.label == "UPTREND" and ma60 is not None and not pd.isna(ma60):
        if len(df) >= 90:
            prior = df.iloc[-90:-30]
            if not prior.empty:
                prior_range = (prior["AdjH"].max() - prior["AdjL"].min())
                prior_avg = prior["AdjC"].mean()
                if prior_avg and prior_range / prior_avg < 0.10:
                    recent = df.tail(10)
                    if (recent["AdjC"] > prior["AdjH"].max()).any():
                        result.matches.append(PatternMatch(
                            "P1", "底値ボックス→上昇転換",
                            "下落終盤の底値ボックスを上抜け、上昇相場への転換初動",
                            "4時限目02 p.128-129 / 5時限目03 / 6時限目04",
                            # 3年実証 2026-05-23: 96件、勝率52.1%、+0.15%（ベース52.4%並み）→ +15から+5に減額
                            score=5.0,
                        ))

    # パターン②: ボックス上限ブレイクアウト
    if env.label in ("BOX", "UPTREND"):
        window = df.tail(60)
        if not window.empty and len(window) > 5:
            box_high = window["AdjH"].iloc[:-5].max()
            if not pd.isna(box_high) and close > box_high:
                if (df["AdjC"].tail(5) > box_high).any():
                    result.matches.append(PatternMatch(
                        "P2", "ボックス上限ブレイクアウト",
                        "ボックス相場の上限（過去60日高値）を抜けた",
                        "4時限目03 p.144 / 1時限目05",
                        # 3年実証 2026-05-23: 2480件、勝率52.3%、+0.55%（ベース並み）→ +30から+25に微減
                        score=25.0,
                    ))

    # パターン③: 上昇相場中の押し目→再上昇
    if env.label == "UPTREND" and ma5 is not None and ma20 is not None:
        # 直近15日でMA20付近にタッチした押し目があり、その後5MAを上抜けたパターン
        last15 = df.tail(15)
        touched_ma20 = (last15["AdjL"] <= last15["MA20"] * 1.015).any()  # 1.5%まで許容
        # 5MA上抜けを直近3日内に広げる（1日ピンポイントではなく）
        last3 = df.tail(4)
        crossed_up = False
        for i in range(1, len(last3)):
            prev_c = last3["AdjC"].iloc[i - 1]
            prev_m = last3["MA5"].iloc[i - 1]
            cur_c = last3["AdjC"].iloc[i]
            cur_m = last3["MA5"].iloc[i]
            if pd.notna(prev_m) and pd.notna(cur_m) and prev_c < prev_m and cur_c > cur_m:
                crossed_up = True
                break
        # または、株価が5MA上に出て継続上昇中
        on_top_of_ma5 = close > ma5 and df["AdjC"].iloc[-2] > df["MA5"].iloc[-2]
        if touched_ma20 and (crossed_up or on_top_of_ma5):
            result.matches.append(PatternMatch(
                "P3", "上昇相場中の押し目買い",
                "20MAタッチ後、5MAを上抜けして再上昇している押し目買いポイント",
                "4時限目02③ p.137-139",
                score=40.0,
            ))

    # 加点: 新高値ブレイク後の戻し
    if len(df) >= 250 and env.label == "UPTREND":
        rolling_high = df["AdjH"].rolling(250).max()
        breached_recently = (df["AdjC"].tail(15) >= rolling_high.tail(15) * 0.999).any()
        if breached_recently and ma5 is not None and close >= ma5:
            result.bonus.append(PatternMatch(
                "B1", "新高値ブレイク後の戻し→再上昇",
                "1年高値ブレイク確認、サポート化した位置で再上昇兆候",
                "4時限目03 p.144",
                # 3年実証 2026-05-23: 630件、勝率53.2%、+0.76%（ベース+0.8pt）→ +15から+10に減額
                score=10.0,
            ))

    # 加点: 三役好転
    senkou_a = latest.get("Ichimoku_SenkouA")
    senkou_b = latest.get("Ichimoku_SenkouB")
    tenkan = latest.get("Ichimoku_Tenkan")
    kijun = latest.get("Ichimoku_Kijun")
    if all(pd.notna(x) for x in (senkou_a, senkou_b, tenkan, kijun)):
        cloud_top = max(senkou_a, senkou_b)
        if close > cloud_top and tenkan > kijun:
            result.bonus.append(PatternMatch(
                "B2", "三役好転",
                "雲の上+転換線>基準線（強い買いパターン）",
                "3時限目06 p.95-97",
                # 3年実証 2026-05-23: 5394件、勝率52.4%、+0.69%（候補の51%にベース並みで加点=底上げ）→ +10から+5に減額
                score=5.0,
            ))

    # ============================================================
    # B3 系列: パーフェクトオーダー（3年9,923件の完成イベント実証分析に基づく再設計）
    #
    # 旧B3「形成直後 +12点」は、書籍の「完成直後は高値づかみリスク」の警告を踏まえ
    # データ分析（2026-05-23、3年実証）で以下が判明したため再設計:
    #
    #   - PO完成日 (素): 勝率53.7% +0.72%
    #   - PO完成 + RSI<70 + 出来高1.2x: 勝率58.9% +1.66% ← B3-Quality
    #   - PO完成 + RSI>=70 (過熱):     勝率48.8% +0.12% ← B3-Caution（減点）
    #   - 中期GC達成 + 60MA未上向き + 40<RSI<70 + 出来高1.2x: 勝率60.4% +1.78% ← B3-Anticipate
    # ============================================================
    ma60_slope_negative = env.ma60_slope is not None and not pd.isna(env.ma60_slope) and env.ma60_slope < 0
    vol_ratio_avg = latest.get("Vol_Ratio20_avg20")
    rsi_today = latest.get(f"RSI{config.RSI_PERIOD}")

    is_perfect_order = env.perfect_order
    has_volume_surge = (
        vol_ratio_avg is not None and not pd.isna(vol_ratio_avg)
        and vol_ratio_avg > 1.2
    )
    rsi_in_safe_zone = (
        rsi_today is not None and not pd.isna(rsi_today)
        and rsi_today < config.RSI_OVERBOUGHT
    )
    rsi_in_premium_zone = (
        rsi_today is not None and not pd.isna(rsi_today)
        and 40 <= rsi_today < config.RSI_OVERBOUGHT
    )
    rsi_overheated = (
        rsi_today is not None and not pd.isna(rsi_today)
        and rsi_today >= config.RSI_OVERBOUGHT
    )

    # PO完成「直後」判定（直近20日以内に揃った）— 旧B3と同じロジック
    po_recently_formed = False
    if is_perfect_order and len(df) > 20:
        po_recently_formed = not (
            df["MA5"].shift(20).iloc[-1] > df["MA20"].shift(20).iloc[-1] > df["MA60"].shift(20).iloc[-1]
        )

    # ---------- B3-Anticipate v3: 60MA"転換"初動型 (+15) ----------
    # v2 (slope<0.5% 単発) は勝率55% で目標未達。
    # v3 で決定的な改善: 「10日前は下向きだった」を必須化することで「単なる横ばい」と
    # 「下から横へ転換中」を区別。実証勝率 58.3%、平均 +1.43% (3年・206件)。
    # 書籍4時限目02⑤「60日MAは上向きに転換する初動、上昇トレンドへの入り口で使う」を体現。
    ma5 = latest.get("MA5")
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")

    # 60MA の「転換」判定: 直近5日間 slope < 0.5% かつ 10日前 5日間 slope < -0.3%
    ma60_in_transition = False
    if pd.notna(ma60) and len(df) >= 16:
        try:
            ma60_now = df["MA60"].iloc[-1]
            ma60_5d = df["MA60"].iloc[-6]    # 5日前
            ma60_10d = df["MA60"].iloc[-11]  # 10日前
            ma60_15d = df["MA60"].iloc[-16]  # 15日前
            if all(pd.notna(x) and x > 0 for x in (ma60_now, ma60_5d, ma60_10d, ma60_15d)):
                slope_now = (ma60_now / ma60_5d) - 1
                slope_10d_ago = (ma60_5d / ma60_15d) - 1
                ma60_in_transition = (slope_now < 0.005) and (slope_10d_ago < -0.003)
        except (IndexError, KeyError):
            ma60_in_transition = False

    if (
        pd.notna(ma5) and pd.notna(ma20) and pd.notna(ma60)
        and ma5 > ma20 > ma60                  # 5MA>20MA>60MA stacked
        and env.ma20_slope is not None and env.ma20_slope > 0  # 20MA 上向き
        and ma60_in_transition                  # 60MA が下から横へ「転換中」
        and has_volume_surge                    # 出来高傾向 1.2倍超
        and rsi_in_premium_zone                 # 40<=RSI<70
    ):
        result.bonus.append(PatternMatch(
            "B3_Anticipate", "パーフェクトオーダー形成初動（60MA下→横転換）",
            "5MA>20MA>60MA達成 + 60MAが下向きから横向きへ転換中 + 出来高傾向1.2倍超 + RSI 40-70（実証勝率58.3%）",
            "4時限目02⑤ p.148 「60MA上向き転換初動が上昇トレンド入口」/ カスタム版実証分析v3 2026-05-23",
            score=15.0,
        ))
    # ---------- B3-Quality: 形成直後型 強化版 (+12) ----------
    # 既存B3と同じ「完成直後」だが、出来高傾向とRSI適温の条件を必須化。
    # B3_Anticipate と排他: 60MA が既に強く上向いている場合のみこちらが発火。
    elif po_recently_formed and has_volume_surge and rsi_in_safe_zone:
        result.bonus.append(PatternMatch(
            "B3_Quality", "パーフェクトオーダー形成直後（質確認済）",
            "直近20日以内に5MA>20MA>60MAが揃い、出来高傾向1.2倍超かつRSI<70（実証勝率58.9%）",
            "4時限目02⑤ p.148 / カスタム版実証分析 2026-05-23",
            score=12.0,
        ))

    # ---------- B3-Caution: 形成直後 + 過熱 (-5) ----------
    # PO完成しているがRSI過買い圏 → 高値づかみリスク（実証勝率48.8%・ベース53.7%から-4.9pt）
    if po_recently_formed and rsi_overheated:
        result.penalties.append(PatternMatch(
            "B3_Caution", "パーフェクトオーダー完成 + 過買い圏",
            f"PO完成済だがRSI {rsi_today:.0f} で過買い圏。高値づかみ警戒（実証勝率48.8%）",
            "4時限目02⑤ / カスタム版実証分析 2026-05-23",
            score=5.0,
        ))

    # 減点: トレンド成熟
    duration = _trend_duration_days(df)
    if duration > config.TREND_MAX_DAYS:
        result.penalties.append(PatternMatch(
            "N1", "トレンド成熟",
            f"株価が20MAの上に滞在 {duration}営業日（6か月超）、転換警戒",
            "5時限目01② 日柄分析 / 3時限目05 p.91",
            score=15.0,
        ))
    elif duration > config.TREND_MIN_DAYS:
        # 3年バックテストで勝率44.4%（ベース52.4%から-8.0pt）と明確に弱い
        # 2026-05-22: -5 → -10 に強化済
        # 2026-05-23: 最新3年データで -10 → -15 にさらに強化
        result.penalties.append(PatternMatch(
            "N2", "トレンド中盤",
            f"株価が20MAの上に滞在 {duration}営業日（3か月超）、警戒気味",
            "5時限目01②",
            score=15.0,
        ))

    # 戻り上昇兆候のローソク足パターン (旧N3「弱いローソク足出現」)
    # 3年10,545件バックテストで勝率61.7%、平均+2.45%（ベース52.5%から+9.2pt）と判明 → 加点B4に転換
    # 本書5時限目01④では「弱い売りシグナル」とされるが、AIスクリーニング後の銘柄（買いトリガー+パターン
    # マッチ済み）では「いったん下げて反発する直前」の予兆として機能している。
    if _has_engulfing_bearish(df.tail(3)) or _has_evening_star(df.tail(3)):
        result.bonus.append(PatternMatch(
            "B4", "戻り上昇兆候のローソク足",
            "包み足/否定陰線/宵の明星出現（3年データで勝率60.9%、+2.29%の逆指標として加点）",
            "5時限目01④ p.167-168（本書記述は減点だがAIではデータ的に加点）",
            # 3年実証 2026-05-23: 448件、勝率60.9%、+2.29%（ベース+8.5pt、最強の加点要素）→ +10から+12に強化
            score=12.0,
        ))

    # ============================================================
    # 【B6】ボリンジャーバンド スクイーズ→エクスパンション (+10)【2026-05-23 新規】
    # 「ボラ低下→拡張」のトレンド誕生シグナル
    # 3年実証: 4,410件、勝率56.4%、+1.24% (ベース+2.3pt、件数7.0%)
    # 書籍3時限目07 p.98-99 のボリンジャーバンド理論を実装
    # ============================================================
    bb_squeeze_to_expansion = latest.get("BB_SqueezeToExpansion")
    if bb_squeeze_to_expansion is not None and not pd.isna(bb_squeeze_to_expansion) and bool(bb_squeeze_to_expansion):
        result.bonus.append(PatternMatch(
            "B6_BB_TrendBirth", "ボリンジャー スクイーズ→エクスパンション",
            "ボラ低下からの拡張（トレンド誕生シグナル）",
            "3時限目07 p.98-99 / カスタム版実証3年: 勝率56.4%・+1.24% (ベース+2.3pt)",
            score=10.0,
        ))

    # ============================================================
    # 【N5】+2σ超過熱ペナルティ (-5)【2026-05-23 新規】
    # 価格が +2σ より上にある = 急騰しすぎ = 新規買いとして弱い
    # 3年実証: 4,356件、勝率49.9%、+0.43% (ベース-4.2pt、件数6.9%)
    # ============================================================
    bb_up2 = latest.get("BB_UP2")
    if bb_up2 is not None and not pd.isna(bb_up2) and close > bb_up2:
        result.penalties.append(PatternMatch(
            "N5_BB_Overheated", "ボリンジャー +2σ超（過熱）",
            f"終値{close:.0f}が+2σ({bb_up2:.0f})を超え、急騰しすぎで新規買いには遅い",
            "3時限目07 p.98-99 / カスタム版実証3年: 勝率49.9%・+0.43% (ベース-4.2pt)",
            score=5.0,
        ))

    # 減点: MAからの上方乖離
    # 3年10,426件バックテストに基づく再調整（2026-05-22）:
    #   20%超     : 勝率36.3%, 平均-1.39% → screener.py で**ハード除外**
    #   15-20%乖離: 勝率49.7%, 平均+0.24% → -10点
    #   10-15%乖離: 勝率46.9%, 平均+0.76% → -10点（ベースから-5.9pt）
    if env.price_vs_ma20 > 0.20:
        # 注: ここで20%超を検出して表示するが、screener.py側でハード除外される
        result.penalties.append(PatternMatch(
            "N4_severe", "MAから極端な上方乖離（除外対象）",
            f"株価が20MAより{env.price_vs_ma20:.1%}上方、天井圏（3年勝率36.3%で除外）",
            "2時限目02 p.71-72 / グランビル④",
            score=30.0,
        ))
    elif env.price_vs_ma20 > 0.15:
        result.penalties.append(PatternMatch(
            "N4_high", "MAから大きく上方乖離",
            f"株価が20MAより{env.price_vs_ma20:.1%}上方、グランビル④の警戒",
            "2時限目02 p.71-72",
            score=10.0,
        ))
    elif env.price_vs_ma20 > 0.10:
        result.penalties.append(PatternMatch(
            "N4", "MAから上方乖離",
            f"株価が20MAより{env.price_vs_ma20:.1%}上方、グランビル④の警戒",
            "2時限目02 p.71-72",
            score=10.0,
        ))

    return result


def _has_engulfing_bearish(df: pd.DataFrame) -> bool:
    """陽線→大陰線で前日陽線を完全に包む"""
    if len(df) < 2:
        return False
    p, c = df.iloc[-2], df.iloc[-1]
    if p["AdjC"] <= p["AdjO"]:
        return False
    if c["AdjC"] >= c["AdjO"]:
        return False
    return c["AdjO"] >= p["AdjC"] and c["AdjC"] <= p["AdjO"]


def _has_evening_star(df: pd.DataFrame) -> bool:
    """宵の明星"""
    if len(df) < 3:
        return False
    a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if a["AdjC"] <= a["AdjO"]:
        return False
    body_b = abs(b["AdjC"] - b["AdjO"])
    range_b = b["AdjH"] - b["AdjL"]
    if range_b == 0 or body_b / range_b > 0.3:
        return False
    if c["AdjC"] >= c["AdjO"]:
        return False
    midpoint_a = (a["AdjO"] + a["AdjC"]) / 2
    return c["AdjC"] < midpoint_a
