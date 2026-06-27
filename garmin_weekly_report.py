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


# ── 1ラン単位の解析（種別分類・ラップ・HRゾーン） ──────────────
# 種別キーワード（アクティビティ名から判定。日本語・英語の両対応）
_TYPE_KEYWORDS = [
    ("interval", ["インターバル", "interval", "レペ", "rep", "ヤッソ", "yasso",
                  "400", "800", "1000m", "ビルドアップ", "build"]),
    ("tempo",    ["テンポ", "tempo", "閾値", "threshold", "ペース走", "lt走"]),
    ("long",     ["ロング", "long", "lsd", "30k", "ロング走"]),
    ("race",     ["レース", "race", "大会", "marathon", "マラソン", "ハーフ", "half"]),
    ("recovery", ["リカバリー", "recovery", "回復", "regen", "リカバ"]),
    ("easy",     ["イージー", "easy", "ジョグ", "jog"]),
]


def _pace_min_per_km(dist_m, dur_s):
    if dist_m and dur_s and dist_m > 0:
        return (dur_s / 60) / (dist_m / 1000)
    return None


def _extract_laps(splits: dict) -> list:
    """get_activity_splits の戻りからラップ配列を取り出す（キー差異に頑健に対応）。"""
    laps_raw = splits.get("lapDTOs") or splits.get("splits") or []
    laps = []
    for l in laps_raw:
        dist = l.get("distance", 0) or 0
        dur  = l.get("duration") or l.get("movingDuration") or l.get("elapsedDuration") or 0
        hr   = l.get("averageHR") or l.get("avgHr")
        laps.append({"dist_m": round(dist), "dur_s": round(dur),
                     "avg_hr": int(hr) if hr else None})
    return laps


def classify_workout(act: dict, week_longest_m: float, laps: list) -> str:
    """アクティビティ名・距離・ラップのペースばらつきからトレーニング種別を推定。"""
    name = (act.get("activityName") or "").lower()
    for label, kws in _TYPE_KEYWORDS:
        if any(k.lower() in name for k in kws):
            return label

    dist = act.get("distance", 0) or 0
    # ロング走: 18km以上、または週最長かつ15km以上
    if dist >= 18000 or (week_longest_m and dist >= 0.95 * week_longest_m and dist >= 15000):
        return "long"

    # ラップ間ペース差で緩急（インターバル/変化走）を判定
    paces = [p for p in (_pace_min_per_km(l["dist_m"], l["dur_s"]) for l in laps) if p]
    if len(paces) >= 4:
        spread = max(paces) - min(paces)
        if spread >= 1.2:          # ラップ間で 1'12"/km 以上の差 → 緩急あり
            return "interval"
        if spread >= 0.5 and (act.get("averageHR") or 0) >= 150:
            return "tempo"
    return "easy"


def _compact_laps(laps: list) -> list:
    """ラップをLLM用にペース文字列＋心拍へ整形（緩急の評価用）。"""
    out = []
    for i, l in enumerate(laps, 1):
        p = _pace_min_per_km(l["dist_m"], l["dur_s"])
        item = {"lap": i, "dist_m": l["dist_m"]}
        if p:
            item["pace"] = format_pace(p)
        if l.get("avg_hr"):
            item["hr"] = l["avg_hr"]
        out.append(item)
    return out


def summarize_activity(client, act: dict, week_longest_m: float) -> dict:
    """1本のランを、種別・ラップ・HRゾーン込みで詳細化する。"""
    aid  = act.get("activityId")
    dist = act.get("distance", 0) or 0
    dur  = act.get("duration", 0) or 0

    rec = {
        "date":        (act.get("startTimeLocal") or "")[:10],
        "name":        act.get("activityName") or "",
        "distance_km": round(dist / 1000, 2),
        "duration_min": round(dur / 60, 1),
    }
    p = _pace_min_per_km(dist, dur)
    if p:
        rec["avg_pace_per_km"] = format_pace(p)
    if act.get("averageHR"):
        rec["avg_hr"] = int(act["averageHR"])
    if act.get("maxHR"):
        rec["max_hr"] = int(act["maxHR"])
    cad = act.get("averageRunningCadenceInStepsPerMinute")
    if cad:
        rec["cadence_spm"] = int(cad)
    if act.get("elevationGain"):
        rec["elevation_m"] = int(act["elevationGain"])
    # トレーニング効果（取得できる場合）
    if act.get("aerobicTrainingEffect") is not None:
        rec["aerobic_te"] = round(act["aerobicTrainingEffect"], 1)
    if act.get("anaerobicTrainingEffect") is not None:
        rec["anaerobic_te"] = round(act["anaerobicTrainingEffect"], 1)

    # ラップ取得（種別判定と緩急評価に使用）
    laps = []
    try:
        laps = _extract_laps(client.get_activity_splits(aid))
    except Exception as e:
        log(f"  ラップ取得スキップ (id={aid}): {e}")

    rec["workout_type"] = classify_workout(act, week_longest_m, laps)

    # HRゾーン配分（80/20分析用）
    try:
        zones = client.get_activity_hr_in_timezones(aid) or []
        total = sum(z.get("secsInZone", 0) for z in zones)
        if total > 0:
            rec["hr_zone_pct"] = {
                f"z{z.get('zoneNumber')}": round(100 * z.get("secsInZone", 0) / total)
                for z in zones if z.get("zoneNumber")
            }
    except Exception as e:
        log(f"  HRゾーン取得スキップ (id={aid}): {e}")

    # ラップは質練習・ロング・レースのみ payload に含める（トークン節約）
    if rec["workout_type"] in ("interval", "tempo", "long", "race") and laps:
        rec["laps"] = _compact_laps(laps)

    return rec


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


def build_payload(conf: dict, weeks: list, this_week_runs: list, today: datetime.date) -> dict:
    """
    LLMに渡す構造化データを組み立てる。

    生データ（FIT時系列）は渡さず、コード側で集計した値とランナープロファイルのみを
    構造化JSONとして渡す。これによりトークンを節約し、無料枠内で安定動作させる。

    this_week_runs: 今週の「1ラン単位」の詳細（種別・ラップ・HRゾーン込み）。
                    これにより種別ごとの具体的な講評が可能になる。
    weeks_recent_first: 週次の集計（トレンド把握用の文脈）。
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
        "this_week_runs":     this_week_runs,
        "weeks_recent_first": week_records,
    }


def analyze_with_llm(conf: dict, payload: dict) -> str:
    """Gemini API でトレーニングデータを分析してレポートを生成"""
    system_prompt = """あなたは経験豊富なランニングコーチです。
入力JSONには分析日、ランナープロファイル(runner_profile)、今週の各ランの詳細(this_week_runs)、
週次の推移(weeks_recent_first) が含まれます。

this_week_runs の各ランには次の情報があります:
- workout_type: long(ロング走)/interval(インターバル)/tempo(テンポ・閾値)/easy(イージー)/recovery(回復走)/race(レース)
- avg_pace_per_km, avg_hr, max_hr, cadence_spm, elevation_m
- hr_zone_pct: 心拍ゾーン別の時間配分(%)
- laps: 質練習・ロングのみ。各ラップの距離・ペース・心拍（緩急やラップの揃い方の評価に使う）

【最重要】各ランを1本ずつ、種別に応じた観点で講評してください。
良かった点に加えて「具体的な改善ポイント」を必ず述べ、ペースや心拍などの数値を根拠として引用すること。
種別ごとの着眼点:
- ロング走: 後半の失速(ポジティブスプリット)有無、心拍ドリフト、距離の妥当性、目標レースペース対比
- インターバル: ラップの揃い方/終盤の失速、設定ペース達成度、本数、心拍の上がり方
- テンポ/閾値: 設定ペースの維持、心拍が閾値域に収まっているか
- イージー/回復走: 強度が上がりすぎていないか(hr_zone_pctでゾーン2中心か)、80/20の遵守

日本語・プレーンテキスト・絵文字を適度に使い、最大1500文字。Markdownやコードブロックは使わない。

構成:
1. 今週のサマリー（一言評価）
2. 各ランの講評（1本ずつ。種別を明記し、良かった点＋具体的改善ポイントを数値根拠つきで）
3. 週全体のバランス（強度配分・80/20、距離・質のバランス）
4. 目標(goal_time/goal_race_pace)への進捗評価
5. 来週の具体的提案（練習メニューを1〜2本、ペース付きで）"""

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
            "maxOutputTokens": 4096,
            # 2.5 Flash は思考(thinking)が標準ON。思考トークンが maxOutputTokens を
            # 消費し本文が途中で切れるため、思考を無効化(0)して全枠を出力に充てる。
            # 各ランの講評で出力が長くなるため上限を増やしている。
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
        this_week_acts = []

        for i in range(4):
            # 直近週から順に4週分（月〜日で区切り）
            week_end   = today - datetime.timedelta(days=7 * i)
            week_start = week_end - datetime.timedelta(days=6)
            label      = ("今週" if i == 0 else f"{i}週前") + \
                         f"（{week_start.strftime('%m/%d')}〜{week_end.strftime('%m/%d')}）"
            acts = fetch_activities(garmin, week_start, week_end)
            if i == 0:
                this_week_acts = acts
            weeks_data.append(summarize_week(acts, label))
            log(f"取得: {label} → {weeks_data[-1]['count']}件 / {weeks_data[-1]['distance_km']}km")

    except Exception as e:
        log(f"❌ データ取得エラー: {e}")
        send_line_message(conf, f"⚠️ Garminデータ取得エラー:\n{e}")
        sys.exit(1)

    # ── 今週の各ランを1本ずつ詳細化（種別・ラップ・HRゾーン） ──
    this_week_runs = []
    try:
        week_longest_m = max((a.get("distance", 0) or 0 for a in this_week_acts), default=0)
        # 日付順（古い→新しい）に並べて詳細化
        for a in sorted(this_week_acts, key=lambda x: x.get("startTimeLocal") or ""):
            run = summarize_activity(garmin, a, week_longest_m)
            this_week_runs.append(run)
            log(f"  詳細: {run['date']} {run['workout_type']} "
                f"{run['distance_km']}km {run.get('avg_pace_per_km','-')}")
    except Exception as e:
        # 詳細化に失敗しても週次集計だけで続行する
        log(f"⚠️ 各ラン詳細化でエラー（週次集計のみで続行）: {e}")

    # ── LLM 分析 ────────────────────────────────────
    try:
        log(f"Gemini API（{conf['gemini_model']}）で分析中...")
        payload = build_payload(conf, weeks_data, this_week_runs, today)
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