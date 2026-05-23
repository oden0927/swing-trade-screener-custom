"""バックテスト。

過去日付時点でスクリーニングを実行し、検出された候補の N日後の実勝率を集計する。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
from tqdm import tqdm

import config
from . import data_fetcher
from .screener import Candidate, screen_at

logger = logging.getLogger(__name__)


@dataclass
class BacktestRow:
    date: pd.Timestamp
    code: str
    display_code: str
    name: str
    score: float
    patterns: List[str]
    bonuses: List[str]
    penalties: List[str]
    triggers: List[str]
    environment: str
    price_vs_ma20: float
    entry: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    risk_pct: float
    # カスタム版追加：モメンタム指標スナップショット
    rsi: float = float("nan")
    macd: float = float("nan")
    macd_signal: float = float("nan")
    macd_hist: float = float("nan")
    # 上位足→下位足分析（2026-05-23 追加）
    tf_monthly: str = "—"
    tf_weekly: str = "—"
    tf_daily: str = "—"
    tf_alignment: str = "—"
    returns: dict = field(default_factory=dict)
    hit_take_profit: dict = field(default_factory=dict)
    hit_stop_loss: dict = field(default_factory=dict)


def _forward_returns(
    daily_groups: pd.api.typing.DataFrameGroupBy,
    code: str,
    eval_date: pd.Timestamp,
    entry: float,
    stop_loss: float,
    take_profit: float,
    holding_days_list: List[int],
) -> tuple[dict, dict, dict]:
    """指定銘柄について各保有日数後のリターンを計算。

    Returns:
        returns: {hold: pct_return}
        hit_tp: {hold: 1 if hit TP within hold, else 0}
        hit_sl: {hold: 1 if hit SL within hold, else 0}
    """
    if code not in daily_groups.groups:
        return {}, {}, {}
    sub = daily_groups.get_group(code).sort_values("Date")
    future = sub[sub["Date"] > eval_date].head(max(holding_days_list))
    if future.empty:
        return {}, {}, {}

    returns = {}
    hit_tp = {}
    hit_sl = {}
    for hold in holding_days_list:
        if len(future) < hold:
            continue
        slice_ = future.head(hold)
        # 終値リターン (hold 日後)
        future_close = slice_["AdjC"].iloc[-1]
        returns[hold] = (future_close - entry) / entry if entry else 0.0
        # 期間内に TP/SL に到達したか
        hit_tp[hold] = int((slice_["AdjH"] >= take_profit).any()) if take_profit > 0 else 0
        hit_sl[hold] = int((slice_["AdjL"] <= stop_loss).any()) if stop_loss > 0 else 0
    return returns, hit_tp, hit_sl


def run_backtest(
    months_back: int = 6,
    sample_interval_days: int = 10,
    holding_days_list: Optional[List[int]] = None,
) -> pd.DataFrame:
    """過去 N か月分、X日ごとにスクリーニングを実行し、forward returns を集計。

    Args:
        months_back: 何か月過去まで検証するか
        sample_interval_days: 何営業日おきにサンプリングするか
        holding_days_list: 保有日数の評価ポイント (5, 10, 20など)
    """
    if holding_days_list is None:
        holding_days_list = [5, 10, 20]

    logger.info("バックテスト開始: 過去%dか月、%d日おき、保有=%s日", months_back, sample_interval_days, holding_days_list)

    # データを一度だけロード
    master = data_fetcher.load_master()
    daily = data_fetcher.load_daily()
    financials = data_fetcher.load_financials()
    announcements = data_fetcher.load_announcements()
    topix = data_fetcher.load_topix()

    if daily.empty:
        raise RuntimeError("日足データが空です。先に main.py fetch を実行してください。")

    # サンプル日付（取引日のみ）
    end_date = daily["Date"].max()
    start_date = end_date - timedelta(days=months_back * 30)
    # ただし、保有日数分先のデータが必要なので、末尾は除外
    cutoff_end = end_date - timedelta(days=max(holding_days_list) * 1.5)
    trading_dates = sorted(daily["Date"].unique())
    trading_dates = [d for d in trading_dates if start_date <= d <= cutoff_end]
    # 間引き
    sample_dates = trading_dates[::sample_interval_days]
    logger.info("サンプル日数: %d 日", len(sample_dates))

    daily_groups = daily.groupby("Code", sort=False)

    rows: List[BacktestRow] = []
    for d in tqdm(sample_dates, desc="バックテスト"):
        try:
            candidates = screen_at(
                cutoff_date=d,
                master=master,
                daily=daily,
                financials=financials,
                announcements=announcements,
                topix=topix,
                show_progress=False,
                max_candidates=None,  # バックテストでは全候補を統計対象に（上限なし）
            )
        except Exception as exc:
            logger.warning("%s: スクリーニング失敗 %s", d, exc)
            continue

        for c in candidates:
            ret, hit_tp, hit_sl = _forward_returns(
                daily_groups,
                c.code,
                d,
                c.risk_reward.entry,
                c.risk_reward.stop_loss,
                c.risk_reward.take_profit,
                holding_days_list,
            )
            rows.append(BacktestRow(
                date=d,
                code=c.code,
                display_code=c.display_code,
                name=c.name,
                score=c.score,
                patterns=[m.label for m in c.pattern.matches],
                bonuses=[b.label for b in c.pattern.bonus],
                penalties=[p.label for p in c.pattern.penalties],
                triggers=[t.signal_type for t in c.triggers],
                environment=c.environment.label,
                price_vs_ma20=c.environment.price_vs_ma20,
                entry=c.risk_reward.entry,
                stop_loss=c.risk_reward.stop_loss,
                take_profit=c.risk_reward.take_profit,
                rr_ratio=c.risk_reward.rr_ratio,
                risk_pct=c.risk_reward.risk_pct,
                rsi=c.momentum.get("rsi", float("nan")),
                macd=c.momentum.get("macd", float("nan")),
                macd_signal=c.momentum.get("macd_signal", float("nan")),
                macd_hist=c.momentum.get("macd_hist", float("nan")),
                tf_monthly=c.multi_timeframe.get("monthly", "—"),
                tf_weekly=c.multi_timeframe.get("weekly", "—"),
                tf_daily=c.multi_timeframe.get("daily", "—"),
                tf_alignment=c.multi_timeframe.get("alignment", "—"),
                returns=ret,
                hit_take_profit=hit_tp,
                hit_stop_loss=hit_sl,
            ))

    # DataFrame に変換
    records = []
    for r in rows:
        rec = {
            "date": r.date,
            "code": r.display_code,
            "name": r.name,
            "score": r.score,
            "environment": r.environment,
            "price_vs_ma20": r.price_vs_ma20,
            "patterns": ", ".join(r.patterns),
            "bonuses": ", ".join(r.bonuses),
            "penalties": ", ".join(r.penalties),
            "triggers": ", ".join(r.triggers),
            "entry": r.entry,
            "stop_loss": r.stop_loss,
            "take_profit": r.take_profit,
            "rr_ratio": r.rr_ratio,
            "risk_pct": r.risk_pct,
            "rsi": r.rsi,
            "macd": r.macd,
            "macd_signal": r.macd_signal,
            "macd_hist": r.macd_hist,
            "tf_monthly": r.tf_monthly,
            "tf_weekly": r.tf_weekly,
            "tf_daily": r.tf_daily,
            "tf_alignment": r.tf_alignment,
        }
        for h in holding_days_list:
            rec[f"return_{h}d"] = r.returns.get(h)
            rec[f"hit_tp_{h}d"] = r.hit_take_profit.get(h)
            rec[f"hit_sl_{h}d"] = r.hit_stop_loss.get(h)
        records.append(rec)
    df = pd.DataFrame(records)
    return df


def summarize(df: pd.DataFrame, holding_days_list: List[int]) -> str:
    """バックテスト結果を集計してテキストで返す。"""
    if df.empty:
        return "バックテスト結果は空です。"

    lines = []
    lines.append("=" * 70)
    lines.append(f"バックテスト集計（{datetime.now().strftime('%Y-%m-%d %H:%M')}）")
    lines.append(f"検出シグナル件数: {len(df)} 件")
    lines.append(f"対象期間: {df['date'].min().date()} 〜 {df['date'].max().date()}")
    lines.append("=" * 70)

    # 保有日数ごとの集計
    for h in holding_days_list:
        col = f"return_{h}d"
        if col not in df.columns or df[col].dropna().empty:
            continue
        sub = df.dropna(subset=[col])
        wins = (sub[col] > 0).sum()
        losses = (sub[col] < 0).sum()
        flat = (sub[col] == 0).sum()
        avg = sub[col].mean() * 100
        median = sub[col].median() * 100
        max_ret = sub[col].max() * 100
        min_ret = sub[col].min() * 100
        win_rate = wins / max(1, len(sub)) * 100
        tp_hit_rate = sub[f"hit_tp_{h}d"].mean() * 100 if f"hit_tp_{h}d" in sub.columns else 0
        sl_hit_rate = sub[f"hit_sl_{h}d"].mean() * 100 if f"hit_sl_{h}d" in sub.columns else 0
        lines.append(f"\n【保有 {h} 営業日】")
        lines.append(f"  検証件数: {len(sub)} 件")
        lines.append(f"  勝率: {win_rate:.1f}%  (勝ち {wins} / 負け {losses} / 引分 {flat})")
        lines.append(f"  平均リターン: {avg:+.2f}%   中央値: {median:+.2f}%")
        lines.append(f"  最大上昇: {max_ret:+.2f}%   最大下落: {min_ret:+.2f}%")
        lines.append(f"  利確到達率: {tp_hit_rate:.1f}%   損切到達率: {sl_hit_rate:.1f}%")
        # 期待値
        avg_win = sub[sub[col] > 0][col].mean() * 100 if wins else 0
        avg_loss = sub[sub[col] < 0][col].mean() * 100 if losses else 0
        if wins or losses:
            ev = win_rate / 100 * avg_win + (1 - win_rate / 100) * avg_loss
            lines.append(f"  平均利益: {avg_win:+.2f}%   平均損失: {avg_loss:+.2f}%   期待値: {ev:+.2f}%")

    # トリガー別の勝率
    lines.append("\n" + "=" * 70)
    lines.append("【トリガー別の勝率（保有10営業日）】")
    lines.append("=" * 70)
    col = "return_10d"
    if col in df.columns:
        for trigger_kw in ("MA5_BREAK", "SUPPORT_BOUNCE", "NEW_HIGH_REENTRY"):
            sub = df[df["triggers"].str.contains(trigger_kw, na=False)].dropna(subset=[col])
            if sub.empty:
                continue
            wins = (sub[col] > 0).sum()
            avg = sub[col].mean() * 100
            win_rate = wins / len(sub) * 100
            lines.append(f"  {trigger_kw}: {len(sub)} 件、勝率 {win_rate:.1f}%、平均 {avg:+.2f}%")

    # パターン別の勝率
    lines.append("\n" + "=" * 70)
    lines.append("【パターン別の勝率（保有10営業日）】")
    lines.append("=" * 70)
    if col in df.columns:
        for pattern_kw in ("底値ボックス→上昇転換", "ボックス上限ブレイクアウト", "上昇相場中の押し目買い"):
            sub = df[df["patterns"].str.contains(pattern_kw, na=False)].dropna(subset=[col])
            if sub.empty:
                continue
            wins = (sub[col] > 0).sum()
            avg = sub[col].mean() * 100
            win_rate = wins / len(sub) * 100
            lines.append(f"  {pattern_kw}: {len(sub)} 件、勝率 {win_rate:.1f}%、平均 {avg:+.2f}%")

    # スコア帯別の勝率
    lines.append("\n" + "=" * 70)
    lines.append("【スコア帯別の勝率（保有10営業日）】")
    lines.append("=" * 70)
    if col in df.columns:
        bins = [(0, 50), (50, 75), (75, 100), (100, 150), (150, 9999)]
        for low, high in bins:
            sub = df[(df["score"] >= low) & (df["score"] < high)].dropna(subset=[col])
            if sub.empty:
                continue
            wins = (sub[col] > 0).sum()
            avg = sub[col].mean() * 100
            win_rate = wins / len(sub) * 100
            lines.append(f"  スコア {low}-{high}: {len(sub)} 件、勝率 {win_rate:.1f}%、平均 {avg:+.2f}%")

    # スコア閾値別の累積勝率（そのスコア以上の銘柄だけ取引した場合）
    lines.append("\n" + "=" * 70)
    lines.append("【スコア閾値別の累積勝率（保有10営業日）】")
    lines.append("=" * 70)
    lines.append("\"そのスコア以上の銘柄だけ取引したら勝率はどうなるか\" の集計")
    lines.append("最低エントリー条件を決めるときの参考に")
    lines.append("")
    if col in df.columns:
        thresholds = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150]
        for th in thresholds:
            sub = df[df["score"] >= th].dropna(subset=[col])
            if len(sub) < 30:  # サンプル30件未満は統計信頼度低くて省略
                break
            wins = (sub[col] > 0).sum()
            avg = sub[col].mean() * 100
            wr = wins / len(sub) * 100
            median = sub[col].median() * 100
            # 期待値計算
            avg_win = sub[sub[col] > 0][col].mean() * 100 if wins else 0
            losses = (sub[col] < 0).sum()
            avg_loss = sub[sub[col] < 0][col].mean() * 100 if losses else 0
            ev = (wr / 100) * avg_win + ((100 - wr) / 100) * avg_loss
            lines.append(
                f"  スコア{th:>3}以上: {len(sub):>5}件、"
                f"勝率 {wr:5.1f}%、平均 {avg:+5.2f}%、中央値 {median:+5.2f}%、期待値 {ev:+5.2f}%"
            )

    # 減点別の勝率（N4 MA上方乖離の効果を検証）
    lines.append("\n" + "=" * 70)
    lines.append("【減点要素別の勝率（保有10営業日）】")
    lines.append("=" * 70)
    if col in df.columns and "penalties" in df.columns:
        # 減点なしの群
        no_pen = df[df["penalties"].fillna("") == ""].dropna(subset=[col])
        if not no_pen.empty:
            wins = (no_pen[col] > 0).sum()
            avg = no_pen[col].mean() * 100
            wr = wins / len(no_pen) * 100
            lines.append(f"  [減点なし]: {len(no_pen)} 件、勝率 {wr:.1f}%、平均 {avg:+.2f}%")
        # 各減点別
        penalty_keys = [
            "MAから極端な上方乖離",   # N4_severe (-25)
            "MAから大きく上方乖離",   # N4_high (-15)
            "MAから上方乖離",         # N4 (-10) ※ contains で他も含むので注意
            "トレンド成熟",           # N1
            "トレンド中盤",           # N2
            "弱いローソク足出現",     # N3
            "パーフェクトオーダー完成 + 過買い圏",  # B3_Caution
            # N5_BB_Overheated: 2026-05-24 撤回（実証で減点する価値なし53.0%）
        ]
        for key in penalty_keys:
            sub = df[df["penalties"].fillna("").str.contains(key, regex=False)].dropna(subset=[col])
            if sub.empty:
                continue
            wins = (sub[col] > 0).sum()
            avg = sub[col].mean() * 100
            wr = wins / len(sub) * 100
            lines.append(f"  {key}: {len(sub)} 件、勝率 {wr:.1f}%、平均 {avg:+.2f}%")

    # 20MA乖離率別の勝率（より細かい分析）
    lines.append("\n" + "=" * 70)
    lines.append("【20MA上方乖離率別の勝率（保有10営業日）】")
    lines.append("=" * 70)
    if col in df.columns and "price_vs_ma20" in df.columns:
        dev_bins = [
            (-1.0, 0.0, "乖離0%未満（20MA以下）"),
            (0.0, 0.05, "0〜5%"),
            (0.05, 0.10, "5〜10%"),
            (0.10, 0.15, "10〜15%"),
            (0.15, 0.20, "15〜20%"),
            (0.20, 10.0, "20%超"),
        ]
        for low, high, label in dev_bins:
            sub = df[(df["price_vs_ma20"] >= low) & (df["price_vs_ma20"] < high)].dropna(subset=[col])
            if sub.empty:
                continue
            wins = (sub[col] > 0).sum()
            avg = sub[col].mean() * 100
            wr = wins / len(sub) * 100
            lines.append(f"  {label}: {len(sub)} 件、勝率 {wr:.1f}%、平均 {avg:+.2f}%")

    # 加点要素別の勝率
    lines.append("\n" + "=" * 70)
    lines.append("【加点要素別の勝率（保有10営業日）】")
    lines.append("=" * 70)
    if col in df.columns and "bonuses" in df.columns:
        no_bonus = df[df["bonuses"].fillna("") == ""].dropna(subset=[col])
        if not no_bonus.empty:
            wins = (no_bonus[col] > 0).sum()
            avg = no_bonus[col].mean() * 100
            wr = wins / len(no_bonus) * 100
            lines.append(f"  [加点なし]: {len(no_bonus)} 件、勝率 {wr:.1f}%、平均 {avg:+.2f}%")
        for key in [
            "新高値ブレイク後の戻し→再上昇",      # B1 (+10)
            "三役好転",                           # B2 (+5)
            "パーフェクトオーダー形成初動",       # B3_Anticipate (+15) v3
            "パーフェクトオーダー形成直後（質確認済）",  # B3_Quality (+12)
            "戻り上昇兆候のローソク足",           # B4 (+12)
            "上位足→下位足 全足一致上昇",         # B5_AlignedUp (+15) [2026-05-23]
            # B6_BB_TrendBirth: 2026-05-24 撤回（実証で逆効果49.4%）
        ]:
            sub = df[df["bonuses"].fillna("").str.contains(key, regex=False)].dropna(subset=[col])
            if sub.empty:
                continue
            wins = (sub[col] > 0).sum()
            avg = sub[col].mean() * 100
            wr = wins / len(sub) * 100
            lines.append(f"  {key}: {len(sub)} 件、勝率 {wr:.1f}%、平均 {avg:+.2f}%")

    # =========================================================
    # 【カスタム版】モメンタム指標（RSI / MACD）フィルタ別の勝率
    # =========================================================
    # 参考文献:
    #   - 株の達人: RSI 20以下 → MACDゴールデンクロス
    #   - Fintokei: RSI 30以下 + MACDゴールデンクロス、RSI 50ライン+MACD 0ライン
    #   - ThreeTrader: MACDで方向、RSIでタイミング。基本=GC+RSI>50、応用=押し目40-50
    #   - Trade the Pool: シグナル確認とノイズ除去のための併用
    # スコア計算は不変。ここでは候補を後からフィルタしたときの勝率変化のみ計測。
    if col in df.columns and "rsi" in df.columns and "macd" in df.columns:
        lines.append("\n" + "=" * 70)
        lines.append("【モメンタムフィルタ別の勝率（保有10営業日）】")
        lines.append("=" * 70)
        lines.append("（スコア計算は無変更。候補を後からフィルタした場合の勝率変化）\n")

        sub_base = df.dropna(subset=[col]).dropna(subset=["rsi", "macd", "macd_signal"]).copy()
        n_base = len(sub_base)
        if n_base == 0:
            lines.append("  モメンタムデータを含む候補がありません（バックテストを再実行してください）")
        else:
            def _wr_stats(sub: pd.DataFrame, label: str) -> str:
                if sub.empty:
                    return f"  {label}: 0 件"
                wins = (sub[col] > 0).sum()
                losses = (sub[col] < 0).sum()
                avg = sub[col].mean() * 100
                wr = wins / len(sub) * 100
                med = sub[col].median() * 100
                avg_win = sub[sub[col] > 0][col].mean() * 100 if wins else 0
                avg_loss = sub[sub[col] < 0][col].mean() * 100 if losses else 0
                ev = (wr / 100) * avg_win + ((100 - wr) / 100) * avg_loss
                share = len(sub) / n_base * 100
                return (
                    f"  {label}: {len(sub):>5}件 ({share:4.1f}%), "
                    f"勝率 {wr:5.1f}%, 平均 {avg:+5.2f}%, 中央値 {med:+5.2f}%, 期待値 {ev:+5.2f}%"
                )

            lines.append("--- ベースライン ---")
            lines.append(_wr_stats(sub_base, "F0: フィルタなし（全候補）"))

            lines.append("\n--- 単独フィルタ ---")
            lines.append(_wr_stats(
                sub_base[sub_base["macd"] > sub_base["macd_signal"]],
                "F1: MACD>Signal（ゴールデンクロス状態）"
            ))
            lines.append(_wr_stats(
                sub_base[sub_base["macd"] > 0],
                "F2: MACD>0（ゼロライン上、強気フェーズ）"
            ))
            lines.append(_wr_stats(
                sub_base[sub_base["rsi"] > 50],
                "F3: RSI>50（強気バイアス）"
            ))
            lines.append(_wr_stats(
                sub_base[(sub_base["rsi"] > 40) & (sub_base["rsi"] < 70)],
                "F4: 40<RSI<70（適温ゾーン）"
            ))
            lines.append(_wr_stats(
                sub_base[sub_base["macd_hist"] > 0],
                "F7: ヒストグラム>0（短期モメンタム加速中）"
            ))

            lines.append("\n--- 組み合わせフィルタ ---")
            lines.append(_wr_stats(
                sub_base[(sub_base["macd"] > sub_base["macd_signal"]) & (sub_base["rsi"] > 50)],
                "F5: MACD>Signal AND RSI>50 （順張り基本）"
            ))
            lines.append(_wr_stats(
                sub_base[(sub_base["macd"] > 0) & (sub_base["rsi"] > 40) & (sub_base["rsi"] < 60)],
                "F6: MACD>0 AND 40<RSI<60 （押し目買いゾーン）"
            ))

            lines.append("\n--- 参考: 過熱・冷却域での挙動 ---")
            lines.append(_wr_stats(
                sub_base[sub_base["rsi"] >= 70],
                "RSI>=70（過買い圏）"
            ))
            lines.append(_wr_stats(
                sub_base[sub_base["rsi"] <= 30],
                "RSI<=30（過売り圏）"
            ))
            lines.append(_wr_stats(
                sub_base[sub_base["macd"] < sub_base["macd_signal"]],
                "MACD<Signal（デッドクロス状態）"
            ))
            lines.append(_wr_stats(
                sub_base[sub_base["macd"] < 0],
                "MACD<0（ゼロライン下、弱気フェーズ）"
            ))

            lines.append("\n--- RSI レンジ別の分解 ---")
            rsi_bins = [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 100)]
            for low, high in rsi_bins:
                seg = sub_base[(sub_base["rsi"] >= low) & (sub_base["rsi"] < high)]
                lines.append(_wr_stats(seg, f"RSI {low:>2}-{high:>2}"))

            lines.append("\n判定の目安:")
            lines.append(
                "  - F0 と比較して、フィルタ後の勝率と期待値が両方上がっていれば「足切り条件」として有効"
                "\n  - サンプル件数が極端に減るフィルタは過剰絞り込みの可能性あり（実運用での候補枯渇）"
                "\n  - 期待値プラス・件数も確保 のバランスが取れているものを採用候補に"
            )

    # =========================================================
    # 【カスタム版 2026-05-23】上位足→下位足アライメント別の勝率
    # =========================================================
    # 本書1時限目03 P49「上位足で方向感→下位足でトレード」の効果検証
    # スコア計算は不変。アライメント別の勝率変化を計測。
    if col in df.columns and "tf_alignment" in df.columns:
        lines.append("\n" + "=" * 70)
        lines.append("【上位足→下位足アライメント別の勝率（保有10営業日）】")
        lines.append("=" * 70)
        lines.append("（スコア計算は無変更。月足/週足/日足の方向一致度による勝率分布）")
        lines.append("（本書1時限目03 p.49「上位足で方向感→下位足でトレード」の効果検証）\n")

        sub_base = df.dropna(subset=[col]).copy()
        sub_base = sub_base[sub_base["tf_alignment"].notna() & (sub_base["tf_alignment"] != "—")]
        n_base = len(sub_base)
        if n_base == 0:
            lines.append("  上位足データを含む候補がありません（バックテストを再実行してください）")
        else:
            def _tf_stats(sub: pd.DataFrame, label: str) -> str:
                if sub.empty:
                    return f"  {label}: 0 件"
                wins = (sub[col] > 0).sum()
                losses = (sub[col] < 0).sum()
                avg = sub[col].mean() * 100
                wr = wins / len(sub) * 100
                med = sub[col].median() * 100
                avg_win = sub[sub[col] > 0][col].mean() * 100 if wins else 0
                avg_loss = sub[sub[col] < 0][col].mean() * 100 if losses else 0
                ev = (wr / 100) * avg_win + ((100 - wr) / 100) * avg_loss
                share = len(sub) / n_base * 100
                return (
                    f"  {label}: {len(sub):>5}件 ({share:4.1f}%), "
                    f"勝率 {wr:5.1f}%, 平均 {avg:+5.2f}%, 中央値 {med:+5.2f}%, 期待値 {ev:+5.2f}%"
                )

            lines.append("--- アライメント別 ---")
            for align in ["ALIGNED_UP", "PARTIAL_UP", "MIXED", "PARTIAL_DOWN", "ALIGNED_DOWN"]:
                sub = sub_base[sub_base["tf_alignment"] == align]
                label_jp = {
                    "ALIGNED_UP":   "🟢 全足一致(上昇)  月・週・日 全て上昇",
                    "PARTIAL_UP":   "🟢 概ね上昇         上昇2つ、残り中立",
                    "MIXED":        "⚪ 方向感バラバラ  上昇下落混在",
                    "PARTIAL_DOWN": "🔴 概ね下落         下落2つ、残り中立",
                    "ALIGNED_DOWN": "🔴 全足一致(下落)  月・週・日 全て下落",
                }[align]
                lines.append(_tf_stats(sub, label_jp))

            lines.append("\n--- 月足単独 ---")
            for tf in ["UPTREND", "BOX", "DOWNTREND", "UNCLEAR"]:
                sub = sub_base[sub_base["tf_monthly"] == tf]
                lines.append(_tf_stats(sub, f"月足={tf}"))

            lines.append("\n--- 週足単独 ---")
            for tf in ["UPTREND", "BOX", "DOWNTREND", "UNCLEAR"]:
                sub = sub_base[sub_base["tf_weekly"] == tf]
                lines.append(_tf_stats(sub, f"週足={tf}"))

            lines.append("\n判定の目安:")
            lines.append(
                "  - ALIGNED_UP (全足上昇) が他より勝率高ければ、フィルタ/加点要素として有効"
                "\n  - PARTIAL_DOWN / ALIGNED_DOWN が明らかに低勝率なら除外/減点に検討"
                "\n  - 上位足DOWNTREND時の勝率が低ければ「月足DOWNTREND除外」条件追加検討"
            )

    return "\n".join(lines)


def save_results(df: pd.DataFrame, summary_text: str) -> tuple[str, str]:
    """結果をCSVと集計テキストに保存。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = config.REPORT_DIR / f"backtest_{timestamp}.csv"
    txt_path = config.REPORT_DIR / f"backtest_{timestamp}_summary.txt"
    df.to_csv(csv_path, index=False)
    txt_path.write_text(summary_text, encoding="utf-8")
    return str(csv_path), str(txt_path)
