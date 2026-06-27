# Garmin 週次ランニングレポート（Gemini分析版）

Garmin Connect から直近4週間のランニングデータを取得し、Gemini（無料枠）で
コーチ視点の分析を生成して、毎週 LINE に通知するツールです。

```
🏃 週次ランニングレポート
📅 2026年06月27日

📊 今週のサマリー
  走行回数   : 4 回
  総距離     : 41.5 km
  ...
──────────────
（Geminiによるコーチング講評）
```

---

> 📱 **PCを持っていない／スマホだけで設定したい方へ**: `SMARTPHONE_SETUP.md` と
> 付属の Colab ノートブック `setup_from_phone.ipynb` を使うと、スマホのブラウザだけで
> セットアップできます。以下の手順はPCで行う場合の説明です。

## 1. 必要なもの

- Python 3.10 以上（PCで動かす場合。スマホのみなら不要）
- Garmin Connect のアカウント（メール＋パスワードでログインできること）
- Google アカウント（Gemini APIキー取得用）
- LINE アカウント（通知の受信用）

> 注意: 本ツールは Garmin の**非公式**ライブラリ（garminconnect）を使用します。
> Garmin 側の仕様変更で動かなくなる可能性があります。個人利用の範囲でお使いください。

---

## 2. APIキー・認証情報の取得

設定する値は次の5つです。取得方法を順に説明します。

| 設定項目 | 内容 |
|----------|------|
| `[garmin] email / password` | Garmin Connect のログイン情報 |
| `[gemini] api_key` | Gemini APIキー |
| `[line] channel_access_token` | LINE チャネルアクセストークン |
| `[line] user_id` | 自分の LINE ユーザーID |

### 2-1. Gemini APIキー（無料）

1. ブラウザで **Google AI Studio**（`https://aistudio.google.com/`）にアクセスし、Googleアカウントでログイン
2. 左メニューまたは右上の「**Get API key（APIキーを取得）**」をクリック
3. 「**Create API key（APIキーを作成）**」を選び、プロジェクトを選択して作成
4. 表示された文字列をコピー → `config.ini` の `api_key` に貼り付け

- クレジットカード登録は不要です。
- 無料枠では gemini-2.5-flash が 1日250リクエスト・10 RPM 使えます（週1回の実行なら十分）。
- **無料枠ではプロンプト・応答がGoogleの品質改善に使われる場合があります**。気になる場合は
  Google Cloud で課金を有効化（Tier 1）すると学習対象外になります（従量課金。週1実行なら極小額）。

### 2-2. LINE（チャネルアクセストークン＋ユーザーID）

> 旧「LINE Notify」は 2025年3月末で終了したため、現在は **Messaging API** を使います。

**(A) Messaging API チャネルを作る**

1. **LINE Developers**（`https://developers.line.biz/console/`）にLINEアカウントでログイン
2. 「**プロバイダーを作成**」→ 任意の名前（例: 自分の名前）で作成
3. そのプロバイダー内で「**新規チャネル作成**」→ 「**Messaging API**」を選択
   （公式アカウント作成フローに進む場合は、画面の案内に従って作成してください）
4. チャネル名・業種などを入力して作成

**(B) チャネルアクセストークンを取得**

5. 作成したチャネルを開き、「**Messaging API設定**」タブを選択
6. 画面下部の「**チャネルアクセストークン（長期）**」の「**発行**」をクリック
7. 表示された文字列をコピー → `config.ini` の `channel_access_token` に貼り付け

**(C) 自分のユーザーIDを取得**

8. 同じチャネルの「**チャネル基本設定**」タブを開く
9. 下の方にある「**あなたのユーザーID**」（`U` で始まる文字列）をコピー
   → `config.ini` の `user_id` に貼り付け
   （表示されない場合はページを再読み込み）

**(D) Botを友だち追加（重要）**

10. 「Messaging API設定」タブに表示される **QRコード** を、自分のスマホのLINEで読み取り、
    作成したBotを**友だち追加**します。これをしないと通知が届きません。

- 自動応答メッセージはオフでも構いません。
- 無料プランでも月200通まで送信できます（週1回なら余裕）。
- **トークンとユーザーIDは他人に渡さないでください**（不正送信に悪用される恐れがあります）。

### 2-3. Garmin（ログイン情報）

`config.ini` の `[garmin]` に、普段使っている Garmin Connect の
メールアドレスとパスワードを記入するだけです。

- 2段階認証（MFA）を有効にしていると、非公式ライブラリではログインに失敗することがあります。
  うまくいかない場合は、まず手動実行で挙動を確認してください。

---

## 3. 環境準備

### 3-1. Windows

1. **Python のインストール**
   - `https://www.python.org/downloads/` から最新版をダウンロードしてインストール
   - インストーラ最初の画面で「**Add Python to PATH**」に**必ずチェック**
2. インストール確認（コマンドプロンプトで）:
   ```cmd
   python --version
   ```
3. 本ツールのフォルダを任意の場所に展開（例: `C:\tools\garmin-weekly-report`）
4. そのフォルダで仮想環境を作成して有効化（推奨）:
   ```cmd
   cd C:\tools\garmin-weekly-report
   python -m venv .venv
   .venv\Scripts\activate
   ```
5. 依存パッケージをインストール:
   ```cmd
   pip install -r requirements.txt
   ```
6. 設定ファイルを作成:
   ```cmd
   copy config.example.ini config.ini
   ```
   `config.ini` をメモ帳などで開き、第2章で取得した値を記入して保存。

### 3-2. macOS

1. **Python のインストール**（どちらかでOK）
   - `https://www.python.org/downloads/` の公式インストーラ、または
   - Homebrew: `brew install python`
2. インストール確認（ターミナルで）:
   ```bash
   python3 --version
   ```
3. 本ツールのフォルダを任意の場所に展開（例: `~/tools/garmin-weekly-report`）
4. 仮想環境を作成して有効化（推奨）:
   ```bash
   cd ~/tools/garmin-weekly-report
   python3 -m venv .venv
   source .venv/bin/activate
   ```
5. 依存パッケージをインストール:
   ```bash
   pip install -r requirements.txt
   ```
6. 設定ファイルを作成:
   ```bash
   cp config.example.ini config.ini
   ```
   `config.ini` をエディタで開き、第2章で取得した値を記入して保存。

---

## 4. 動作確認（手動実行）

設定が終わったら、まず手動で実行して通知が届くか確認します。

- Windows:
  ```cmd
  .venv\Scripts\activate
  python garmin_weekly_report.py
  ```
- macOS:
  ```bash
  source .venv/bin/activate
  python3 garmin_weekly_report.py
  ```

LINE に通知が届けば成功です。詳細な実行ログは同じフォルダの `garmin_report.log` に出力されます。

---

## 5. 自動実行のスケジュール設定（自分のPCで動かす場合）

毎週月曜の朝などに自動実行する設定です。**仮想環境内のPython**を絶対パスで指定するのがコツです。

> PCを起動しっぱなしにしたくない／PCを持たない人に使わせたい場合は、
> 第6章「PCレス運用（GitHub Actions）」を参照してください。

### 5-1. Windows（タスクスケジューラー）

1. スタートメニューで「**タスク スケジューラ**」を開く
2. 右側「**基本タスクの作成**」をクリック
3. 名前: `Garmin週次レポート` →「次へ」
4. トリガー: 「**毎週**」→ 曜日「**月曜日**」、開始時刻（例 7:00）を指定
5. 操作: 「**プログラムの開始**」を選択
6. 次のように設定:
   - **プログラム/スクリプト**:
     `C:\tools\garmin-weekly-report\.venv\Scripts\pythonw.exe`
     （`pythonw.exe` にすると黒い画面が出ません。なければ `python.exe`）
   - **引数の追加**: `garmin_weekly_report.py`
   - **開始（作業フォルダー）**: `C:\tools\garmin-weekly-report`
7. 「完了」。必要なら作成後にプロパティを開き、
   「**ユーザーがログオンしているかどうかにかかわらず実行する**」にチェック。

### 5-2. macOS（launchd 推奨）

1. 次の内容で `~/Library/LaunchAgents/com.user.garminreport.plist` を作成
   （パスは自分の環境に合わせて書き換え。`Weekday` の 1 = 月曜、Hour/Minute で時刻指定）:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>Label</key>
       <string>com.user.garminreport</string>
       <key>ProgramArguments</key>
       <array>
           <string>/Users/あなたのユーザー名/tools/garmin-weekly-report/.venv/bin/python3</string>
           <string>/Users/あなたのユーザー名/tools/garmin-weekly-report/garmin_weekly_report.py</string>
       </array>
       <key>WorkingDirectory</key>
       <string>/Users/あなたのユーザー名/tools/garmin-weekly-report</string>
       <key>StartCalendarInterval</key>
       <dict>
           <key>Weekday</key><integer>1</integer>
           <key>Hour</key><integer>7</integer>
           <key>Minute</key><integer>0</integer>
       </dict>
       <key>StandardOutPath</key>
       <string>/Users/あなたのユーザー名/tools/garmin-weekly-report/launchd.out.log</string>
       <key>StandardErrorPath</key>
       <string>/Users/あなたのユーザー名/tools/garmin-weekly-report/launchd.err.log</string>
   </dict>
   </plist>
   ```

2. 登録（読み込み）:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.user.garminreport.plist
   ```
3. 解除したいとき:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.user.garminreport.plist
   ```

> cron でも可能です（`crontab -e` に `0 7 * * 1 /フルパス/.venv/bin/python3 /フルパス/garmin_weekly_report.py`）。
> ただし最近のmacOSではcronに「フルディスクアクセス」権限が必要な場合があり、launchd の方が確実です。

---

## 6. PCレス運用（GitHub Actions で自動実行）

PCを起動していなくても、**GitHub のクラウド上**で毎週自動実行できます。週1回なら無料枠で十分です。
設定値は `config.ini` の代わりに **GitHub Secrets（環境変数）** で渡します（環境変数が優先されます）。

### 6-1. Garmin トークンを生成（最初に1回だけ・自分のPC）

クラウドから毎回パスワードでログインすると Garmin にブロックされやすいため、
**保存済みトークンでログイン**します。まず手元のPCでトークンを作ります。

```bash
# 依存をインストール済みの環境で
python setup_garmin_token.py        # Windowsは python、Macは python3
```

メール・パスワード（必要ならMFAコード）を入力すると、長い**トークン文字列**が表示されます。
これを次の手順で Secret `GARMIN_TOKENS` に登録します。トークンの有効期限は約1年です。

### 6-2. リポジトリを用意

1. このフォルダ一式を自分の **GitHubリポジトリ**にアップロード（**private 推奨**）
   - `config.ini` は**絶対に含めない**でください（`.gitignore` で除外済み）
   - `.github/workflows/weekly-report.yml` が含まれていることを確認

### 6-3. Secrets と Variables を登録

リポジトリの **Settings → Secrets and variables → Actions** で登録します。

**Secrets（秘密情報）タブ**:

| 名前 | 値 |
|------|----|
| `GARMIN_TOKENS` | 6-1で生成したトークン文字列 |
| `GEMINI_API_KEY` | Gemini APIキー |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINEチャネルアクセストークン |
| `LINE_USER_ID` | 自分のLINEユーザーID |

> トークンを使わずメール/パスワードで運用する場合は、代わりに `GARMIN_EMAIL` と
> `GARMIN_PASSWORD` を登録します（クラウドではブロックされやすいため非推奨）。

**Variables（秘密でない設定）タブ**（任意・未設定でも既定値で動きます）:

| 名前 | 値の例 |
|------|--------|
| `GEMINI_MODEL` | `gemini-2.5-flash` |
| `GOAL_MARATHON_TIME` | `3時間30分` |
| `GOAL_RACE_PACE` | `4:58/km` |
| `RUNNER_PROFILE` | 目標・方針の説明（複数行可） |

### 6-4. 有効化と動作確認

1. リポジトリの **Actions** タブを開き、ワークフローを有効化（初回は確認ボタンが出ます）
2. 「Weekly Running Report」を選び、「**Run workflow**」で手動実行 → LINEに届けば成功
3. あとは毎週月曜 7:00 JST に自動実行されます（cronは `weekly-report.yml` で変更可）

**注意点**:
- GitHub の cron は **UTC基準**です（JST月曜7:00 = UTC日曜22:00 → `0 22 * * 0`）。混雑時は数分〜数十分遅延することがあります。
- スケジュール実行は**デフォルトブランチ**でのみ動きます。
- リポジトリが**60日間まったく更新されない**とスケジュールは自動停止します（手動実行で復活）。
- Garminトークンが期限切れ（約1年）になったら `setup_garmin_token.py` を再実行し `GARMIN_TOKENS` を更新してください。

---

## 7. 知人に配布する場合

配布の方法は2通りあります。**認証情報は絶対に預からない**のが原則です。

### 方法A: 各自のPCで動かしてもらう（最も簡単）

1. このフォルダから **`config.ini` を除いた**一式を渡す（zipなど）
2. 受け取った人は本READMEの **第2〜4章**（APIキー取得・環境準備・手動実行）を実施
3. 常時実行したい人は第5章（タスクスケジューラー / launchd）

→ 各自が自分のGarmin・Gemini・LINEを設定するので、あなたが秘密情報を扱うことはありません。

### 方法B: 各自のGitHubで動かしてもらう（PCレス）

1. 受け取った人が自分のGitHubアカウントにリポジトリを作成（private推奨）
2. 本READMEの **第6章**（トークン生成 → Secrets登録 → 有効化）を各自で実施

→ これも各自のアカウント・各自のSecretsで完結するため、認証情報の受け渡しが発生しません。

### やってはいけないこと

- 他人のGarminのメール/パスワードやトークンを**あなたが預かる・保存する**こと
  （セキュリティ上もGarmin規約上もNG。これが必要になる「みんなで使う共同サービス」化は、
  Garmin公式APIの承認、またはStrava連携など別の土台が必要になります）
- 自分の `config.ini` や Secrets を相手に渡すこと（必ず各自で取得してもらう）

> 不特定多数向けの本格サービス化を検討する場合は、LINE公式アカウント＋OAuth連携＋
> バックエンド＋プライバシーポリシーが必要になります。まずは方法A/Bの範囲がおすすめです。

---

## 8. セキュリティ上の注意

- `config.ini` には**パスワードとAPIキー**が平文で入ります。
  他人と共有したり、GitHub等に公開したりしないでください（`.gitignore` で除外済み）。
- 配布する際は **`config.ini` を含めず**、`config.example.ini` のみを渡してください。
- トークンが漏れた疑いがあるときは、LINE Developers / Google AI Studio で速やかに再発行してください。

---

## 9. トラブルシューティング

| 症状 | 対処 |
|------|------|
| `config.ini が見つかりません` | `config.example.ini` をコピーして `config.ini` を作成 |
| `未記入の項目があります` | 該当項目に正しい値を記入（プレースホルダのまま残っている） |
| Garminログインエラー | メール/パスワードを確認。MFA有効だと失敗することあり。`pip install --upgrade garminconnect curl_cffi ua-generator` で最新化 |
| LINEに届かない | Botを**友だち追加**したか、`user_id`（U始まり）が正しいか確認 |
| レポートが途中で切れる | `garmin_report.log` に `MAX_TOKENS` 警告が出ていないか確認（本ツールは思考OFF設定済み） |
| Gemini 429エラー | 無料枠のレート上限。少し待つか、課金有効化で上限引き上げ |

ログは `garmin_report.log` に毎回追記されます。問題切り分けの際はまずこれを確認してください。
