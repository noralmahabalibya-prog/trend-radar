"""
رادار الترند - يلقط التغريدات اللي بدأت تنتشر في مجالك ويرسلها لك على تيليقرام.
يشتغل كل 30 دقيقة عن طريق GitHub Actions.

التكلفة: كل تغريدة يقرأها = 0.005$ من رصيد X API.
الإعدادات الافتراضية (10 تغريدات كل 30 دقيقة) = تقريباً 2.4$ في اليوم.
"""

import os
import json
import datetime as dt

import requests

# ====== الإعدادات (عدّلها على كيفك) ======

# الكلمات اللي يدوّر عليها البوت
KEYWORDS = [
    "ريال مدريد",
    "برشلونة",
    "برشلونه",
    "البارسا",
]

LANG = "ar"               # لغة التغريدات
LOOKBACK_MIN = 90         # يدوّر على تغريدات آخر كم دقيقة
MAX_RESULTS = 10          # كم تغريدة يقرأ كل مرة (أقل شي 10)
MIN_SCORE = 5.0           # أقل سرعة انتشار (تفاعل في الدقيقة) عشان ينبّهك
MAX_ALERTS_PER_RUN = 3    # أقصى عدد تنبيهات في كل تشغيل
DAILY_READ_LIMIT = 600    # حد يومي للقراءات عشان ما يخلص الرصيد (600 = 3$)

# ====== المفاتيح (من GitHub Secrets) ======

X_BEARER = os.environ["X_BEARER_TOKEN"]
TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT = os.environ["TG_CHAT_ID"]

STATE_FILE = "radar_state.json"
NOW = dt.datetime.now(dt.timezone.utc)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen": [], "day": "", "reads": 0}


def save_state(state):
    state["seen"] = state["seen"][-500:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def build_query():
    parts = [f'"{k}"' if " " in k else k for k in KEYWORDS]
    return f"({' OR '.join(parts)}) lang:{LANG} -is:retweet -is:reply"


def search():
    start = (NOW - dt.timedelta(minutes=LOOKBACK_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(
        "https://api.x.com/2/tweets/search/recent",
        headers={"Authorization": f"Bearer {X_BEARER}"},
        params={
            "query": build_query(),
            "max_results": MAX_RESULTS,
            "sort_order": "relevancy",
            "start_time": start,
            "tweet.fields": "created_at,public_metrics",
        },
        timeout=30,
    )
    if r.status_code != 200:
        print("X API error:", r.status_code, r.text)
        r.raise_for_status()
    return r.json().get("data", [])


def score(tweet):
    m = tweet["public_metrics"]
    engagement = (
        m.get("like_count", 0)
        + 2 * m.get("retweet_count", 0)
        + 2 * m.get("quote_count", 0)
        + m.get("reply_count", 0)
    )
    created = dt.datetime.fromisoformat(tweet["created_at"].replace("Z", "+00:00"))
    age_min = max((NOW - created).total_seconds() / 60, 1)
    return engagement / age_min, engagement, age_min


def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={"chat_id": TG_CHAT, "text": text},
        timeout=30,
    )


def main():
    state = load_state()

    today = NOW.strftime("%Y-%m-%d")
    if state.get("day") != today:
        state["day"] = today
        state["reads"] = 0

    if state["reads"] + MAX_RESULTS > DAILY_READ_LIMIT:
        print("وصلنا الحد اليومي، ما راح نقرأ شي اليوم.")
        save_state(state)
        return

    tweets = search()
    state["reads"] += len(tweets)

    hits = []
    for t in tweets:
        if t["id"] in state["seen"]:
            continue
        sc, eng, age = score(t)
        if sc >= MIN_SCORE:
            hits.append((sc, eng, age, t))

    hits.sort(key=lambda h: h[0], reverse=True)

    for sc, eng, age, t in hits[:MAX_ALERTS_PER_RUN]:
        text = (
            "🔥 تغريدة بدأت تنتشر\n\n"
            f"{t['text'][:300]}\n\n"
            f"⚡ {sc:.1f} تفاعل/دقيقة | {eng} تفاعل خلال {int(age)} دقيقة\n"
            f"https://x.com/i/status/{t['id']}"
        )
        send_telegram(text)
        state["seen"].append(t["id"])

    print(f"قرأنا {len(tweets)} تغريدة، أرسلنا {min(len(hits), MAX_ALERTS_PER_RUN)} تنبيه. "
          f"قراءات اليوم: {state['reads']}")
    save_state(state)


if __name__ == "__main__":
    main()
