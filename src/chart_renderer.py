"""個別銘柄の詳細チャート可視化（mplfinance）。

ローソク足 + 移動平均線(5/20/60) + 出来高 + エントリー/損切/利確 のラインを描画し、
PNG画像として保存する。HTMLレポートに埋め込み可能。
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")  # GUI不要のバックエンド
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd

try:
    import mplfinance as mpf
except ImportError:  # pragma: no cover
    mpf = None

import config
from .indicators import enrich_one

if TYPE_CHECKING:
    from .screener import Candidate

logger = logging.getLogger(__name__)

# 日本語フォントの自動設定（macOS優先）
_JAPANESE_FONTS = [
    "Hiragino Sans",
    "Hiragino Maru Gothic ProN",
    "Yu Gothic",
    "Meiryo",
    "Noto Sans CJK JP",
    "IPAexGothic",
]
for _name in _JAPANESE_FONTS:
    try:
        font_manager.findfont(_name, fallback_to_default=False)
        plt.rcParams["font.family"] = _name
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


# mplfinance のカスタムスタイル（日本式：陽線=赤、陰線=青）
def _build_style() -> dict:
    mc = mpf.make_marketcolors(
        up="#d63b3b",        # 陽線 = 赤
        down="#1c64b8",      # 陰線 = 青
        edge={"up": "#a82828", "down": "#163f80"},
        wick={"up": "#a82828", "down": "#163f80"},
        volume={"up": "#e09090", "down": "#80a3d0"},
    )
    return mpf.make_mpf_style(
        base_mpf_style="default",
        marketcolors=mc,
        gridcolor="#e0e3eb",
        gridstyle=":",
        facecolor="#ffffff",
        edgecolor="#888888",
        rc={
            "font.family": plt.rcParams.get("font.family", "DejaVu Sans"),
            "axes.unicode_minus": False,
        },
    )


def _build_momentum_addplots(df: pd.DataFrame) -> list:
    """RSI（panel=2）と MACD（panel=3）のサブパネル用 addplot を生成。

    panel 0 = メインチャート（ローソク足+MA）
    panel 1 = 出来高
    panel 2 = RSI（70/30/50 ライン付き）
    panel 3 = MACD（MACD線+シグナル線+ヒストグラム）
    """
    addplots = []
    n = len(df)

    # ----- RSI パネル（panel=2） -----
    rsi_col = f"RSI{config.RSI_PERIOD}"
    if rsi_col in df.columns and df[rsi_col].notna().any():
        addplots.append(mpf.make_addplot(
            df[rsi_col], panel=2, color="#6a1b9a", width=1.3, ylabel="RSI",
        ))
        # 70 過買い・30 過売り・50 中立 の基準線（定数シリーズとして描画）
        addplots.append(mpf.make_addplot(
            pd.Series([config.RSI_OVERBOUGHT] * n, index=df.index),
            panel=2, color="#c2185b", width=0.8, linestyle="--",
        ))
        addplots.append(mpf.make_addplot(
            pd.Series([config.RSI_OVERSOLD] * n, index=df.index),
            panel=2, color="#2e7d32", width=0.8, linestyle="--",
        ))
        addplots.append(mpf.make_addplot(
            pd.Series([config.RSI_NEUTRAL] * n, index=df.index),
            panel=2, color="#9e9e9e", width=0.6, linestyle=":",
        ))

    # ----- MACD パネル（panel=3） -----
    if "MACD" in df.columns and df["MACD"].notna().any():
        # ヒストグラムを正/負で色分け（プラス=緑、マイナス=赤）
        hist = df["MACD_Hist"]
        hist_colors = ["#2e7d32" if v >= 0 else "#c2185b" for v in hist.fillna(0)]
        addplots.append(mpf.make_addplot(
            hist, panel=3, type="bar", color=hist_colors, alpha=0.55, width=0.7, ylabel="MACD",
        ))
        # MACD 線（青）
        addplots.append(mpf.make_addplot(
            df["MACD"], panel=3, color="#1565c0", width=1.3,
        ))
        # シグナル線（オレンジ）
        addplots.append(mpf.make_addplot(
            df["MACD_Signal"], panel=3, color="#ef6c00", width=1.2,
        ))
        # ゼロライン
        addplots.append(mpf.make_addplot(
            pd.Series([0.0] * n, index=df.index),
            panel=3, color="#9e9e9e", width=0.6, linestyle=":",
        ))

    return addplots


# パネル比率: メイン:出来高:RSI:MACD = 6 : 1.5 : 2 : 2.5
_PANEL_RATIOS = (6, 1.5, 2, 2.5)


def _prepare_ohlc(
    daily_df: pd.DataFrame,
    lookback: int = 120,
    signal_date: Optional[pd.Timestamp] = None,
    lookforward: int = 0,
) -> Optional[pd.DataFrame]:
    """銘柄の日足DataFrameを mplfinance 用に整形。

    signal_date を指定すると、その日を中心に「前 lookback 日 + 後 lookforward 日」を抽出。
    None なら最新からの lookback 日。
    """
    enriched = enrich_one(daily_df)
    if enriched.empty:
        return None
    if signal_date is not None:
        enriched["Date"] = pd.to_datetime(enriched["Date"])
        # signal_date 以前 lookback 日 + signal_date 以後 lookforward 日
        before = enriched[enriched["Date"] <= signal_date].tail(lookback)
        after = enriched[enriched["Date"] > signal_date].head(lookforward)
        df = pd.concat([before, after], ignore_index=True)
    else:
        df = enriched.tail(lookback).copy()
    if df.empty:
        return None
    df.index = pd.to_datetime(df["Date"])
    df = df.rename(columns={
        "AdjO": "Open",
        "AdjH": "High",
        "AdjL": "Low",
        "AdjC": "Close",
        "AdjVo": "Volume",
    })
    return df


def render_candidate_chart(
    candidate: "Candidate",
    daily_df: pd.DataFrame,
    save_path: Optional[Path] = None,
    lookback: int = 120,
) -> Optional[Path]:
    """1銘柄のチャートを描画してPNG保存。"""
    if mpf is None:
        logger.warning("mplfinance が未インストールのためチャート出力をスキップ")
        return None

    sub = daily_df[daily_df["Code"].astype(str) == str(candidate.code)].sort_values("Date")
    df = _prepare_ohlc(sub, lookback=lookback)
    if df is None or len(df) < 30:
        return None

    # 追加プロット: 移動平均線
    addplots = []
    if "MA5" in df.columns and df["MA5"].notna().any():
        addplots.append(mpf.make_addplot(df["MA5"], color="#9c27b0", width=1.2))
    if "MA20" in df.columns and df["MA20"].notna().any():
        addplots.append(mpf.make_addplot(df["MA20"], color="#e89a3c", width=1.5))
    if "MA60" in df.columns and df["MA60"].notna().any():
        addplots.append(mpf.make_addplot(df["MA60"], color="#00897b", width=1.5))
    # RSI/MACD サブパネル
    addplots.extend(_build_momentum_addplots(df))

    # エントリー/損切/利確 ライン
    rr = candidate.risk_reward
    hlines_dict = dict(
        hlines=[rr.entry, rr.stop_loss, rr.take_profit],
        colors=["#000000", "#c2185b", "#ff8f00"],   # 黒=エントリー, 濃ピンク=損切, 濃橙=利確
        linestyle=["-", "--", "--"],
        linewidths=[1.6, 1.4, 1.4],
    )

    title = (
        f"{candidate.display_code} {candidate.name} "
        f"(スコア {candidate.score:.0f} / {candidate.environment.label})"
    )

    if save_path is None:
        save_path = config.REPORT_DIR / "charts" / f"{candidate.display_code}.png"
    save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fig, _axes = mpf.plot(
            df,
            type="candle",
            style=_build_style(),
            addplot=addplots if addplots else None,
            volume=True,
            hlines=hlines_dict,
            figsize=(11, 10),
            panel_ratios=_PANEL_RATIOS,
            title=title,
            ylabel="株価 (円)",
            ylabel_lower="出来高",
            tight_layout=True,
            returnfig=True,
            warn_too_much_data=lookback + 10,
            update_width_config=dict(
                candle_linewidth=1.2,
                candle_width=0.85,
                volume_width=0.85,
            ),
        )
        fig.savefig(save_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return save_path
    except Exception as exc:
        logger.warning("チャート描画失敗 %s: %s", candidate.code, exc)
        return None


def render_as_base64(
    candidate: "Candidate",
    daily_df: pd.DataFrame,
    lookback: int = 120,
    lookforward: int = 30,
) -> Optional[str]:
    """HTML埋め込み用に base64 文字列を返す。

    candidate.eval_date がデータ最新日より十分過去なら「シグナル日からN日後の動き」も含めて
    描画し、縦点線でシグナル日を示す。最新時点のシグナルなら通常通り直近 lookback 日のみ。
    """
    if mpf is None:
        return None
    sub = daily_df[daily_df["Code"].astype(str) == str(candidate.code)].sort_values("Date")
    if sub.empty:
        return None

    # 過去シグナルか判定（データ最新日から5日以上前なら past signal とみなす）
    latest_in_data = pd.to_datetime(sub["Date"].max())
    raw_signal = pd.to_datetime(candidate.eval_date) if candidate.eval_date is not None else None
    is_past = bool(raw_signal is not None and (latest_in_data - raw_signal).days > 5)
    signal_date = raw_signal if is_past else None
    effective_lookforward = lookforward if is_past else 0

    df = _prepare_ohlc(sub, lookback=lookback, signal_date=signal_date, lookforward=effective_lookforward)
    if df is None or len(df) < 30:
        return None

    addplots = []
    if "MA5" in df.columns and df["MA5"].notna().any():
        addplots.append(mpf.make_addplot(df["MA5"], color="#9c27b0", width=1.2))
    if "MA20" in df.columns and df["MA20"].notna().any():
        addplots.append(mpf.make_addplot(df["MA20"], color="#e89a3c", width=1.5))
    if "MA60" in df.columns and df["MA60"].notna().any():
        addplots.append(mpf.make_addplot(df["MA60"], color="#00897b", width=1.5))
    # RSI/MACD サブパネル
    addplots.extend(_build_momentum_addplots(df))

    rr = candidate.risk_reward
    hlines_dict = dict(
        hlines=[rr.entry, rr.stop_loss, rr.take_profit],
        colors=["#000000", "#c2185b", "#ff8f00"],
        linestyle=["-", "--", "--"],
        linewidths=[1.6, 1.4, 1.4],
    )

    # シグナル日を縦線で表示（過去日の場合）
    vlines_dict = None
    if is_past and signal_date is not None:
        # signal_date の前後で日付差が最小の日を選ぶ（実営業日が一致しないケースの安全策）
        try:
            closest_idx = df.index[df.index <= signal_date][-1]
            vlines_dict = dict(
                vlines=[closest_idx],
                colors=["#000000"],
                linestyle=["--"],
                linewidths=[1.5],
                alpha=0.6,
            )
        except (IndexError, KeyError):
            vlines_dict = None

    title_extra = ""
    if is_past:
        title_extra = f" ｜ シグナル日: {raw_signal.strftime('%Y-%m-%d')}（縦点線、以降は実績）"
    title = (
        f"{candidate.display_code} {candidate.name} "
        f"(スコア {candidate.score:.0f} / {candidate.environment.label}){title_extra}"
    )

    try:
        plot_kwargs = dict(
            type="candle",
            style=_build_style(),
            addplot=addplots if addplots else None,
            volume=True,
            hlines=hlines_dict,
            figsize=(11, 10),
            panel_ratios=_PANEL_RATIOS,
            title=title,
            ylabel="株価 (円)",
            ylabel_lower="出来高",
            tight_layout=True,
            returnfig=True,
            warn_too_much_data=lookback + lookforward + 10,
            update_width_config=dict(
                candle_linewidth=1.2,
                candle_width=0.85,
                volume_width=0.85,
            ),
        )
        if vlines_dict:
            plot_kwargs["vlines"] = vlines_dict
        fig, _axes = mpf.plot(df, **plot_kwargs)
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=90, bbox_inches="tight")
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        logger.warning("チャート描画失敗 %s: %s", candidate.code, exc)
        return None


def render_code(code: str, lookback: int = 180) -> Optional[Path]:
    """銘柄コードを指定してチャートを生成（screener候補がなくても呼べる）。"""
    from . import data_fetcher
    master = data_fetcher.load_master()
    daily = data_fetcher.load_daily()

    # 4桁を5桁に補完（jquants V2は5桁）
    code_5 = code if len(code) == 5 else f"{code}0"
    sub = daily[daily["Code"].astype(str).isin([code, code_5])].sort_values("Date")
    if sub.empty:
        logger.warning("銘柄 %s の日足データが見つかりません", code)
        return None

    df = _prepare_ohlc(sub, lookback=lookback)
    if df is None or len(df) < 30:
        return None

    # 銘柄名取得
    mrow = master[master["Code"].astype(str).isin([code, code_5])]
    name = mrow.iloc[0].get("CoName", "") if not mrow.empty else ""

    addplots = []
    if "MA5" in df.columns and df["MA5"].notna().any():
        addplots.append(mpf.make_addplot(df["MA5"], color="#9c27b0", width=1.2))
    if "MA20" in df.columns and df["MA20"].notna().any():
        addplots.append(mpf.make_addplot(df["MA20"], color="#e89a3c", width=1.5))
    if "MA60" in df.columns and df["MA60"].notna().any():
        addplots.append(mpf.make_addplot(df["MA60"], color="#00897b", width=1.5))
    if "MA200" in df.columns and df["MA200"].notna().any():
        addplots.append(mpf.make_addplot(df["MA200"], color="#607d8b", width=1.0))
    # RSI/MACD サブパネル
    addplots.extend(_build_momentum_addplots(df))

    display_code = code_5[:4] if len(code_5) == 5 and code_5.endswith("0") else code_5
    title = f"{display_code} {name} (赤=陽線/青=陰線 ｜ MA: 紫=5/橙=20/緑=60/グレー=200)"

    save_path = config.REPORT_DIR / "charts" / f"manual_{display_code}_{datetime.now().strftime('%Y%m%d_%H%M')}.png"
    save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fig, _axes = mpf.plot(
            df,
            type="candle",
            style=_build_style(),
            addplot=addplots if addplots else None,
            volume=True,
            figsize=(12, 10),
            panel_ratios=_PANEL_RATIOS,
            title=title,
            ylabel="株価 (円)",
            ylabel_lower="出来高",
            tight_layout=True,
            returnfig=True,
            warn_too_much_data=lookback + 10,
            update_width_config=dict(
                candle_linewidth=1.2,
                candle_width=0.85,
                volume_width=0.85,
            ),
        )
        fig.savefig(save_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return save_path
    except Exception as exc:
        logger.warning("チャート描画失敗 %s: %s", code, exc)
        return None
