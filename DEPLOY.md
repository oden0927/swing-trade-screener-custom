# Streamlit Cloud デプロイ手順

このアプリを GitHub + Streamlit Cloud で公開し、iPhone/iPad から見られるようにする手順です。

## 全体像

```
[ローカル Mac]                       [GitHub]                    [Streamlit Cloud]
コード編集・データ取得  ─push→  プライベートリポジトリ  ─自動デプロイ→  Webアプリ公開
                                                                         ↓
                                                              iPhone/iPad/PC から閲覧
```

---

## Phase 1: Gitと GitHub の準備

### 1-1. Gitが入っているか確認

ターミナルで実行：

```bash
git --version
```

→ `git version 2.x.x` のような表示が出れば OK。出ない場合は次のコマンドでインストール：

```bash
xcode-select --install
```

### 1-2. Gitの初期設定（初回のみ）

ターミナルで（YOUR_NAMEとYOUR_EMAILは自分のものに置き換え）：

```bash
git config --global user.name "YOUR_NAME"
git config --global user.email "YOUR_EMAIL"
git config --global init.defaultBranch main
```

### 1-3. GitHubアカウント作成

https://github.com にアクセスして、無料アカウントを作成（既にあればスキップ）。

### 1-4. 新しいプライベートリポジトリを作成

1. GitHub にログイン
2. 右上の「+」→「New repository」
3. 設定：
   - Repository name: `swing-trade-screener` （任意）
   - **Private** にチェック（重要：パブリックにすると誰でも見られます）
   - その他はデフォルトのまま
4. 「Create repository」をクリック
5. 表示されたURLをメモ：例 `https://github.com/your-username/swing-trade-screener.git`

---

## Phase 2: ローカルからGitHubへPush

### 2-1. ターミナルでscreenerフォルダに移動

```bash
cd "/Users/kabu/Documents/suingu toredo/screener"
```

### 2-2. Gitリポジトリの初期化

```bash
git init
git branch -M main
```

### 2-3. GitHubリポジトリと紐付け

（URLは Phase 1-4 でメモしたものに置き換え）

```bash
git remote add origin https://github.com/your-username/swing-trade-screener.git
```

### 2-4. 全ファイルをステージング、コミット

```bash
git add .
git commit -m "Initial commit: スイングトレードスクリーナー"
```

**注意**: `.env` は `.gitignore` で除外されているので、API キーが公開されることはありません。

### 2-5. GitHubへpush

```bash
git push -u origin main
```

→ 初回はGitHubの認証が求められます。Personal Access Token を使う必要があります：

1. GitHub右上のプロフィール → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 「Generate new token」
3. Note: 適当な名前
4. Expiration: お好み（90日推奨）
5. Scopes: `repo` だけチェック
6. Generate
7. 出てきたトークンをコピー（一度しか表示されません）

pushのときの「Password」欄にこのトークンを貼り付け。

---

## Phase 3: Streamlit Cloud にデプロイ

### 3-1. アカウント作成

1. https://streamlit.io/cloud にアクセス
2. 「Sign up」→ GitHubで認証

### 3-2. アプリをデプロイ

1. ダッシュボードで「New app」をクリック
2. 設定：
   - Repository: `your-username/swing-trade-screener`
   - Branch: `main`
   - Main file path: `web_app.py`
3. 「Deploy!」をクリック

### 3-3. APIキーを Secrets に設定（重要）

デプロイが始まったら、すぐに：

1. アプリ画面の右下「⋮」→「Settings」→「Secrets」
2. 次の内容を貼り付け（API キーは自分のものに）：

```toml
JQUANTS_API_KEY = "あなたのjquants APIキー"
```

3. 「Save」をクリック
4. アプリが自動再起動して、jquants に接続できるようになる

### 3-4. デプロイURLを確認

数分でデプロイ完了。URL は次のような形式：

```
https://your-app-name.streamlit.app/
```

このURLを iPhone/iPad の Safari でブックマークすれば、どこからでもアクセスできます。

---

## Phase 4: 日々の運用

### 4-1. 株価データの更新

クラウド側は jquants にアクセスしないので、**Mac側でデータを取得 → push する** 必要があります。

```bash
cd "/Users/kabu/Documents/suingu toredo/screener"
source .venv/bin/activate
python main.py fetch
```

データ取得が終わったら：

```bash
git add data/
git commit -m "データ更新 $(date +%Y-%m-%d)"
git push
```

→ Streamlit Cloud が自動で最新データを反映してくれます。

### 4-2. コード変更後のデプロイ

スコアリングや設定を変更した場合も同じ：

```bash
git add .
git commit -m "設定変更: ..."
git push
```

→ 自動的にクラウド側も更新されます。

### 4-3. 推奨運用フロー（毎日）

1. **15時以降に Mac で**: `python main.py fetch` でデータ更新
2. **commit & push**: `git add data/ && git commit -m "data update" && git push`
3. **iPhone/iPad で**: ブックマークから Streamlit Cloud URL を開いて確認

---

## トラブルシューティング

### push 時に認証エラー

→ Personal Access Token を使っているか確認。パスワードでは認証できません。

### Streamlit Cloud で「ModuleNotFoundError」

→ `requirements.txt` に必要なライブラリが全部入っているか確認。

### APIキーエラー

→ Secrets に正しく設定されているか確認。`JQUANTS_API_KEY = "..."` のように **クォートで囲む** こと。

### データが古い

→ 最後に Mac でデータ取得＆push した日付がそのままになります。毎日 push してください。

### GitHub のリポジトリサイズが大きすぎる

→ Parquet ファイルが数十MB あるため、リポジトリは数百MB になる可能性があります。
GitHub の無料プランは1GBまで OK なので問題ないですが、気になる場合は Git LFS の利用も検討。

---

## セキュリティチェックリスト

- [ ] GitHubリポジトリは **Private** になっている
- [ ] `.env` は `.gitignore` に含まれている
- [ ] `data/cache/` も除外されている
- [ ] Streamlit Cloud の Secrets で APIキーを管理している
- [ ] Personal Access Token は安全に保管している
