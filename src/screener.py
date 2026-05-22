"""スクリーニングの中核オーケストレータ。

データを読み込み、Phase 0-5 を順に走らせて買い候補を返す。
バックテストのため、過去日付時点での評価もサポートする。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import pandas as pd
from tqdm import tqdm

import config
from . import data_fetcher
from .environment import EnvironmentResult, judge_environment, judge_market_regime
from .indicators import detect_recent_levels, enrich_one
from .patterns import PatternResult, evaluate as eval_patterns
from .risk_reward import RiskReward, compute_risk_reward
from .triggers import TriggerSignal, evaluate_triggers
from .universe import (
    is_earnings_blackout,
    is_earnings_sensitive_sector,
    is_in_universe,
    passes_financial_filter,
    passes_volume_filter,
)

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    code: str
    name: str
    sector: str
    market_regime: str
    market_regime_note: str
    environment: EnvironmentResult
    pattern: PatternResult
    triggers: List[TriggerSignal]
    risk_reward: RiskReward
    score: float
    earnings_sensitive: bool
    eval_date: Optional[pd.Timestamp] = None
    notes: List[str] = field(default_factory=list)
    # モメンタム指標（カスタム版で追加：計算・表示のみ、スコア未反映）
    momentum: Dict[str, float] = field(default_factory=dict)

    @property
    def rsi_zone(self) -> str:
        """RSI標準レベルでの分類（過買い/過売り/中立）。"""
        rsi = self.momentum.get("rsi")
        if rsi is None or pd.isna(rsi):
            return "—"
        if rsi >= config.RSI_OVERBOUGHT:
            return "過買い圏"
        if rsi <= config.RSI_OVERSOLD:
            return "過売り圏"
        if abs(rsi - config.RSI_NEUTRAL) <= 5:
            return "中立"
        return "やや強気" if rsi > config.RSI_NEUTRAL else "やや弱気"

    @property
    def macd_signal_status(self) -> str:
        """MACDがシグナル線の上か下か。"""
        macd = self.momentum.get("macd")
        sig = self.momentum.get("macd_signal")
        if macd is None or sig is None or pd.isna(macd) or pd.isna(sig):
            return "—"
        return "シグナル上抜け（強気）" if macd > sig else "シグナル下抜け（弱気）"

    @property
    def has_buy_signal(self) -> bool:
        return self.score > 0 and self.risk_reward.valid and bool(self.triggers)

    @property
    def display_code(self) -> str:
        """V2 API は5桁コード（普通株末尾0）。表示用に4桁に正規化する。"""
        c = str(self.code)
        if len(c) == 5 and c.endswith("0"):
            return c[:4]
        return c


def _evaluate_one(
    code: str,
    name: str,
    sector: str,
    enriched: pd.DataFrame,
    market_regime: EnvironmentResult,
    eval_date: pd.Timestamp,
    earnings_sensitive: bool,
) -> Optional[Candidate]:
    """1銘柄を評価して候補かどうか判定する。"""
    env = judge_environment(enriched)
    if env.label == "DOWNTREND":
        return None

    # 3年バックテストで20%超は勝率36.3%/平均-1.39% → ハード除外
    if env.price_vs_ma20 > config.MAX_MA20_DEVIATION:
        return None

    pattern = eval_patterns(enriched, env)
    resistances, supports = detect_recent_levels(enriched)
    triggers = evaluate_triggers(enriched, resistances, supports)
    rr = compute_risk_reward(enriched, supports, resistances)

    score = pattern.total_score
    # トリガー別の重み（最新3年バックテスト 2026-05-23 に基づく）
    # MA5_BREAK     : 9073件、52.9% (ベース52.4%、+0.5pt) → +10 維持
    # SUPPORT_BOUNCE: 1418件、52.5% (ベース並み)        → +10 → +7 微減
    # NEW_HIGH_REENTRY: 1551件、49.6% (-2.8pt、負け越し)  → +5 → 0  ゼロ化
    trigger_weights = {
        "MA5_BREAK": 10.0,
        "SUPPORT_BOUNCE": 7.0,
        "NEW_HIGH_REENTRY": 0.0,
    }
    for t in triggers:
        score += trigger_weights.get(t.signal_type, 10.0)
    if env.confidence >= 0.7:
        score += 5
    if market_regime.label == "DOWNTREND":
        score -= 30
    elif market_regime.label == "BOX":
        score -= 10

    # スコア上限のハード除外（バックテストでスコア150+は勝率28.6%、平均-2.46%）
    if score > config.MAX_SCORE_THRESHOLD:
        return None
    # 最低スコア閾値（デフォルト0=フィルタ無効、負のスコアのみ除外）
    if score < config.MIN_SCORE_THRESHOLD:
        return None
    if score <= 0 or not rr.valid or not triggers:
        return None

    # モメンタム指標の最新値を抽出（カスタム版追加：表示用）
    last_row = enriched.iloc[-1]
    momentum = {
        "rsi": float(last_row.get(f"RSI{config.RSI_PERIOD}", float("nan"))),
        "macd": float(last_row.get("MACD", float("nan"))),
        "macd_signal": float(last_row.get("MACD_Signal", float("nan"))),
        "macd_hist": float(last_row.get("MACD_Hist", float("nan"))),
    }

    return Candidate(
        code=code,
        name=name,
        sector=sector,
        market_regime=market_regime.label,
        market_regime_note=market_regime.notes,
        environment=env,
        pattern=pattern,
        triggers=triggers,
        risk_reward=rr,
        score=score,
        earnings_sensitive=earnings_sensitive,
        eval_date=eval_date,
        momentum=momentum,
    )


def screen_at(
    cutoff_date: Optional[date] = None,
    master: Optional[pd.DataFrame] = None,
    daily: Optional[pd.DataFrame] = None,
    financials: Optional[pd.DataFrame] = None,
    announcements: Optional[pd.DataFrame] = None,
    topix: Optional[pd.DataFrame] = None,
    show_progress: bool = True,
    max_candidates: Optional[int] = None,
) -> List[Candidate]:
    """指定日時点でのスクリーニングを実行。

    cutoff_date=None なら現在時点。データを引数で渡すとロード省略できる。
    """
    if master is None:
        master = data_fetcher.load_master()
    if daily is None:
        daily = data_fetcher.load_daily()
    if financials is None:
        financials = data_fetcher.load_financials()
    if announcements is None:
        announcements = data_fetcher.load_announcements()
    if topix is None:
        topix = data_fetcher.load_topix()

    cutoff = pd.Timestamp(cutoff_date) if cutoff_date else daily["Date"].max()

    # 日足を cutoff まで絞る
    daily_cut = daily[daily["Date"] <= cutoff]
    topix_cut = topix[topix["Date"] <= cutoff] if not topix.empty else topix

    market_regime = judge_market_regime(topix_cut)

    candidates: List[Candidate] = []
    today_for_blackout = cutoff.date() if hasattr(cutoff, "date") else cutoff

    grouped = daily_cut.groupby("Code", sort=False)

    rows = master.iterrows()
    if show_progress:
        rows = tqdm(rows, total=len(master), desc=f"スクリーニング {cutoff.strftime('%Y-%m-%d')}")

    for _, row in rows:
        if not is_in_universe(row):
            continue
        code = str(row["Code"])
        name = str(row.get("CoName") or "")
        sector = str(row.get("S33Nm") or row.get("S17Nm") or "")

        if code not in grouped.groups:
            continue
        sub = grouped.get_group(code).sort_values("Date")
        if len(sub) < config.LONG_MA:
            continue

        enriched = enrich_one(sub)

        if not passes_volume_filter(enriched):
            continue
        if not passes_financial_filter(code, financials):
            continue
        if is_earnings_blackout(code, announcements, today=today_for_blackout):
            continue

        cand = _evaluate_one(
            code=code,
            name=name,
            sector=sector,
            enriched=enriched,
            market_regime=market_regime,
            eval_date=cutoff,
            earnings_sensitive=is_earnings_sensitive_sector(row),
        )
        if cand:
            candidates.append(cand)

    candidates.sort(key=lambda c: c.score, reverse=True)

    if market_regime.label == "DOWNTREND" and show_progress:
        logger.warning("全体地合いが下落相場（書籍8時限目「待つも相場」）")

    # max_candidates=None なら全候補を返す。指定があればそれで切る。
    if max_candidates is not None:
        return candidates[:max_candidates]
    return candidates


def screen(max_candidates: Optional[int] = None) -> List[Candidate]:
    """現在時点のスクリーニング（後方互換）"""
    return screen_at(max_candidates=max_candidates)


def evaluate_stock_history(
    code: str,
    days_back: int = 365,
    master: Optional[pd.DataFrame] = None,
    daily: Optional[pd.DataFrame] = None,
    financials: Optional[pd.DataFrame] = None,
    topix: Optional[pd.DataFrame] = None,
) -> List[Candidate]:
    """指定銘柄について、過去 days_back 日の各営業日でシグナル評価する。

    シグナルが発生した日（買い候補として浮上した日）のCandidateだけリストで返す。
    """
    if master is None:
        master = data_fetcher.load_master()
    if daily is None:
        daily = data_fetcher.load_daily()
    if financials is None:
        financials = data_fetcher.load_financials()
    if topix is None:
        topix = data_fetcher.load_topix()

    # 4桁→5桁補完（V2は5桁）
    code_str = str(code).strip()
    code_5 = code_str if len(code_str) == 5 else f"{code_str}0"

    mrow = master[master["Code"].astype(str).isin([code_str, code_5])]
    if mrow.empty:
        logger.warning("銘柄 %s がマスタに見つかりません", code_str)
        return []
    row = mrow.iloc[0]
    code_actual = str(row["Code"])
    name = str(row.get("CoName", ""))
    sector = str(row.get("S33Nm") or row.get("S17Nm") or "")
    earnings_sensitive = is_earnings_sensitive_sector(row)

    sub_all = daily[daily["Code"].astype(str) == code_actual].sort_values("Date")
    if sub_all.empty:
        logger.warning("銘柄 %s の日足が見つかりません", code_actual)
        return []

    end_date = sub_all["Date"].max()
    start_date = end_date - pd.Timedelta(days=days_back)
    eval_dates = sorted(sub_all[sub_all["Date"] >= start_date]["Date"].unique())

    results: List[Candidate] = []
    for d in eval_dates:
        sub_cut = sub_all[sub_all["Date"] <= d]
        if len(sub_cut) < config.LONG_MA:
            continue
        enriched = enrich_one(sub_cut)

        # 出来高フィルタ
        if not passes_volume_filter(enriched):
            continue
        # 財務フィルタ
        if not passes_financial_filter(code_actual, financials):
            continue

        # 全体地合いをその時点で再評価
        topix_cut = topix[topix["Date"] <= d] if not topix.empty else topix
        market_regime = judge_market_regime(topix_cut)

        cand = _evaluate_one(
            code=code_actual,
            name=name,
            sector=sector,
            enriched=enriched,
            market_regime=market_regime,
            eval_date=d,
            earnings_sensitive=earnings_sensitive,
        )
        if cand:
            results.append(cand)

    return results


def lookup_stock(query: str, master: Optional[pd.DataFrame] = None) -> Optional[Dict]:
    """銘柄コードまたは銘柄名で検索して情報を返す。"""
    if master is None:
        master = data_fetcher.load_master()
    q = str(query).strip()
    # コードで完全一致
    row = master[master["Code"].astype(str).isin([q, f"{q}0"])]
    if row.empty:
        # 銘柄名で部分一致
        row = master[master["CoName"].fillna("").str.contains(q, regex=False)]
    if row.empty:
        return None
    r = row.iloc[0]
    code = str(r["Code"])
    display = code[:4] if len(code) == 5 and code.endswith("0") else code
    return {
        "code": code,
        "display_code": display,
        "name": str(r.get("CoName", "")),
        "sector": str(r.get("S33Nm") or r.get("S17Nm") or ""),
        "scale": str(r.get("ScaleCat", "")),
    }
