# スイングトレード スクリーナー

『世界一やさしい スイングトレードの教科書1年生』（ロット著）のロジックを忠実に実装した、jquants Premium 連携の買い候補抽出ツール。

## できること

- jquants Premium から日本株（日経225・JPX400相当）の日足データを取得
- 全体地合いを TOPIX で判定し、**下落相場ではアラートを出して買い候補を抑制**（買い相場のみで動かす）
- 個別銘柄を本書のルール（移動平均線、ライン分析、一目均衡表、日柄など）でスコアリング
- 該当する本書のページ・節を引用しながら、**「どこから入ってどこで切るか」まで具体提示**
- HTML レポートで一覧表示（ブラウザで開ける）
- **Web UI（Streamlit）**: 日付ピッカーでインタラクティブにスクリーニング

## セットアップ

### 1. Python と依存ライブラリのインストール

```bash
cd "/Users/kabu/Documents/suingu toredo/screener"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. jquants Premium V2 APIキーの設定

jquants V2 は **APIキー方式** です（2025/12/22以降登録の方は V2 のみ）。

```bash
cp .env.example .env
open -a TextEdit .env
```

`.env` を開いて、jquants ダッシュボード ( https://jpx-jquants.com/ja/dashboard ) で発行した APIキーを `JQUANTS_API_KEY` に貼り付けて保存します。

```
JQUANTS_API_KEY=ここに発行されたAPIキー
```

APIキーは期限なしですが、再発行・削除が可能です。

### 3. データの初回取得（30分〜1時間かかる場合あり）

```bash
python main.py fetch
```

過去3年分の日足データを全銘柄分取得し、`data/raw/*.parquet` に保存します。
次回以降は差分取得のみなので数分で済みます。

### 4. スクリーニング実行

```bash
python main.py screen
```

`reports/screen_YYYYMMDD_HHMM.html` と `reports/latest.html` が生成されます。
ブラウザで開くと買い候補とその売買進め方が見られます。

### 5. fetch + screen を一括実行

```bash
python main.py all
```

### 6. Web UI（ブラウザ操作）

ターミナルだけでなく、ブラウザでも操作できます。

```bash
streamlit run web_app.py
```

実行すると自動的にブラウザが開き、`http://localhost:8501` にアクセスできます。

- **現在のスクリーニング** / **過去日付で再現** を選択できる
- 日付ピッカーで簡単に過去シグナルを呼び出せる
- 候補をクリックで展開、チャートをその場で表示
- スコア分布や地合いをサマリー表示

Web UI を停止するには、ターミナルで `Ctrl+C`。

## 毎日の運用フロー

本書「終値で判断して翌朝までに発注」ルールに合わせ、**毎日15時以降に手動実行** が想定です：

1. ターミナルで `cd "/Users/kabu/Documents/suingu toredo/screener"`
2. `source .venv/bin/activate`
3. `python main.py all`
4. `open reports/latest.html` で確認
5. 気になる候補があれば発注を翌朝までに準備

## スクリーニングロジック

5段階で絞り込みます（書籍出典付き）：

| Phase | 内容 | 出典 |
|---|---|---|
| 0 | ユニバース絞り込み（市場・出来高・財務・決算カレンダー） | 0時限目03 / 6時限目01 / 8時限目01 |
| 1 | 全体地合い判定（TOPIXで上昇/ボックス/下落） | 4時限目02 / 8時限目01 |
| 2 | 個別環境認識（株価とMAの関係で3トレンド判定） | 2時限目01-03 / 4時限目02① |
| 3 | 買いパターン該当判定（3パターン+加点要素+減点要素） | 4時限目02-03 |
| 4 | 買いトリガー（5日MA超え/サポート反発/新高値ブレイク） | 4時限目02③ / 02 / 03 |
| 5 | リスクリワード設計（損切/利確/RR比） | 5時限目 |

## 出力レポートの読み方

各候補について以下が表示されます：

- **総合スコア**: パターン+加点-減点 の合計
- **該当する本書パターン**: 4時限目何節・何ページに相当するか
- **買いトリガー**: 5日MA超え/サポート反発/新高値再エントリーのどれが出ているか
- **売買進め方**: エントリー価格・損切ライン・利確目標・RR比（書籍5時限目に準拠）
- **売り判断基準**: 利確トリガーと損切トリガー（5時限目）
- **メンタル運用注意**: 該当する書籍記述

## トラブルシューティング

### `jquants-api-client` がインストールできない
Python 3.10 以上が必要です。`python3 --version` で確認してください。

### 認証エラー
jquants Premium に登録されているメールアドレスとパスワードが正しいか、または refresh token が有効期限内（発行から1週間）か確認してください。

### データ取得が遅い
初回は全銘柄×3年分なので30分〜1時間かかります。2回目以降は差分のみなので数分です。

## 今後の拡張候補

- 監視リスト機能（手動セレクトしたN銘柄だけ毎日通知）
- アラート通知（メール/LINE）
- バックテスト機能（本書のチャート例で再現性チェック）
- 個別銘柄の詳細チャート可視化（mplfinanceで描画）
- 業種別指数を使った地合い判定の高度化

## ファイル構成

```
screener/
├── .env.example              # 認証情報テンプレート
├── .gitignore
├── requirements.txt          # 依存パッケージ
├── README.md
├── config.py                 # 設定（書籍記述値を定数化）
├── main.py                   # CLI エントリ
├── data/
│   ├── raw/                  # jquants から取得した生データ
│   └── cache/                # 計算済み中間データ
├── reports/                  # HTML レポート出力先
└── src/
    ├── jquants_client.py     # jquants API ラッパー
    ├── data_fetcher.py       # データ取得
    ├── indicators.py         # MA・一目均衡表・RSI・ライン分析
    ├── environment.py        # 相場環境判定（2時限目）
    ├── universe.py           # Phase 0（0/6/8時限目）
    ├── patterns.py           # Phase 3（4時限目）
    ├── triggers.py           # Phase 4
    ├── risk_reward.py        # Phase 5（5時限目）
    ├── screener.py           # オーケストレータ
    ├── reporter.py           # HTML生成
    └── templates/
        └── screen_report.html.j2
```

## 免責

本ツールは『世界一やさしい スイングトレードの教科書1年生』（ロット著）の記述を元にAIが自動抽出・整理した売買候補と参考情報を提示するものです。最終的な投資判断はご自身の責任で行ってください。
