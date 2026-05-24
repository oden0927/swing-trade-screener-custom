"""Streamlit ベースの Web UI。

実行方法:
    streamlit run web_app.py

ブラウザが自動で開き、http://localhost:8501 で操作できる。
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus

# プロジェクトルートを path に追加
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

# Streamlit Cloud の secrets を環境変数にブリッジ（config.py 読み込み前）
# ローカル開発時は .env が使われる
try:
    if "JQUANTS_API_KEY" in st.secrets:
        os.environ["JQUANTS_API_KEY"] = st.secrets["JQUANTS_API_KEY"]
except Exception:
    pass  # secrets.toml が無いローカル環境では何もしない

# config を読み込み（プレミアム閾値など参照用）
import config


# ====== ニュースリンク生成 ======
def google_news_url(query: str, after_d: date, before_d: date) -> str:
    """Google ニュースの期間指定検索URLを生成。"""
    after_str = after_d.strftime("%Y-%m-%d")
    before_str = before_d.strftime("%Y-%m-%d")
    q = quote_plus(f'"{query}" after:{after_str} before:{before_str}')
    return f"https://news.google.com/search?q={q}&hl=ja-JP&gl=JP&ceid=JP:ja"


def yahoo_finance_news_url(display_code: str) -> str:
    """Yahoo!ファイナンスのニュースタブURL。"""
    return f"https://finance.yahoo.co.jp/quote/{display_code}.T/news"


def kabutan_news_url(display_code: str) -> str:
    """株探の銘柄ニュースページ。"""
    return f"https://kabutan.jp/stock/news?code={display_code}"


def render_news_section(c, eval_d: date) -> None:
    """ニュースリンク群をStreamlit上に描画する。"""
    one_month_back = eval_d - timedelta(days=30)
    one_month_forward = eval_d + timedelta(days=30)
    two_weeks_back = eval_d - timedelta(days=14)

    is_past_signal = eval_d < date.today() - timedelta(days=5)

    st.markdown("**📰 関連ニュース・情報**")
    col1, col2 = st.columns(2)
    with col1:
        if is_past_signal:
            # 過去シグナル: 前2週 + 後1か月
            st.markdown(
                f"- 🔍 [Google ニュース: シグナル日前2週間]"
                f"({google_news_url(c.name, two_weeks_back, eval_d)})"
            )
            st.markdown(
                f"- 🔍 [Google ニュース: シグナル日以降1か月]"
                f"({google_news_url(c.name, eval_d, one_month_forward)})"
            )
        else:
            # 現在のシグナル: 過去1か月
            st.markdown(
                f"- 🔍 [Google ニュース: 過去1か月]"
                f"({google_news_url(c.name, one_month_back, eval_d + timedelta(days=1))})"
            )
    with col2:
        st.markdown(f"- 📊 [Yahoo!ファイナンス（{c.display_code}）]({yahoo_finance_news_url(c.display_code)})")
        st.markdown(f"- 📈 [株探（{c.display_code}）]({kabutan_news_url(c.display_code)})")

st.set_page_config(
    page_title="スイングトレード スクリーナー",
    page_icon="📊",
    layout="wide",
)

st.title("📊 スイングトレード スクリーナー")

# データ最新日（情報表示と上限値用）
try:
    from src import data_fetcher as _df_module
    _daily_top = _df_module.load_daily()
    LATEST_DATA_DATE = _daily_top["Date"].max().date() if not _daily_top.empty else date.today()
except Exception:
    LATEST_DATA_DATE = date.today()


# ===== タブ切り替え =====
tab_screen, tab_history, tab_position = st.tabs([
    "🔍 スクリーニング",
    "📈 銘柄シグナル履歴",
    "📊 保有銘柄チェック",
])


# ============================================================
# タブ1: スクリーニング
# ============================================================
with tab_screen:
    # ----- サイドバー（タブをまたぐので外でなくここで配置） -----
    with st.sidebar:
        st.header("⚙️ スクリーニング設定")
        st.caption(f"データ最新日: {LATEST_DATA_DATE}")

        mode = st.radio(
            "モード",
            ["現在のスクリーニング", "過去日付で再現"],
            help="過去日付モードならその日に出ていた候補と、その後の動きを表示",
        )

        if mode == "過去日付で再現":
            target_date = st.date_input(
                "基準日",
                value=max(date.today() - timedelta(days=30), LATEST_DATA_DATE - timedelta(days=30)),
                max_value=LATEST_DATA_DATE,
                help="この日付時点でのスクリーニングを実行（その後の値動きも表示）",
            )
            quiz_mode = st.checkbox(
                "🎯 クイズモード（未来を隠す）",
                value=False,
                help="チャートのシグナル日以降を非表示。各候補に「答え表示」ボタンが付き、予想練習ができる",
            )
        else:
            target_date = None
            quiz_mode = False

        limit = st.number_input(
            "表示件数",
            min_value=0,
            max_value=200,
            value=20,
            step=5,
            help="0 で全候補表示",
        )

        show_charts = st.checkbox(
            "チャート画像を表示",
            value=True,
            help="50件で約2〜5分かかります",
        )

        run_button = st.button("🔍 スクリーニング実行", type="primary", use_container_width=True)

        st.markdown("---")
        st.caption("📖 [本書ナレッジベース](book_knowledge_base.md)")
        st.caption("🛠 [設定一覧](config_summary.txt)")

        with st.expander("❓ 使い方・スコアの目安"):
            st.markdown("""
            **使い方**

            1. **現在のスクリーニング**: 今この瞬間（最新データ）の買い候補を抽出
            2. **過去日付で再現**: 過去の特定日のシグナルを再現し、その後どう動いたかを確認

            **スコアの目安**

            - **50-75点**: バランスの良い候補
            - **75-150点**: 高品質候補
            - **150点超**: 自動除外（バックテストで負け組と判明）
            """)

    # ----- メインコンテンツ -----
    # ボタンが押された時に新しくスクリーニングを実行し、結果をsession_stateに保存
    # （クイズボタン等で再実行時も結果が消えないように）
    if run_button:
        from src.screener import screen_at
        from src import data_fetcher

        spinner_text = "スクリーニング中..."
        if target_date:
            spinner_text = f"{target_date} 時点のスクリーニング中..."

        with st.spinner(spinner_text):
            candidates = screen_at(
                cutoff_date=target_date,
                max_candidates=limit if limit > 0 else None,
                show_progress=False,
            )

        # session_state に保存（クイズボタン等の再実行で結果を保持）
        st.session_state["screen_results"] = candidates
        st.session_state["screen_target_date"] = target_date
        st.session_state["screen_quiz_mode"] = quiz_mode
        st.session_state["screen_show_charts"] = show_charts
        # 過去のクイズ回答状態をクリア
        keys_to_clear = [k for k in list(st.session_state.keys()) if k.startswith("quiz_reveal_")]
        for k in keys_to_clear:
            del st.session_state[k]

    # session_state に結果があれば表示（実行ボタンが押された後・クイズ操作時の両方で機能）
    if "screen_results" not in st.session_state:
        # 初期画面は何も表示せず、ユーザーがサイドバーから操作するのを待つ
        pass
    else:
        candidates = st.session_state["screen_results"]
        target_date = st.session_state.get("screen_target_date")
        quiz_mode = st.session_state.get("screen_quiz_mode", False)
        show_charts = st.session_state.get("screen_show_charts", True)
        from src import data_fetcher

        if not candidates:
            st.warning("条件に合致する銘柄が見つかりませんでした。地合いが下落相場の可能性もあります。")
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("候補数", f"{len(candidates)}件")
            col2.metric("最高スコア", f"{candidates[0].score:.0f}")
            col3.metric("最低スコア", f"{candidates[-1].score:.0f}")
            col4.metric("地合い", candidates[0].market_regime)

            scores = [c.score for c in candidates]
            score_bands = {"0-50": 0, "50-75": 0, "75-100": 0, "100-150": 0}
            for s in scores:
                if s < 50:
                    score_bands["0-50"] += 1
                elif s < 75:
                    score_bands["50-75"] += 1
                elif s < 100:
                    score_bands["75-100"] += 1
                else:
                    score_bands["100-150"] += 1
            st.caption(
                f"スコア分布: 0-50: {score_bands['0-50']}件 ｜ "
                f"50-75: {score_bands['50-75']}件 ｜ "
                f"75-100: {score_bands['75-100']}件 ｜ "
                f"100-150: {score_bands['100-150']}件"
            )

            # プレミアム候補（スコア >= PREMIUM_SCORE_THRESHOLD）の強調表示
            premium_threshold = getattr(config, "PREMIUM_SCORE_THRESHOLD", 80)
            premium_candidates = [c for c in candidates if c.score >= premium_threshold]
            if premium_candidates:
                st.success(
                    f"🌟 **本日のプレミアム候補: {len(premium_candidates)}件**"
                    f"（スコア {premium_threshold} 以上）｜ "
                    f"3年実証で勝率56.6%・期待値+1.10%の品質ジャンプ群"
                )

            if target_date and (LATEST_DATA_DATE - target_date).days > 5:
                st.info(
                    f"📅 **過去日付モード**: {target_date} のシグナル / "
                    f"その後 {(LATEST_DATA_DATE - target_date).days} 日分の実績を表示します"
                )

            daily_for_charts = None
            if show_charts:
                with st.spinner("チャート用データをロード中..."):
                    daily_for_charts = data_fetcher.load_daily()

            st.markdown("---")
            st.subheader(f"候補一覧（{len(candidates)}件）")

            for i, c in enumerate(candidates, 1):
                warn = " ⚠️" if c.earnings_sensitive else ""
                premium_mark = "🌟 " if c.score >= premium_threshold else ""
                with st.expander(
                    f"**{premium_mark}#{i}　{c.display_code} {c.name}**　"
                    f"スコア {c.score:.0f} / {c.environment.label}{warn}　"
                    f"〔{c.sector}〕",
                    expanded=(i <= 3),
                ):
                    col_l, col_r = st.columns([1, 1])

                    with col_l:
                        st.markdown("**① 該当パターン**")
                        for m in c.pattern.matches:
                            if m.score > 0:
                                st.markdown(f"- 🔵 **{m.label}** (+{m.score:.0f}点)")
                                st.caption(f"　 {m.description} ／ {m.book_reference}")
                            else:
                                st.markdown(f"- ⚪ {m.label}（参考のみ）")
                        for b in c.pattern.bonus:
                            st.markdown(f"- 🟢 加点: **{b.label}** (+{b.score:.0f}点)")
                            st.caption(f"　 {b.description} ／ {b.book_reference}")
                        for p in c.pattern.penalties:
                            st.markdown(f"- 🔴 減点: **{p.label}** (-{p.score:.0f}点)")
                            st.caption(f"　 {p.description} ／ {p.book_reference}")

                        st.markdown("**② 買いトリガー**")
                        for t in c.triggers:
                            st.markdown(f"- 🟡 `{t.signal_type}`: {t.description}")
                            st.caption(f"　 {t.book_reference}")

                        # 上位足→下位足分析（getattr で安全アクセス、属性が無い古い候補でも動作）
                        mtf = getattr(c, "multi_timeframe", None) or {}
                        if mtf:
                            st.markdown("**上位足→下位足分析**（参考・スコア未反映）")
                            m_lbl = mtf.get("monthly", "—")
                            w_lbl = mtf.get("weekly", "—")
                            d_lbl = mtf.get("daily", "—")
                            tf_emoji = {"UPTREND": "🟢", "DOWNTREND": "🔴", "BOX": "🟡", "UNCLEAR": "⚪"}
                            st.markdown(
                                f"- 月足: {tf_emoji.get(m_lbl, '⚪')} **{m_lbl}** ｜ "
                                f"週足: {tf_emoji.get(w_lbl, '⚪')} **{w_lbl}** ｜ "
                                f"日足: {tf_emoji.get(d_lbl, '⚪')} **{d_lbl}**"
                            )
                            align_label = getattr(c, "timeframe_alignment_label", "—")
                            st.caption(f"　整合性: {align_label}（書籍 1時限目03 p.49）")

                        st.markdown("**モメンタム指標**（参考・スコア未反映）")
                        momentum_dict = getattr(c, "momentum", None) or {}
                        rsi_val = momentum_dict.get("rsi")
                        macd_val = momentum_dict.get("macd")
                        macd_sig_val = momentum_dict.get("macd_signal")
                        macd_hist_val = momentum_dict.get("macd_hist")
                        if rsi_val is not None and rsi_val == rsi_val:
                            st.markdown(f"- 🟣 RSI(14): **{rsi_val:.1f}** ({c.rsi_zone})")
                            st.caption("　 基準: 70+過買い / 30-過売り / 約50中立")
                        if (macd_val is not None and macd_val == macd_val
                                and macd_sig_val is not None and macd_sig_val == macd_sig_val):
                            st.markdown(
                                f"- 🟣 MACD(12,26,9): MACD **{macd_val:.2f}** / "
                                f"Sig **{macd_sig_val:.2f}** / Hist **{macd_hist_val:.2f}**"
                            )
                            st.caption(f"　 {c.macd_signal_status}")
                        # ボリンジャーバンド状態 (新規 2026-05-23)
                        bb_up2 = momentum_dict.get("bb_up2")
                        bb_dn2 = momentum_dict.get("bb_dn2")
                        bb_mid = momentum_dict.get("bb_mid")
                        if bb_up2 is not None and bb_up2 == bb_up2 and bb_dn2 is not None and bb_dn2 == bb_dn2:
                            bb_status = getattr(c, "bb_status_label", "—")
                            st.markdown(
                                f"- 🟣 ボリンジャー(20): 中央 **{bb_mid:.0f}** / "
                                f"+2σ **{bb_up2:.0f}** / -2σ **{bb_dn2:.0f}**"
                            )
                            st.caption(f"　 状態: {bb_status}")

                    with col_r:
                        st.markdown("**③ 売買進め方**")
                        rr = c.risk_reward
                        st.markdown(f"""
| 項目 | 値 |
|---|---|
| エントリー | **{rr.entry:.0f} 円** |
| 損切ライン | {rr.stop_loss:.0f} 円 ({rr.risk_pct * 100:.1f}%下) |
| 利確目標 | {rr.take_profit:.0f} 円 ({rr.reward_pct * 100:.1f}%上) |
| RR比 | **1 : {rr.rr_ratio:.2f}** |
| 損切根拠 | {rr.stop_basis} |
| 利確根拠 | {rr.target_basis} |
                        """)

                        st.markdown("**④ 売り判断**")
                        st.markdown("""
- 利確: 過去高値 / 包み足・否定陰線 / 5日MA陰線割れ / 上昇開始 7〜9 日目
- 損切: 逆指値で自動執行（5時限目02④）
- 含み益: 損切位置の **引き上げのみ** OK
- 分割売買: 想定資金を **3分割**、1回目で全額入れない
                        """)

                    # ニュースリンクセクション
                    eval_d_for_news = (
                        pd.Timestamp(c.eval_date).date() if c.eval_date is not None else date.today()
                    )
                    render_news_section(c, eval_d_for_news)

                    if show_charts and daily_for_charts is not None:
                        from src.chart_renderer import render_as_base64

                        # クイズモード時は答えの表示/非表示を管理
                        is_revealed = True  # デフォルト: 通常通り未来も表示
                        if quiz_mode:
                            reveal_key = f"quiz_reveal_{c.code}_{i}"
                            is_revealed = st.session_state.get(reveal_key, False)

                        # チャート生成（クイズモードで未公開なら未来非表示）
                        try:
                            b64 = render_as_base64(
                                c, daily_for_charts,
                                lookback=120, lookforward=30,
                                force_hide_future=(quiz_mode and not is_revealed),
                            )
                        except TypeError:
                            # 古い chart_renderer.py 用のフォールバック
                            b64 = render_as_base64(
                                c, daily_for_charts,
                                lookback=120,
                                lookforward=30 if (not quiz_mode or is_revealed) else 0,
                            )

                        if b64:
                            chart_title = "**⑤ ローソク足チャート**"
                            if quiz_mode and not is_revealed:
                                chart_title = "**⑤ ローソク足チャート（🎯 クイズモード：未来非表示）**"
                            elif quiz_mode and is_revealed:
                                chart_title = "**⑤ ローソク足チャート（✅ 答え表示中）**"
                            st.markdown(chart_title)
                            st.markdown(
                                f'<img src="data:image/png;base64,{b64}" style="width:100%; max-width:1000px; border:1px solid #ddd; border-radius:6px;">',
                                unsafe_allow_html=True,
                            )
                            st.caption(
                                "ローソク足: 🔴赤=陽線 / 🔵青=陰線 ｜ "
                                "MA: 🟣紫=5MA / 🟠橙=20MA / 🟢緑=60MA ｜ "
                                "売買: ⬛黒線=エントリー / 🩷桃破線=損切 / 🟧橙破線=利確"
                            )

                            # クイズモード用の答え表示ボタン
                            if quiz_mode:
                                if not is_revealed:
                                    if st.button(
                                        f"💡 答えを表示 ({c.display_code})",
                                        key=f"reveal_btn_{c.code}_{i}",
                                    ):
                                        st.session_state[f"quiz_reveal_{c.code}_{i}"] = True
                                        st.rerun()
                                else:
                                    # 実績リターンを表示
                                    sub_d = daily_for_charts[
                                        daily_for_charts["Code"].astype(str) == str(c.code)
                                    ].sort_values("Date").copy()
                                    sub_d["Date"] = pd.to_datetime(sub_d["Date"])
                                    sig_ts = pd.Timestamp(target_date) if target_date else pd.Timestamp(date.today())
                                    entry_close = (sub_d[sub_d["Date"] <= sig_ts]["AdjC"].iloc[-1]
                                                   if not sub_d[sub_d["Date"] <= sig_ts].empty else None)
                                    future_df = sub_d[sub_d["Date"] > sig_ts].head(30)
                                    if entry_close is not None and not future_df.empty:
                                        close_5d = future_df["AdjC"].iloc[4] if len(future_df) >= 5 else None
                                        close_10d = future_df["AdjC"].iloc[9] if len(future_df) >= 10 else None
                                        close_20d = future_df["AdjC"].iloc[19] if len(future_df) >= 20 else None
                                        col_a, col_b, col_c = st.columns(3)
                                        if close_5d:
                                            col_a.metric("5日後", f"{close_5d:.0f}",
                                                         f"{(close_5d-entry_close)/entry_close*100:+.2f}%")
                                        if close_10d:
                                            col_b.metric("10日後", f"{close_10d:.0f}",
                                                         f"{(close_10d-entry_close)/entry_close*100:+.2f}%")
                                        if close_20d:
                                            col_c.metric("20日後", f"{close_20d:.0f}",
                                                         f"{(close_20d-entry_close)/entry_close*100:+.2f}%")
                                    if st.button(
                                        f"🔄 答えを隠す ({c.display_code})",
                                        key=f"hide_btn_{c.code}_{i}",
                                    ):
                                        st.session_state[f"quiz_reveal_{c.code}_{i}"] = False
                                        st.rerun()


# ============================================================
# タブ2: 銘柄シグナル履歴
# ============================================================
with tab_history:
    st.subheader("📈 銘柄シグナル履歴の検索")
    st.markdown("""
    指定した銘柄について、過去どの日に買いシグナルが発生したかを表示します。
    シグナルが出ていた日の **パターン・トリガー・スコア** をタイムライン形式で確認できます。
    """)

    col_q, col_period = st.columns([2, 1])
    with col_q:
        query = st.text_input(
            "銘柄コード または 銘柄名",
            placeholder="例: 7203 / トヨタ / 4385 / メルカリ",
            help="4桁の銘柄コードか、銘柄名（部分一致可）",
        )
    with col_period:
        days_back = st.selectbox(
            "対象期間",
            options=[90, 180, 365, 730, 1095],
            index=2,
            format_func=lambda d: f"過去 {d} 日（約{d // 30}か月）",
        )

    history_charts = st.checkbox(
        "各シグナル日のチャートを表示", value=False,
        help="件数が多いと時間がかかります（1件あたり数秒）",
    )

    search_button = st.button("🔎 シグナル履歴を検索", type="primary")

    if search_button:
        if not query.strip():
            st.error("銘柄コードまたは銘柄名を入力してください")
        else:
            from src.screener import evaluate_stock_history, lookup_stock

            info = lookup_stock(query)
            if not info:
                st.error(f"銘柄 「{query}」 が見つかりません。コードは4桁、銘柄名は一部でも可。")
            else:
                st.success(
                    f"📌 **{info['display_code']} {info['name']}** "
                    f"〔{info['sector']}〕 {info['scale']}"
                )

                with st.spinner(f"過去 {days_back} 日分のシグナルを検索中..."):
                    history = evaluate_stock_history(info["code"], days_back=days_back)

                if not history:
                    st.warning(
                        "この銘柄ではこの期間にシグナルが発生していません。"
                        "出来高・財務・地合いなどの前提条件を満たさなかった可能性もあります。"
                    )
                else:
                    # サマリーメトリクス
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("シグナル発生回数", f"{len(history)} 回")
                    avg_score = sum(c.score for c in history) / len(history)
                    col_b.metric("平均スコア", f"{avg_score:.1f}")
                    max_score = max(c.score for c in history)
                    col_c.metric("最高スコア", f"{max_score:.0f}")

                    # 一覧表示
                    st.markdown("---")
                    st.subheader(f"シグナル一覧（古い順、{len(history)} 件）")

                    # 一覧テーブル
                    rows = []
                    for c in history:
                        rows.append({
                            "日付": c.eval_date.strftime("%Y-%m-%d"),
                            "スコア": f"{c.score:.0f}",
                            "個別環境": c.environment.label,
                            "地合い": c.market_regime,
                            "パターン": ", ".join(m.label for m in c.pattern.matches if m.score > 0),
                            "トリガー": ", ".join(t.signal_type for t in c.triggers),
                            "エントリー": f"{c.risk_reward.entry:.0f}",
                            "損切": f"{c.risk_reward.stop_loss:.0f}",
                            "利確": f"{c.risk_reward.take_profit:.0f}",
                            "RR比": f"1:{c.risk_reward.rr_ratio:.2f}",
                        })
                    df_hist = pd.DataFrame(rows)
                    st.dataframe(df_hist, use_container_width=True, hide_index=True)

                    # 各シグナルの詳細
                    if history_charts:
                        from src import data_fetcher as _df
                        daily_full = _df.load_daily()
                        from src.chart_renderer import render_as_base64

                        st.markdown("---")
                        st.subheader("各シグナル日の詳細チャート")
                        for c in history:
                            with st.expander(
                                f"{c.eval_date.strftime('%Y-%m-%d')} | "
                                f"スコア {c.score:.0f} | {c.environment.label}"
                            ):
                                st.markdown(f"**パターン:** {', '.join(m.label for m in c.pattern.matches if m.score > 0) or '（なし）'}")
                                st.markdown(f"**加点:** {', '.join(b.label for b in c.pattern.bonus) or '（なし）'}")
                                st.markdown(f"**減点:** {', '.join(p.label for p in c.pattern.penalties) or '（なし）'}")
                                st.markdown(f"**トリガー:** {', '.join(t.signal_type for t in c.triggers)}")
                                st.markdown(
                                    f"**エントリー:** {c.risk_reward.entry:.0f}円 / "
                                    f"**損切:** {c.risk_reward.stop_loss:.0f}円 / "
                                    f"**利確:** {c.risk_reward.take_profit:.0f}円 / "
                                    f"**RR:** 1:{c.risk_reward.rr_ratio:.2f}"
                                )
                                # ニュースリンク
                                eval_d_for_news = pd.Timestamp(c.eval_date).date()
                                render_news_section(c, eval_d_for_news)
                                # チャート
                                b64 = render_as_base64(c, daily_full, lookback=90, lookforward=30)
                                if b64:
                                    st.markdown(
                                        f'<img src="data:image/png;base64,{b64}" style="width:100%; max-width:900px; border:1px solid #ddd; border-radius:6px;">',
                                        unsafe_allow_html=True,
                                    )
    else:
        st.info("銘柄コードまたは銘柄名を入力して「シグナル履歴を検索」を押してください")


# ============================================================
# タブ3: 保有銘柄チェック（書籍5時限目 利確基準の自動判定）
# ============================================================
with tab_position:
    st.subheader("📊 保有銘柄チェック（売り判断シグナル）")
    st.markdown("""
    エントリー済の銘柄について、書籍5時限目に基づく**売り判断シグナル**を自動判定します。

    検出する売りシグナル:
    - 🔴 **損切ライン到達** (即時損切)
    - 🟢 **利確目標到達** (RR比達成)
    - 🟠 **過去高値到達** (20日/60日/250日)
    - 🟡 **上昇日数 7-9日** (短期トレーダー利確時期)
    - 🔴 **5MA陰線割れ** (短期トレンド崩れ)
    - 🟡 **弱いローソク足** (包み足/宵の明星)
    """)

    col_input1, col_input2 = st.columns([1, 1])
    with col_input1:
        pos_code = st.text_input(
            "銘柄コード（4桁または5桁）",
            value="",
            help="例: 7203（トヨタ自動車）",
            key="position_code",
        )
        pos_entry_date = st.date_input(
            "エントリー日",
            value=date.today() - timedelta(days=7),
            max_value=LATEST_DATA_DATE,
            help="この銘柄を買った日",
            key="position_entry_date",
        )

    with col_input2:
        pos_entry_price = st.number_input(
            "エントリー価格（円）",
            min_value=0.0,
            value=0.0,
            step=1.0,
            help="買った時の価格",
            key="position_entry_price",
        )
        col_stop, col_profit = st.columns(2)
        with col_stop:
            pos_stop_loss = st.number_input(
                "損切ライン",
                min_value=0.0,
                value=0.0,
                step=1.0,
                help="逆指値の価格",
                key="position_stop_loss",
            )
        with col_profit:
            pos_take_profit = st.number_input(
                "利確目標",
                min_value=0.0,
                value=0.0,
                step=1.0,
                help="目標株価",
                key="position_take_profit",
            )

    check_button = st.button("📊 売り判断を実行", type="primary", key="position_check")

    if check_button:
        if not pos_code.strip():
            st.error("銘柄コードを入力してください")
        elif pos_entry_price <= 0:
            st.error("エントリー価格を入力してください")
        else:
            with st.spinner("売り判断シグナルを計算中..."):
                from src.sell_signals import evaluate_sell_signals
                from src import data_fetcher as _df

                master = _df.load_master()
                daily_all = _df.load_daily()

                # 4桁→5桁変換
                code_str = pos_code.strip()
                code_5 = code_str if len(code_str) == 5 else f"{code_str}0"
                mrow = master[master["Code"].astype(str).isin([code_str, code_5])]
                if mrow.empty:
                    st.error(f"銘柄 {code_str} がマスタに見つかりません")
                else:
                    actual_code = str(mrow.iloc[0]["Code"])
                    name = str(mrow.iloc[0].get("CoName", ""))
                    result = evaluate_sell_signals(
                        daily_df=daily_all,
                        code=actual_code,
                        name=name,
                        entry_date=pos_entry_date,
                        entry_price=pos_entry_price,
                        stop_loss=pos_stop_loss,
                        take_profit=pos_take_profit,
                    )

                    if result is None:
                        st.error("評価できませんでした。日足データが不足している可能性があります")
                    else:
                        # サマリー表示
                        display_code = actual_code[:4] if len(actual_code) == 5 and actual_code.endswith("0") else actual_code
                        st.markdown(f"### {display_code} {result.name}")

                        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                        col_m1.metric("現在価格", f"{result.current_price:.0f} 円")
                        col_m2.metric("エントリー", f"{result.entry_price:.0f} 円")
                        col_m3.metric("損益", f"{result.pct_change:+.2f}%")
                        col_m4.metric("保有日数", f"{result.days_held} 営業日")

                        # 総合推奨度を大きく表示
                        rec = result.recommendation
                        if "即時損切" in rec:
                            st.error(f"## {rec}")
                        elif "強い売り推奨" in rec:
                            st.warning(f"## {rec}")
                        elif "売り検討" in rec:
                            st.warning(f"## {rec}")
                        elif "兆候あり" in rec:
                            st.info(f"## {rec}")
                        else:
                            st.success(f"## {rec}")

                        # シグナル詳細
                        st.markdown("---")
                        st.markdown(f"**検出された売りシグナル: {len(result.signals)}件**")
                        if result.signals:
                            for s in result.signals:
                                severity_color = {
                                    "URGENT": "🔴",
                                    "STRONG": "🟠",
                                    "MODERATE": "🟡",
                                    "MILD": "🟢",
                                }.get(s.severity, "⚪")
                                st.markdown(f"### {severity_color} {s.label}")
                                st.markdown(f"- {s.description}")
                                st.caption(f"　 根拠: {s.book_reference}")
                        else:
                            st.success("売りシグナルなし。現在のポジションを継続してOK")

                        # 損切・利確ライン情報
                        st.markdown("---")
                        st.markdown("**📋 設定したリスクリワード**")
                        st.markdown(
                            f"- 損切ライン: **{result.stop_loss:.0f} 円**"
                            f" ({(result.stop_loss - result.entry_price) / result.entry_price * 100:+.1f}%)"
                        )
                        st.markdown(
                            f"- 利確目標: **{result.take_profit:.0f} 円**"
                            f" ({(result.take_profit - result.entry_price) / result.entry_price * 100:+.1f}%)"
                        )
                        if result.stop_loss > 0 and result.take_profit > 0:
                            risk = result.entry_price - result.stop_loss
                            reward = result.take_profit - result.entry_price
                            if risk > 0:
                                st.markdown(f"- RR比: **1 : {reward/risk:.2f}**")

                        # メンタル管理メモ
                        st.markdown("---")
                        st.markdown("**📖 書籍5時限目 メンタル管理メモ**")
                        st.markdown("""
                        - **「頂点で利確」は結果論**。自分の利確基準を機械的に守ることが重要
                        - **損失時の苦痛は同額の利益の2倍以上感じる**（プロスペクト理論）
                        - **損切は遅らせない**。逆指値で自動執行が基本
                        - **含み益でルール変更しない**。トレーリングストップは引き上げのみOK
                        """)
    else:
        st.info("銘柄情報を入力して「📊 売り判断を実行」を押してください")

