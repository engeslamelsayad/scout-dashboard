"""
Scout Dashboard — complete web app with all features.
Tabs: Overview | Search Terms | Competitors | Countries | Store | Winners | Themes | Swipe File | Settings
"""

import os, sys, json, threading
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, redirect, url_for, session, render_template_string
import psycopg
from pgvector.psycopg import register_vector

# ── path so we can import Scout modules for manual run ──────────────────────
# When deployed with Root Directory empty and started as dashboard.app:app
# __file__ = /app/dashboard/app.py → ROOT = /app (where main.py lives)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'dashboard'))  # for dashboard-local imports

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
PASSWORD     = os.environ.get("DASHBOARD_PASSWORD", "scout2026")

COUNTRIES_LIST = [
    ("SA","السعودية"),("AE","الإمارات"),("EG","مصر"),
    ("KW","الكويت"),("QA","قطر"),("BH","البحرين"),
    ("OM","عُمان"),("MA","المغرب"),
]

# ── manual run state ────────────────────────────────────────────────────────
_run_lock   = threading.Lock()
_run_status = {"running": False, "started_at": None, "log": [], "done_msg": ""}


def get_db():
    conn = psycopg.connect(DATABASE_URL)
    register_vector(conn)
    return conn


def load_config(conn) -> dict:
    row = conn.execute("SELECT data FROM scout_config WHERE id=1").fetchone()
    if row:
        d = row[0]
        return d if isinstance(d, dict) else json.loads(d)
    return {}


def save_config(conn, data: dict) -> None:
    conn.execute(
        """INSERT INTO scout_config (id,data,updated_at,updated_by) VALUES (1,%s,now(),'dashboard')
           ON CONFLICT (id) DO UPDATE SET data=EXCLUDED.data,updated_at=now(),updated_by='dashboard'""",
        (json.dumps(data, ensure_ascii=False),)
    )
    conn.commit()


def get_stats(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM competitor_snapshots").fetchone()[0]
    by_country = conn.execute(
        "SELECT country,COUNT(*) FROM competitor_snapshots GROUP BY country ORDER BY 2 DESC"
    ).fetchall()
    last_event = conn.execute(
        "SELECT type,confidence,ts FROM agent_events ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    last_run = conn.execute("SELECT MAX(run_date) FROM clusters").fetchone()[0]
    return {
        "total_ads": total,
        "by_country": [{"country": r[0], "count": r[1]} for r in by_country],
        "last_event": {
            "type": last_event[0],
            "confidence": round(float(last_event[1] or 0), 2),
            "ts": last_event[2].strftime("%Y-%m-%d %H:%M UTC") if last_event[2] else "—",
        } if last_event else {},
        "last_run": last_run.isoformat() if last_run else "لم يُشغَّل بعد",
    }


def login_required(f):
    @wraps(f)
    def d(*a, **k):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return f(*a, **k)
    return d


# ═══════════════════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/login", methods=["GET","POST"])
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


# ═══════════════════════════════════════════════════════════════════════════
# Main page
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/")
@login_required
def index():
    conn  = get_db()
    cfg   = load_config(conn)
    stats = get_stats(conn)
    conn.close()
    return render_template_string(
        DASHBOARD_HTML,
        cfg=json.dumps(cfg, ensure_ascii=False),
        stats=json.dumps(stats, ensure_ascii=False),
        countries=COUNTRIES_LIST,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Config API
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/config", methods=["GET"])
@login_required
def api_get_config():
    conn = get_db(); cfg = load_config(conn); conn.close()
    return jsonify(cfg)

@app.route("/api/config", methods=["POST"])
@login_required
def api_save_config():
    data = request.get_json(force=True) or {}
    data.setdefault("countries", [])
    data.setdefault("competitor_page_ids", [])
    data.setdefault("search_terms_config", [])
    data.setdefault("store", {})
    data.setdefault("use_tiktok", True)
    data.setdefault("confidence_floor", 0.60)
    data.setdefault("winner_days_threshold", 30)
    data.setdefault("alert_settings", {})
    conn = get_db(); save_config(conn, data); conn.close()
    return jsonify({"ok": True, "saved_at": datetime.now(timezone.utc).isoformat()})


# ═══════════════════════════════════════════════════════════════════════════
# Stats API
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/stats")
@login_required
def api_stats():
    conn = get_db(); s = get_stats(conn); conn.close()
    return jsonify(s)


# ═══════════════════════════════════════════════════════════════════════════
# Runs history
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/runs")
@login_required
def api_runs():
    conn = get_db()
    rows = conn.execute(
        "SELECT id,type,confidence,ts,payload FROM agent_events ORDER BY ts DESC LIMIT 20"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        payload = r[4]
        if isinstance(payload, str):
            try: payload = json.loads(payload)
            except: payload = {}
        out.append({
            "id": r[0], "type": r[1],
            "confidence": round(float(r[2] or 0), 2),
            "ts": r[3].strftime("%Y-%m-%d %H:%M") if r[3] else "",
            "theme": (payload or {}).get("theme", ""),
        })
    return jsonify(out)


# ═══════════════════════════════════════════════════════════════════════════
# Manual run
# ═══════════════════════════════════════════════════════════════════════════
def _run_scout():
    import subprocess
    main_py = os.path.join(ROOT, 'main.py')
    if not os.path.exists(main_py):
        _run_status["done_msg"] = "❌ main.py غير موجود — تحقق من Root Directory في Railway"
        _run_status["running"] = False
        return
    try:
        proc = subprocess.Popen(
            [sys.executable, main_py],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
            cwd=ROOT,
        )
        lines = []
        for line in proc.stdout:
            lines.append(line.rstrip())
            _run_status["log"] = lines[-60:]
        proc.wait()
        _run_status["done_msg"] = (
            "✅ اكتمل بنجاح" if proc.returncode == 0
            else f"❌ exit code {proc.returncode}"
        )
    except Exception as e:
        _run_status["done_msg"] = f"❌ {e}"
    finally:
        _run_status["running"] = False

@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    """
    Direct subprocess run requires main.py in the same deployment context.
    When Root Directory = 'dashboard', main.py is not deployed here.
    Solution: trigger via Railway Cron Runs tab, or deploy without Root Directory.
    For now, attempt subprocess and return clear error if main.py is missing.
    """
    main_py = os.path.join(ROOT, 'main.py')
    if not os.path.exists(main_py):
        return jsonify({
            "ok": False,
            "error": "railway_cron",
            "message": "main.py غير موجود في هذا الـ deployment. شغّل من Railway → Scout service → Cron Runs → Trigger"
        }), 200
    if _run_status["running"]:
        return jsonify({"error": "run already in progress"}), 409
    _run_status.update({"running": True, "started_at": datetime.now().strftime("%H:%M:%S"), "log": [], "done_msg": ""})
    threading.Thread(target=_run_scout, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/run/status")
@login_required
def api_run_status():
    return jsonify(_run_status)


# ═══════════════════════════════════════════════════════════════════════════
# Winners
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/winners")
@login_required
def api_winners():
    min_days = int(request.args.get("min_days", 14))
    conn = get_db()
    rows = conn.execute(
        """SELECT ad_id,page_name,country,body,snapshot_url,
                  EXTRACT(DAY FROM (now()-start_time))::int AS days
           FROM competitor_snapshots
           WHERE start_time IS NOT NULL AND (stop_time IS NULL OR stop_time>now())
           ORDER BY start_time ASC LIMIT 200"""
    ).fetchall()
    conn.close()
    cols = ["ad_id","page_name","country","body","snapshot_url","days"]
    result = [dict(zip(cols,r)) for r in rows if (r[5] or 0) >= min_days]
    result.sort(key=lambda x: x["days"] or 0, reverse=True)
    return jsonify(result[:40])


# ═══════════════════════════════════════════════════════════════════════════
# Competitor activity
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/competitors/activity")
@login_required
def api_competitor_activity():
    conn = get_db()
    rows = conn.execute(
        """SELECT page_name, country,
             COUNT(*) FILTER (WHERE first_seen >= now()-INTERVAL '7 days')  AS this_week,
             COUNT(*) FILTER (WHERE first_seen >= now()-INTERVAL '14 days'
                                AND first_seen <  now()-INTERVAL '7 days')  AS last_week,
             COUNT(*) AS total
           FROM competitor_snapshots
           GROUP BY page_name,country
           HAVING COUNT(*)>=2
           ORDER BY this_week DESC, total DESC LIMIT 30"""
    ).fetchall()
    conn.close()
    cols = ["page_name","country","this_week","last_week","total"]
    out = []
    for r in rows:
        d = dict(zip(cols,r))
        d["delta"] = (d["this_week"] or 0) - (d["last_week"] or 0)
        out.append(d)
    return jsonify(out)


# ═══════════════════════════════════════════════════════════════════════════
# Themes history
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/themes")
@login_required
def api_themes():
    conn = get_db()
    rows = conn.execute(
        "SELECT run_date,theme,size,competitor_count FROM clusters ORDER BY run_date DESC,size DESC LIMIT 80"
    ).fetchall()
    conn.close()
    cols = ["run_date","theme","size","competitor_count"]
    return jsonify([dict(zip(cols,r)) | {"run_date": str(r[0])} for r in rows])


# ═══════════════════════════════════════════════════════════════════════════
# Swipe file
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/swipe", methods=["GET"])
@login_required
def api_swipe_get():
    conn = get_db()
    rows = conn.execute(
        "SELECT id,ad_id,page_name,country,body,snapshot_url,notes,tags,saved_at FROM swipe_file ORDER BY saved_at DESC"
    ).fetchall()
    conn.close()
    cols = ["id","ad_id","page_name","country","body","snapshot_url","notes","tags","saved_at"]
    return jsonify([dict(zip(cols,r)) | {"saved_at": r[8].strftime("%Y-%m-%d") if r[8] else ""} for r in rows])

@app.route("/api/swipe", methods=["POST"])
@login_required
def api_swipe_add():
    d = request.get_json(force=True) or {}
    conn = get_db()
    conn.execute(
        "INSERT INTO swipe_file (ad_id,page_name,country,body,snapshot_url,notes,tags) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (d.get("ad_id",""), d.get("page_name",""), d.get("country",""),
         d.get("body",""), d.get("snapshot_url",""), d.get("notes",""), d.get("tags",""))
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/swipe/<int:item_id>", methods=["DELETE"])
@login_required
def api_swipe_delete(item_id):
    conn = get_db()
    conn.execute("DELETE FROM swipe_file WHERE id=%s", (item_id,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════
# Telegram test
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/telegram/test", methods=["POST"])
@login_required
def api_telegram_test():
    try:
        sys.path.insert(0, ROOT)
        from telegram import send
        ok = send("✅ *Scout Dashboard* — اختبار ناجح! البوت شغّال.")
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# HTML
# ═══════════════════════════════════════════════════════════════════════════
LOGIN_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scout — دخول</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f0f0f;color:#e0e0e0;
  display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:40px;width:100%;max-width:360px}
h1{font-size:20px;margin-bottom:6px;color:#fff} p{font-size:13px;color:#888;margin-bottom:22px}
input{width:100%;padding:10px 14px;background:#0f0f0f;border:1px solid #333;border-radius:8px;
  color:#fff;font-size:14px;margin-bottom:12px;outline:none}
input:focus{border-color:#7c5cfc}
button{width:100%;padding:11px;background:#7c5cfc;border:none;border-radius:8px;color:#fff;
  font-size:14px;font-weight:500;cursor:pointer}
button:hover{background:#6a4de0}
.err{color:#e55;font-size:13px;margin-top:8px;text-align:center}
</style></head><body>
<div class="card"><h1>🎯 Scout</h1><p>منصة متابعة إعلانات المنافسين — MENA</p>
<form method="post">
  <input type="password" name="password" placeholder="كلمة السر" autofocus>
  <button type="submit">دخول</button>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
</form></div></body></html>"""

DASHBOARD_HTML = open(os.path.join(os.path.dirname(__file__), "ui.html"), encoding="utf-8").read() if os.path.exists(os.path.join(os.path.dirname(__file__), "ui.html")) else "<h1>ui.html not found</h1>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)