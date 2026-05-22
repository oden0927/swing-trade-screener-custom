"""設定とパス管理。.env を読み込み、各モジュールから参照される。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# プロジェクトルート（このファイルの親ディレクトリ）
ROOT_DIR = Path(__file__).resolve().parent

# .env を読む（プロジェクトルートを優先）
load_dotenv(ROOT_DIR / ".env")

# データ保存先
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"          # jquants から取得した生データ
CACHE_DIR = DATA_DIR / "cache"      # 計算済み指標などの中間データ
REPORT_DIR = ROOT_DIR / "reports"   # HTML レポート出力先

for d in (RAW_DIR, CACHE_DIR, REPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 認証情報（V2 API はAPIキー方式）
JQUANTS_API_KEY = os.getenv("JQUANTS_API_KEY", "")
# V2 API のベースURL
JQUANTS_API_BASE = "https://api.jquants.com/v2"

# 取得期間
DAILY_LOOKBACK_YEARS = int(os.getenv("DAILY_LOOKBACK_YEARS", "3"))
MONTHLY_LOOKBACK_YEARS = int(os.getenv("MONTHLY_LOOKBACK_YEARS", "10"))

# スクリーニング設定
UNIVERSE = os.getenv("UNIVERSE", "BOTH").upper()  # JPX400, NIKKEI225, BOTH
MIN_AVG_VOLUME = int(os.getenv("MIN_AVG_VOLUME", "500000"))
MAX_WATCHLIST_SIZE = int(os.getenv("MAX_WATCHLIST_SIZE", "20"))

# 本書に登場する重要数値（書籍記述ベース）
# 移動平均線設定（2時限目）
SHORT_MA = 5
MID_MA = 20
LONG_MA = 60
ULTRA_LONG_MA = 200

# 一目均衡表（3時限目06）
ICHIMOKU_TENKAN = 9
ICHIMOKU_KIJUN = 26
ICHIMOKU_SENKOU_B = 52

# 日柄分析（3時限目05, 5時限目）
JIGARA_SHORT = 9    # 短期日柄
JIGARA_MID = 17     # 中期日柄
JIGARA_LONG = 26    # 長期日柄
TREND_MIN_DAYS = 60   # 3カ月 = 約60営業日
TREND_MAX_DAYS = 120  # 6カ月 = 約120営業日

# 利確・損切（5時限目）
DEFAULT_RR_RATIO = 2.0    # リスクリワード1:2
LOSS_CUT_TICKS = 10       # 過去安値・サポートラインから10ティック離す（バックテスト63%損切到達対策）

# スコア上限ハード除外（バックテストでスコア150+は勝率28.6%、平均-2.46%）
MAX_SCORE_THRESHOLD = 150

# 最低スコア閾値
# 最新3年バックテスト (2026-05-23 / 10,559件) で確認された品質ジャンプ点:
#   ベース（全候補）: 勝率52.4%、期待値+0.65%
#   20以上:           勝率53.8%、期待値+0.92% (+1.4pt品質ジャンプ)
#   80以上:           勝率56.6%、期待値+1.10% (プレミアム候補)
MIN_SCORE_THRESHOLD = 20

# プレミアム候補のスコア閾値（UI表示で「特に注目すべき候補」として強調する）
# 3年実証で勝率56.6%・期待値+1.10% の明確な品質ジャンプ点
PREMIUM_SCORE_THRESHOLD = 80

# 20MA乖離率のハード除外（3年バックテストで20%超は勝率36.3%、平均-1.39%）
MAX_MA20_DEVIATION = 0.20

# 決算発表前後の除外日数（8時限目01-3）
EARNINGS_AVOIDANCE_DAYS = 7

# RSI（3時限目08）
# 標準的なRSI水準（一般的な解釈）:
#   70以上: 過買い圏（買われすぎ）
#   30未満: 過売り圏（売られすぎ）
#   約50  : 中立
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
RSI_NEUTRAL = 50

# MACD（移動平均収束発散）標準設定:
#   高速EMA   : 12期間
#   低速EMA   : 26期間
#   シグナル線: 9期間（MACD線のEMA）
# 現状はカスタム版で「計算と表示」のみ。スコアには未反映（バックテストで効果検証後に判断）。
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 業種コード（S33）で除外したい業種
# 「製薬・医薬品」「化学」など、サプライズが起きやすい業種
# 8時限目で著者が「日跨ぎ注意」と言及した業種に対応
EARNINGS_SENSITIVE_S33_CODES = {
    "3250",  # 医薬品
    "3050",  # 化学（一部、製薬関連を含む）
}

# 出力フォーマット
REPORT_TEMPLATE_NAME = "screen_report.html.j2"
