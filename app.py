"""
Scout Dashboard — standalone Flask app (separate repo).
Talks to the shared Railway Postgres. Triggers Scout via Railway API.

Required env vars:
  DATABASE_URL              — shared Postgres (from Scout's Railway project)
  DASHBOARD_PASSWORD        — login password
  SECRET_KEY                — Flask session secret (any random string)
  RAILWAY_API_TOKEN         — for manual Scout trigger
  RAILWAY_SCOUT_SERVICE_ID  — Scout service ID
  RAILWAY_ENVIRONMENT_ID    — Railway environment ID
  TELEGRAM_BOT_TOKEN        — for Telegram test (optional)
  TELEGRAM_CHAT_ID          — for Telegram test (optional)
"""

import os
import json
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, redirect, url_for, session, render_template_string
import db_reader as db
from railway_api import trigger_scout_run

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-please")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
PASSWORD     = os.environ.get("DASHBOARD_PASSWORD", "scout2026")

COUNTRIES_LIST = [
    ("SA", "السعودية"), ("AE", "الإمارات"), ("EG", "مصر"),
    ("KW", "الكويت"),   ("QA", "قطر"),      ("BH", "البحرين"),
    ("OM", "عُمان"),    ("MA", "المغرب"),
    ("LY", "ليبيا"),    ("PS", "فلسطين"),   ("LB", "لبنان"),
    ("SY", "سوريا"),    ("JO", "الأردن"),   ("IQ", "العراق"),
    ("TN", "تونس"),
]


def get_conn():
    return db.get_conn(DATABASE_URL)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ═══ Auth ════════════════════════════════════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def login():
    err = ""
    if request.method == "POST":
        if request.form.get("password") == PASSWORD:
            session["auth"] = True
            return redirect(url_for("index"))
        err = "كلمة السر غلط"
    return render_template_string(LOGIN_HTML, error=err)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ═══ Main page ════════════════════════════════════════════════════════════════

@app.route("/")
@login_required
def index():
    conn  = get_conn()
    cfg   = db.load_config(conn)
    stats = db.get_stats(conn)
    conn.close()
    return render_template_string(
        open("ui.html", encoding="utf-8").read(),
        cfg=json.dumps(cfg, ensure_ascii=False),
        stats=json.dumps(stats, ensure_ascii=False),
        countries=COUNTRIES_LIST,
    )


# ═══ Config API ═══════════════════════════════════════════════════════════════

@app.route("/api/config", methods=["GET"])
@login_required
def api_config_get():
    conn = get_conn()
    cfg  = db.load_config(conn)
    conn.close()
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
@login_required
def api_config_save():
    data = request.get_json(force=True) or {}
    data.setdefault("countries", [])
    data.setdefault("competitor_page_ids", [])
    data.setdefault("search_terms_config", [])
    data.setdefault("store", {})
    data.setdefault("use_tiktok", True)
    data.setdefault("confidence_floor", 0.60)
    data.setdefault("winner_days_threshold", 30)
    data.setdefault("alert_settings", {})
    conn = get_conn()
    db.save_config(conn, data)
    conn.close()
    return jsonify({"ok": True, "saved_at": datetime.now(timezone.utc).isoformat()})


# ═══ Stats ════════════════════════════════════════════════════════════════════

@app.route("/api/stats")
@login_required
def api_stats():
    conn  = get_conn()
    stats = db.get_stats(conn)
    conn.close()
    return jsonify(stats)


# ═══ Runs history ═════════════════════════════════════════════════════════════

@app.route("/api/runs")
@login_required
def api_runs():
    conn = get_conn()
    runs = db.get_runs(conn)
    conn.close()
    return jsonify(runs)


# ═══ Manual run (Railway API) ═════════════════════════════════════════════════

@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    ok, message = trigger_scout_run()
    return jsonify({"ok": ok, "message": message})


# ═══ Run Results ═════════════════════════════════════════════════════════════

@app.route("/api/run-results")
@login_required
def api_run_results():
    """كل الإعلانات اللي شافها الـ Scout في آخر run."""
    conn = get_conn()

    # وقت آخر run من agent_events
    last_event = conn.execute(
        "SELECT ts FROM agent_events ORDER BY ts DESC LIMIT 1"
    ).fetchone()

    if not last_event or not last_event[0]:
        conn.close()
        return jsonify({"ads": [], "run_ts": None, "total": 0})

    from datetime import timedelta
    run_ts    = last_event[0]
    run_start = run_ts - timedelta(hours=2)   # نافذة 2 ساعة تغطي مدة الـ run

    rows = conn.execute(
        """SELECT ad_id, page_name, country, source,
                  body, title, description, snapshot_url,
                  start_time, last_seen,
                  EXTRACT(DAY FROM (now() - start_time))::int AS days_running
           FROM competitor_snapshots
           WHERE last_seen >= %s
           ORDER BY page_name, last_seen DESC
           LIMIT 500""",
        (run_start,),
    ).fetchall()
    conn.close()

    from datetime import timedelta as td
    KSA = td(hours=3)
    ads = []
    for r in rows:
        # تحويل كل الـ datetimes لـ strings عشان JSON يشتغل
        start = r[8]
        last  = r[9]
        ads.append({
            "ad_id":       str(r[0] or ""),
            "page_name":   str(r[1] or ""),
            "country":     str(r[2] or ""),
            "source":      str(r[3] or ""),
            "body":        str(r[4] or ""),
            "title":       str(r[5] or ""),
            "description": str(r[6] or ""),
            "snapshot_url":str(r[7] or ""),
            "start_time":  (start + KSA).strftime("%Y-%m-%d") if start else "",
            "last_seen":   (last  + KSA).strftime("%Y-%m-%d %H:%M") if last else "",
            "days_running": int(r[10] or 0),
        })

    return jsonify({
        "ads":    ads,
        "run_ts": (run_ts + KSA).strftime("%Y-%m-%d %H:%M KSA"),
        "total":  len(ads),
    })


# ═══ Winners ══════════════════════════════════════════════════════════════════

@app.route("/api/winners")
@login_required
def api_winners():
    min_days = int(request.args.get("min_days", 14))
    conn     = get_conn()
    winners  = db.get_winners(conn, min_days=min_days)
    conn.close()
    return jsonify(winners)


# ═══ Known competitors from DB ═══════════════════════════════════════════════

@app.route("/api/known-competitors")
@login_required
def api_known_competitors():
    """المنافسون المكتشفون من الـ DB مع الـ page_id الفعلي."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT page_name, page_id, country,
                  COUNT(*) AS ads,
                  MIN(first_seen)::date AS since
           FROM competitor_snapshots
           WHERE page_id IS NOT NULL AND page_id != ''
           GROUP BY page_name, page_id, country
           ORDER BY ads DESC LIMIT 40"""
    ).fetchall()
    conn.close()
    cols = ["page_name", "page_id", "country", "ads", "since"]
    return jsonify([dict(zip(cols, r)) | {"since": str(r[4])} for r in rows])


# ═══ Competitor activity ══════════════════════════════════════════════════════

@app.route("/api/competitors/activity")
@login_required
def api_activity():
    conn     = get_conn()
    activity = db.get_competitor_activity(conn)
    conn.close()
    return jsonify(activity)


# ═══ Themes ═══════════════════════════════════════════════════════════════════

@app.route("/api/themes")
@login_required
def api_themes():
    conn   = get_conn()
    themes = db.get_themes(conn)
    conn.close()
    return jsonify(themes)


# ═══ Swipe file ═══════════════════════════════════════════════════════════════

@app.route("/api/swipe", methods=["GET"])
@login_required
def api_swipe_get():
    conn  = get_conn()
    items = db.get_swipe(conn)
    conn.close()
    return jsonify(items)


@app.route("/api/swipe", methods=["POST"])
@login_required
def api_swipe_add():
    d    = request.get_json(force=True) or {}
    conn = get_conn()
    db.add_swipe(conn,
                 d.get("ad_id", ""),    d.get("page_name", ""),
                 d.get("country", ""),  d.get("body", ""),
                 d.get("snapshot_url", ""), d.get("notes", ""), d.get("tags", ""))
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/swipe/<int:item_id>", methods=["DELETE"])
@login_required
def api_swipe_delete(item_id):
    conn = get_conn()
    db.delete_swipe(conn, item_id)
    conn.close()
    return jsonify({"ok": True})


# ═══ Railway API debug ════════════════════════════════════════════════════════

@app.route("/api/railway/mutations")
@login_required
def api_railway_mutations():
    """استعلام Railway API schema للعثور على الـ mutation الصح للـ cron"""
    import requests as req
    token = os.environ.get("RAILWAY_API_TOKEN", "")
    if not token:
        return jsonify({"error": "RAILWAY_API_TOKEN غير موجود"}), 400

    # أولاً نستعلم عن الـ input type بتاع deploymentInstanceExecutionCreate
    introspect_input = """
    {
      __type(name: "DeploymentInstanceExecutionCreateInput") {
        fields { name type { name kind ofType { name kind } } }
      }
    }
    """
    try:
        resp_input = req.post(
            "https://backboard.railway.app/graphql/v2",
            json={"query": introspect_input},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        input_fields = (resp_input.json().get("data") or {}).get("__type", {}).get("fields", [])
    except Exception:
        input_fields = []

    introspect = """
    { __schema { mutationType { fields {
        name description
        args { name type { name kind ofType { name } } }
    }}}}
    """
    try:
        resp = req.post(
            "https://backboard.railway.app/graphql/v2",
            json={"query": introspect},
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            timeout=15
        )
        data = resp.json()
        fields = (data.get("data", {})
                      .get("__schema", {})
                      .get("mutationType", {})
                      .get("fields", []))
        keywords = ["cron", "job", "trigger", "run", "execute", "deploy", "start"]
        relevant = [
            {"name": f["name"],
             "desc": (f.get("description") or "")[:100],
             "args": [a["name"] for a in f.get("args", [])]}
            for f in fields
            if any(k in f["name"].lower() for k in keywords)
        ]
        return jsonify({"total": len(fields), "relevant": relevant, "deploymentInstanceExecutionCreate_input": input_fields})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══ Telegram test ════════════════════════════════════════════════════════════

@app.route("/api/telegram/test", methods=["POST"])
@login_required
def api_telegram_test():
    import requests as req
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return jsonify({"ok": False, "error": "TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID غير موجودين"}), 400
    try:
        r = req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "✅ *Scout Dashboard* — اختبار ناجح!", "parse_mode": "Markdown"},
            timeout=10,
        )
        return jsonify({"ok": r.ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ═══ Login HTML ═══════════════════════════════════════════════════════════════

LOGIN_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scout</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f0f0f;color:#e0e0e0;
  display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;
  padding:40px;width:100%;max-width:360px}
h1{font-size:20px;margin-bottom:6px;color:#fff}
p{font-size:13px;color:#888;margin-bottom:22px}
input{width:100%;padding:10px 14px;background:#0f0f0f;border:1px solid #333;
  border-radius:8px;color:#fff;font-size:14px;margin-bottom:12px;outline:none}
input:focus{border-color:#7c5cfc}
button{width:100%;padding:11px;background:#7c5cfc;border:none;border-radius:8px;
  color:#fff;font-size:14px;font-weight:500;cursor:pointer}
button:hover{background:#6a4de0}
.err{color:#e55;font-size:13px;margin-top:8px;text-align:center}
</style></head><body>
<div class="card">
  <h1>🎯 Scout</h1>
  <p>منصة متابعة إعلانات المنافسين — MENA</p>
  <form method="post">
    <input type="password" name="password" placeholder="كلمة السر" autofocus>
    <button type="submit">دخول</button>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
  </form>
</div></body></html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
