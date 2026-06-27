#!/usr/bin/env python3
"""
Garmin トークン生成ツール（最初に1回だけ、自分のPCで実行）

GitHub Actions などのクラウドで毎回パスワードログインすると、
Garmin にボット扱いされてブロックされやすくなります。
このスクリプトで一度だけログインしてトークン文字列を生成し、
それを GitHub Secret `GARMIN_TOKENS` に登録すると、
クラウド側はパスワード無し・トークンだけでログインできます。

使い方:
    python setup_garmin_token.py
    （メール・パスワード、必要ならMFAコードを入力）
    → 表示された長い文字列をすべてコピーして Secret `GARMIN_TOKENS` に貼り付け

トークンの有効期限は約1年です。期限切れやログイン失敗が出たら再実行してください。
"""

import getpass
import sys


def main():
    try:
        from garminconnect import Garmin
    except ImportError:
        sys.exit("garminconnect が未インストールです。先に `pip install -r requirements.txt` を実行してください。")

    print("=== Garmin トークン生成 ===")
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    # MFA（2段階認証）が有効な場合はコード入力を促す
    garmin = Garmin(email, password, prompt_mfa=lambda: input("MFAコードを入力: ").strip())

    print("\nログイン中...")
    try:
        garmin.login()
    except Exception as e:
        sys.exit(f"❌ ログインに失敗しました: {e}")

    token_str = garmin.client.dumps()

    print("\n✅ ログイン成功。下の1行（長い文字列）をすべてコピーして、")
    print("   GitHub Secret『GARMIN_TOKENS』に貼り付けてください。")
    print("   （ローカルでトークン運用したい場合は環境変数 GARMIN_TOKENS に設定）\n")
    print("─" * 60)
    print(token_str)
    print("─" * 60)


if __name__ == "__main__":
    main()
