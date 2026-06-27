# 📱 スマホだけでセットアップする手順

PCがなくても、**スマホのブラウザだけ**でセットアップできます。
難所の「GitHubへのファイル配置」は付属の Colab ノートブック
（`setup_from_phone.ipynb`）が自動でやってくれます。

---

## 全体の流れ

```
① 各種キーをスマホで取得（Gemini / LINE / GitHub PAT）
        ↓
② Colabでノートブックを実行（Garminトークン生成 → GitHubへ自動配置）
        ↓
③ GitHubで秘密情報を登録 → 自動実行スタート
```

所要時間はおよそ20〜30分。トークン類の取得が初めてだと少し時間がかかります。

---

## ① 事前に取得するもの（すべてスマホで）

### Gemini APIキー
1. ブラウザで `aistudio.google.com` を開きGoogleでログイン
2. 「Get API key」→「Create API key」→ 表示された文字列をコピー（メモアプリに保存）

### LINE（チャネルアクセストークン＋ユーザーID）
1. `developers.line.biz/console/` にLINEでログイン
2. プロバイダー作成 →「新規チャネル作成」→「Messaging API」
3. 「Messaging API設定」タブ →「チャネルアクセストークン（長期）」を発行してコピー
4. 「チャネル基本設定」タブ →「あなたのユーザーID」（U始まり）をコピー
5. Botを**友だち追加**（同タブの友だち追加リンク／Bot ID検索から。これをしないと届きません）

> ※ 画面操作はスマホだとやや窮屈です。ブラウザを「PC版サイトを表示」にすると操作しやすくなります。

### GitHub アカウントと個人アクセストークン(PAT)
1. `github.com` でアカウント作成／ログイン
2. Settings → Developer settings → Personal access tokens →
   **Tokens (classic)** →「Generate new token (classic)」
3. スコープ **repo** と **workflow** にチェックして発行 → 文字列をコピー
   （この画面を離れると二度と表示されないので必ず保存）

> 各キーの詳細は `README.md` 第2章も参照。

---

## ② Colab でノートブックを実行

1. ブラウザで `colab.research.google.com` を開きGoogleでログイン
2. 「ノートブックを開く」→「アップロード」→ `setup_from_phone.ipynb` を選択
   （ファイルはこのパッケージ内。スマホの「ファイル」アプリ等から選べます）
3. 上のセルから順に再生ボタンを押して実行:
   - **手順1**: ライブラリのインストール
   - **手順2**: Garminのメール・パスワード（必要ならMFAコード）を入力 → トークン生成
   - **手順3**: GitHubのPATとリポジトリ名を入力 → リポジトリ作成＆ファイル自動アップロード

実行後、作成されたリポジトリのURLが表示されます。

> Colabはデータセンターから動くため、ごく稀に手順2のGarminログインが弾かれます。
> その場合は数分おいて再実行してください。それでもダメなら「PCを一度だけ借りる」のが確実です。

---

## ③ 秘密情報を登録して自動実行スタート

ファイル配置までは自動で終わっています。最後に秘密情報だけ手動で登録します（安全のため）。

1. 作成されたリポジトリを開く
2. **Settings → Secrets and variables → Actions**
3. **Secrets** タブで次の4つを登録（「New repository secret」）:

   | Name | Value |
   |------|-------|
   | `GARMIN_TOKENS` | 手順2で生成（ノートブック最後のセルで再表示できます） |
   | `GEMINI_API_KEY` | Gemini APIキー |
   | `LINE_CHANNEL_ACCESS_TOKEN` | LINEチャネルアクセストークン |
   | `LINE_USER_ID` | LINEユーザーID |

4. （任意）**Variables** タブで目標を登録:
   `GOAL_MARATHON_TIME` / `GOAL_RACE_PACE` / `RUNNER_PROFILE` / `GEMINI_MODEL`
5. **Actions** タブでワークフローを有効化
6. 「Weekly Running Report」→「**Run workflow**」で手動実行 → LINEに届けば完了 🎉

以降は毎週月曜 7:00（日本時間）に自動でレポートが届きます。

---

## 手動でやる場合（ノートブックを使わない方法）

Colabを使わずGitHubのブラウザ操作だけでも可能です（やや手間）。

1. GitHubでリポジトリを新規作成
2. 「Add file」→「Create new file」で、ファイル名に
   `.github/workflows/weekly-report.yml` などパスを直接入力し、中身を貼り付けてコミット
   （これを各ファイル分くり返す。`.github/` を含むパスもこの方法なら作れます）
3. Garminトークンだけは別途生成が必要 → `README.md` の「スマホでトークン生成」または
   付属ノートブックの手順2のセルだけ実行
4. あとは上記③と同じ

---

## トラブル時

| 症状 | 対処 |
|------|------|
| 手順2でGarminログイン失敗 | 数分待って再実行。続く場合はPCを一度だけ借りて `setup_garmin_token.py` |
| 手順3で 401/403 | PATのスコープに **repo** と **workflow** が入っているか確認 |
| 手順3で workflow ファイルだけ失敗 | PATに **workflow** スコープが必要 |
| LINEに届かない | Botを友だち追加したか／`LINE_USER_ID` が正しいか |
| Actionsが動かない | リポジトリのActionsを有効化したか／デフォルトブランチか |
