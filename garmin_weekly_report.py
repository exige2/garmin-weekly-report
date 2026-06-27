#!/usr/bin/env python3
"""
Garmin Connect 週次ランニングレポート（LLM分析版 / Gemini Flash）
Gemini API でトレーニングを分析し、目標達成に向けた進捗をLINEに通知します。

設定の読み込み順は「環境変数（GitHub Secrets等）→ config.ini」です。
- ローカルPC実行: config.example.ini をコピーして config.ini に記入
- GitHub Actions等のクラウド実行: 環境変数（Secrets）で渡す（config.ini不要）

Garmin認証は次の優先順位:
  1. GARMIN_TOKENS（保存済みトークン文字列。setup_garmin_token.py で生成）
  2. メール＋パスワード
クラウドではトークン認証を強く推奨（毎回SSOログインするとブロックされやすいため）。

実行例:
    python garmin_weekly_report.py
スケジュール実行・クラウド化の方法は README.md を参照してください。
"""

import configparser
import datetime
import json
import os
import sys

import requests

# ══════════════════════════════════════════════
#  設定ファイルの読み込み
# ══════════════════════════════════════════════
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")
LOG_FILE    = os.path.join(BASE_DIR, "garmin_report.log")

_PLACEHOLDERS = {"", "XXXXXX", "XXXXXXXX",
                 "your_email@example.com", "your_password",
                 "your_gemini_api_key",
                 "your_line_channel_access_token", "your_line_user_id"}


def _get(env_key: str, cfg, section: str, option: str, default: str = "") -> str:
    """環境変数を最優先、無ければ config.ini、それも無ければ default を返す。"""
    v = os.getenv(env_key)
    if v is not None and v.strip() != "":
        return v
    if cfg is not None:
        return cfg.get(section, option, fallback=default)
    return default


def load_config():
    """環境変数 → config.ini の順で設定を読み込む。必須項目が無ければエラーで停止。"""
    cfg = None
    if os.path.exists(CONFIG_FILE):
        # interpolation=None: プロフィール内の「%」（例: 80%）をそのまま扱う
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(CONFIG_FILE, encoding="utf-8")

    conf = {
        # Garmin認証: トークン（推奨）か メール+パスワード
        "garmin_tokens":   os.getenv("GARMIN_TOKENS", "").strip(),
        "garmin_email":    _get("GARMIN_EMAIL", cfg, "garmin", "email"),
        "garmin_password": _get("GARMIN_PASSWORD", cfg, "garmin", "password"),
        # Gemini
        "gemini_api_key":  _get("GEMINI_API_KEY", cfg, "gemini", "api_key"),
        "gemini_model":    _get("GEMINI_MODEL", cfg, "gemini", "model", "gemini-2.5-flash"),
        # LINE
        "line_token":      _get("LINE_CHANNEL_ACCESS_TOKEN", cfg, "line", "channel_access_token"),
        "line_user_id":    _get("LINE_USER_ID", cfg, "line", "user_id"),
        # 目標・プロフィール
        "goal_time":       _get("GOAL_MARATHON_TIME", cfg, "goal", "marathon_time", "3時間30分"),
        "goal_pace":       _get("GOAL_RACE_PACE", cfg, "goal", "race_pace", "4:58/km"),
        "runner_profile":  _get("RUNNER_PROFILE", cfg, "goal", "profile", "").strip(),
    }

    # プレースホルダのまま残っている値は未設定扱いにする
    for k, v in conf.items():
        if isinstance(v, str) and v.strip() in _PLACEHOLDERS:
            conf[k] = ""
    if not conf["gemini_model"]:
        conf["gemini_model"] = "gemini-2.5-flash"

    # 必須項目の検証
    errs = []
    if not conf["gemini_api_key"]:
        errs.append("Gemini APIキー（GEMINI_API_KEY / [gemini]api_key）")
    if not conf["line_token"]:
        errs.append("LINEトークン（LINE_CHANNEL_ACCESS_TOKEN / [line]channel_access_token）")
    if not conf["line_user_id"]:
        errs.append("LINEユーザーID（LINE_USER_ID / [line]user_id）")
    has_token = bool(conf["garmin_tokens"])
    has_creds = bool(conf["garmin_email"] and conf["garmin_password"])
    if not (has_token or has_creds):
        errs.append("Garmin認証（GARMIN_TOKENS、または GARMIN_EMAIL ＋ GARMIN_PASSWORD）")

    if errs:
        sys.exit(
            "❌ 設定が不足しています:\n  - " + "\n  - ".join(errs)
            + "\n\nローカルなら config.ini、クラウドなら環境変数(Secrets)で設定してください。"
            "\n取得・設定方法は README.md を参照してください。"
        )
    return conf


# ══════════════════════════════════════════════
#  ユーティリティ
# ══════════════════════════════════════════════
def garmin_login(conf: dict):
    """Garminにログイン。トークン優先、失敗時はメール/パスワードへフォールバック。"""
    from garminconnect import Garmin

    token = conf["garmin_tokens"]
    has_creds = bool(conf["garmin_email"] and conf["garmin_password"])

    if token:
        log(f"Garmin: 保存済みトークンでログイン中...（トークン長 {len(token)} 文字）")
        if len(token) <= 512:
            log("⚠️ トークンが512文字以下です。login()がパス扱いになり失敗します。"
                "トークンが途中までしかコピー/登録されていない可能性が高いです。")
        if not (token.lstrip().startswith("{") and token.rstrip().endswith("}")):
            log("⚠️ トークンが {\"di_token\":...} のJSON形式になっていません。"
                "全文（先頭の { から末尾の } まで）が登録されているか確認してください。")
        try:
            garmin = Garmin()
            garmin.login(token)
            log("ログイン成功（トークン）")
            return garmin
        except Exception as e:
            log(f"⚠️ トークンでのログインに失敗: {e}")
            if not has_creds:
                raise RuntimeError(
                    "トークンでのログインに失敗しました。考えられる原因:\n"
                    "  ① GARMIN_TOKENS が途中までしか登録されていない → 全文をコピーし直す\n"
                    "     （JSON 1行。先頭 { ～ 末尾 } まで、通常1000文字以上）\n"
                    "  ② トークンの有効期限切れ → トークンを再生成して更新\n"
                    "  ③ 予備に GARMIN_EMAIL / GARMIN_PASSWORD を登録すると自動で切替可能"
                ) from e
            log("メール/パスワードでの再ログインを試みます...")

    garmin = Garmin(conf["garmin_email"], conf["garmin_password"])
    garmin.login()
    log("ログイン成功（メール/パスワード）")
    return garmin


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def format_pace(pace_min_per_km: float) -> str:
    mins = int(pace_min_per_km)
    secs = int((pace_min_per_km - mins) * 60)
    return f"{mins}'{secs:02d}\""


def fetch_activities(client, start_date: datetime.date, end_date: datetime.date) -> list:
    """指定期間のランニングアクティビティを取得"""
    return client.get_activities_by_date(
        start_date.isoformat(),
        end_date.isoformat(),
        activitytype="running"
    )


def summarize_week(activities: list, label: str) -> dict:
    """1週分のアクティビティを集計してdictで返す"""
    if not activities:
        return {"label": label, "count": 0, "distance_km": 0, "duration_min": 0,
                "calories": 0, "avg_pace": None, "avg_hr": None, "avg_cadence": None,
                "max_distance_km": 0, "elevation_m": 0}

    total_dist  = sum(a.get("distance", 0) for a in activities)
    total_dur   = sum(a.get("duration", 0) for a in activities)
    total_cal   = sum(a.get("calories", 0) for a in activities)
    total_elev  = sum(a.get("elevationGain", 0) or 0 for a in activities)
    max_dist    = max(a.get("distance", 0) for a in activities)

    hr_list  = [a.get("averageHR") or a.get("avgHr", 0) for a in activities if a.get("averageHR") or a.get("avgHr")]
    cad_list = [a.get("averageRunningCadenceInStepsPerMinute", 0) for a in activities
                if a.get("averageRunningCadenceInStepsPerMinute")]

    paces = []
    for a in activities:
        d, t = a.get("distance", 0), a.get("duration", 0)
        if d > 0 and t > 0:
            paces.append((t / 60) / (d / 1000))

    return {
        "label":           label,
        "count":           len(activities),
        "distance_km":     round(total_dist / 1000, 1),
        "duration_min":    round(total_dur / 60, 0),
        "calories":        round(total_cal, 0),
        "avg_pace":        round(sum(paces) / len(paces), 2) if paces else None,
        "avg_hr":          round(sum(hr_list) / len(hr_list), 0) if hr_list else None,
        "avg_cadence":     round(sum(cad_list) / len(cad_list), 0) if cad_list else None,
        "max_distance_km": round(max_dist / 1000, 1),
        "elevation_m":     round(total_elev, 0),
    }


def format_week_summary(week: dict) -> str:
    """今週の集計値をLINE表示用のテキストブロックに整形"""
    if week["count"] == 0:
        return "📊 今週のサマリー\n  今週はランニングなし"
    lines = ["📊 今週のサマリー"]
    lines.append(f"  走行回数   : {week['count']} 回")
    lines.append(f"  総距離     : {week['distance_km']} km")
    lines.append(f"  最長ラン   : {week['max_distance_km']} km")
    lines.append(f"  総時間     : {int(week['duration_min'])} 分")
    if week["avg_pace"]:
        lines.append(f"  平均ペース : {format_pace(week['avg_pace'])} /km")
    if week["avg_hr"]:
        lines.append(f"  平均心拍   : {int(week['avg_hr'])} bpm")
    if week["avg_cadence"]:
        lines.append(f"  ケイデンス : {int(week['avg_cadence'])} spm")
    if week["elevation_m"] > 0:
        lines.append(f"  獲得標高   : {int(week['elevation_m'])} m")
    return "\n".join(lines)


def build_payload(conf: dict, weeks: list, today: datetime.date) -> dict:
    """
    LLMに渡す構造化データを組み立てる。

    生データ（FIT時系列）は渡さず、コード側で集計した値とランナープロファイルのみを
    構造化JSONとして渡す。これによりトークンを節約し、無料枠内で安定動作させる。
    """
    week_records = []
    for w in weeks:
        if w["count"] == 0:
            week_records.append({"label": w["label"], "ran": False})
            continue
        rec = {
            "label":          w["label"],
            "ran":            True,
            "runs":           w["count"],
            "total_km":       w["distance_km"],
            "longest_run_km": w["max_distance_km"],
            "total_minutes":  int(w["duration_min"]),
            "calories":       int(w["calories"]),
        }
        if w["avg_pace"]:
            rec["avg_pace_per_km"] = format_pace(w["avg_pace"])
        if w["avg_hr"]:
            rec["avg_hr_bpm"] = int(w["avg_hr"])
        if w["avg_cadence"]:
            rec["avg_cadence_spm"] = int(w["avg_cadence"])
        if w["elevation_m"] > 0:
            rec["elevation_gain_m"] = int(w["elevation_m"])
        week_records.append(rec)

    return {
        "analysis_date": today.strftime("%Y-%m-%d"),
        "runner_profile": {
            "goal_time":      conf["goal_time"],
            "goal_race_pace": conf["goal_pace"],
            "notes":          conf["runner_profile"],
        },
        "weeks_recent_first": week_records,
    }


def analyze_with_llm(conf: dict, payload: dict) -> str:
    """Gemini API でトレーニングデータを分析してレポートを生成"""
    system_prompt = """あなたは経験豊富なランニングコーチです。
与えられたGarminトレーニングデータ（構造化JSON）とランナープロファイルに基づき、
目標達成に向けた具体的で実践的なアドバイスを日本語で提供してください。

入力JSONの weeks_recent_first は直近週が先頭、配列順に過去へ遡ります。
ran=false の週はランニング実施なしを意味します。

レポートはLINEメッセージとして送信されます。
絵文字を適度に使い、読みやすくモチベーションが上がる内容にし、合計700文字以内に収めてください。
プレーンテキストで出力し、Markdown記法やコードブロックは使わないでください。

構成：
1. 今週のサマリー（一言評価）
2. 先週との比較・トレンド
3. 目標への進捗評価（目標ペース・距離・心拍ゾーンの観点から）
4. 来週のトレーニング提案（具体的に1〜2点）
5. 一言コーチングメッセージ"""

    user_text = (
        "以下のトレーニングデータ（JSON）を分析してください。\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{conf['gemini_model']}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": conf["gemini_api_key"],
    }
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 2048,
            # 2.5 Flash は思考(thinking)が標準ON。思考トークンが maxOutputTokens を
            # 消費し本文が途中で切れるため、思考を無効化(0)して全枠を出力に充てる。
            # 分析を厚くしたい場合は 0→512 等にし、maxOutputTokens も併せて増やす。
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # candidates[0].content.parts[*].text を結合して取り出す
    try:
        cand = data["candidates"][0]
        parts = cand["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini応答の解析に失敗: {e} / raw={json.dumps(data, ensure_ascii=False)[:500]}")

    # 出力上限に達して途中で切れた場合に検知（思考ONのまま枠不足だと発生）
    if cand.get("finishReason") == "MAX_TOKENS":
        log("⚠️ finishReason=MAX_TOKENS: 出力が途中で切れた可能性。maxOutputTokens増 or thinkingBudget=0 を確認")

    if not text:
        raise RuntimeError(f"Geminiが空の応答を返しました / raw={json.dumps(data, ensure_ascii=False)[:500]}")

    return text


def send_line_message(conf: dict, text: str):
    """LINE Messaging API でプッシュメッセージを送信"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {conf['line_token']}",
    }
    payload = {
        "to": conf["line_user_id"],
        "messages": [{"type": "text", "text": text}],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    return resp.status_code, resp.text


def main():
    log("=== 週次ランニングレポート（Gemini分析版）開始 ===")
    conf = load_config()

    # ── Garmin ログイン（トークン優先 / 失敗時は認証情報へ） ──
    try:
        garmin = garmin_login(conf)
    except Exception as e:
        log(f"❌ Garminログインエラー: {e}")
        send_line_message(conf, f"⚠️ Garminログインエラー:\n{e}")
        sys.exit(1)

    # ── 過去4週のデータ取得 ──────────────────────────
    try:
        today      = datetime.date.today()
        weeks_data = []

        for i in range(4):
            # 直近週から順に4週分（月〜日で区切り）
            week_end   = today - datetime.timedelta(days=7 * i)
            week_start = week_end - datetime.timedelta(days=6)
            label      = ("今週" if i == 0 else f"{i}週前") + \
                         f"（{week_start.strftime('%m/%d')}〜{week_end.strftime('%m/%d')}）"
            acts = fetch_activities(garmin, week_start, week_end)
            weeks_data.append(summarize_week(acts, label))
            log(f"取得: {label} → {weeks_data[-1]['count']}件 / {weeks_data[-1]['distance_km']}km")

    except Exception as e:
        log(f"❌ データ取得エラー: {e}")
        send_line_message(conf, f"⚠️ Garminデータ取得エラー:\n{e}")
        sys.exit(1)

    # ── LLM 分析 ────────────────────────────────────
    try:
        log(f"Gemini API（{conf['gemini_model']}）で分析中...")
        payload = build_payload(conf, weeks_data, today)
        log("── 送信データ（JSON） ──")
        for line in json.dumps(payload, ensure_ascii=False, indent=2).split("\n"):
            log(line)

        report = analyze_with_llm(conf, payload)
        log("分析完了")
        log("── レポート ──")
        for line in report.split("\n"):
            log(line)

    except Exception as e:
        log(f"❌ LLM分析エラー: {e}")
        send_line_message(conf, f"⚠️ LLM分析エラー:\n{e}")
        sys.exit(1)

    # ── LINE 送信 ────────────────────────────────────
    try:
        header        = f"🏃 週次ランニングレポート\n📅 {today.strftime('%Y年%m月%d日')}\n\n"
        summary_block = format_week_summary(weeks_data[0]) + "\n\n" + "─" * 14 + "\n\n"
        message       = header + summary_block + report
        status, body  = send_line_message(conf, message)
        if status == 200:
            log("✅ LINE送信成功")
        else:
            log(f"❌ LINE送信エラー: {status} / {body}")
            sys.exit(1)
    except Exception as e:
        log(f"❌ LINE送信エラー: {e}")
        sys.exit(1)

    log("=== 完了 ===\n")


if __name__ == "__main__":
    main()
