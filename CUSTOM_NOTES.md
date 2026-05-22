# カスタム版（自分流のアレンジを試す場所）

このフォルダは `screener` をコピーして作成された **実験用** のディレクトリです。

## このフォルダの目的

- 本忠実版 (`screener/`) は触らず、そのまま安定運用
- このフォルダ (`screener-custom/`) で自由にロジック追加・変更
- 例：モメンタム指標の追加、別の売買ルール、新しいパターン検出など

## 元になっているバージョン

- コピー元: `/Users/kabu/Documents/suingu toredo/screener/`
- コピー日時: 2026-05-22
- 本忠実版の最終バックテスト実力値: 10日勝率52.5%、期待値+0.65%（3年データ）

## 初期セットアップ

このフォルダで作業を始めるには、まずPython仮想環境を作る必要があります（.venvはコピーしていないため）：

```bash
cd "/Users/kabu/Documents/suingu toredo/screener-custom"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`.env` ファイルはすでにコピー済みなので、APIキー設定は不要です。

## 動作確認

セットアップ後、念のため動くか確認：

```bash
python main.py screen
```

または Web UI：

```bash
streamlit run web_app.py
```

→ ポート番号が同時起動だとぶつかるので、本忠実版を止めるか、`--server.port 8502` で別ポート使用：

```bash
streamlit run web_app.py --server.port 8502
```

## アレンジのアイデア

### 1. モメンタム指標の追加
- RSI を 14日ではなく 6日にする（短期モメンタム）
- ROC（Rate of Change）を追加
- ADX（トレンドの強さ）を追加

### 2. 新しい買いパターン
- カップウィズハンドル（書籍ではあるが現状未実装）
- ダブルボトム
- ブレイクアウト後の押し目買い（より詳細な条件）

### 3. ファンダメンタル要素
- ROE 高い銘柄を加点
- 自己資本比率
- 配当利回り

### 4. テーマ別フィルタ
- AI関連銘柄だけ
- 半導体関連だけ
- 円安メリット銘柄だけ

### 5. 売買ルールの変更
- 損切ラインを ATR ベースに変更
- リスクリワード比 を 1:3 に変更
- 利確を トレーリングストップで段階的に

## 別のGitHubリポジトリにする場合

`screener-custom` を別リポジトリとして管理したい場合：

```bash
cd "/Users/kabu/Documents/suingu toredo/screener-custom"
git init
git branch -M main
# GitHubで新リポジトリを作成（例: swing-trade-screener-custom）
git remote add origin https://github.com/oden0927/swing-trade-screener-custom.git
git add .
git commit -m "Initial commit: カスタム版"
git push -u origin main
```

その後 Streamlit Cloud で別アプリとしてデプロイすれば、本忠実版と並行して別URLでアクセスできます。

## 注意事項

- 本忠実版とは **独立した実験場所** として使ってください
- 変更は本忠実版に影響しません
- アレンジで「これは良い！」となったものは、本忠実版にも反映するかご検討ください
