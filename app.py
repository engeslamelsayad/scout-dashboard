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

    # وقت آخر run — MAX(last_seen) كـ fallback لو agent_events فاضية
    from datetime import timedelta
    last_seen_row = conn.execute(
        "SELECT MAX(last_seen) FROM competitor_snapshots"
    ).fetchone()

    if not last_seen_row or not last_seen_row[0]:
        conn.close()
        return jsonify({"ads": [], "run_ts": None, "total": 0})

    run_ts    = last_seen_row[0]
    run_start = run_ts - timedelta(hours=2)

    rows = conn.execute(
        """SELECT ad_id, page_name, country, source,
                  body, title, description, snapshot_url, image_url,
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
        # cols: 0=ad_id 1=page_name 2=country 3=source 4=body
        # 5=title 6=description 7=snapshot_url 8=image_url
        # 9=start_time 10=last_seen 11=days_running
        start = r[9]
        last  = r[10]
        ads.append({
            "ad_id":        str(r[0] or ""),
            "page_name":    str(r[1] or ""),
            "country":      str(r[2] or ""),
            "source":       str(r[3] or ""),
            "body":         str(r[4] or ""),
            "title":        str(r[5] or ""),
            "description":  str(r[6] or ""),
            "snapshot_url": str(r[7] or ""),
            "image_url":    str(r[8] or ""),
            "start_time":   (start + KSA).strftime("%Y-%m-%d") if start else "",
            "last_seen":   (last  + KSA).strftime("%Y-%m-%d %H:%M") if last else "",
            "days_running": int(r[11] or 0),
        })

    with_images = sum(1 for a in ads if a.get("image_url"))
    return jsonify({
        "ads":    ads,
        "run_ts": (run_ts + KSA).strftime("%Y-%m-%d %H:%M KSA"),
        "total":  len(ads),
        "with_images": with_images,
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

# ═══ AI Term Suggestions ══════════════════════════════════════════════════════

@app.route("/api/suggest-terms", methods=["POST"])
@login_required
def api_suggest_terms():
    """Claude يقترح search terms مرتبطة بالـ keyword."""
    import requests as req
    data    = request.get_json(force=True) or {}
    term    = data.get("term", "").strip()
    context = data.get("context", "")   # الـ search terms الموجودة

    if not term:
        return jsonify({"suggestions": []})

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"suggestions": [], "error": "ANTHROPIC_API_KEY not set"})

    prompt = f"""أنت خبير في التسويق الإلكتروني في السوق العربي.
المستخدم يبحث عن إعلانات منافسين في Meta Ad Library للـ keyword: "{term}"
Search terms موجودة بالفعل: {context or "لا يوجد"}

اقترح 6 search terms إضافية مختلفة تساعد على اكتشاف المزيد من المنافسين والإعلانات المرتبطة.
فكر في: مرادفات، مشكلات العميل، أسماء منتجات شائعة، مصطلحات طبية/تقنية، عامية.
أجب بـ JSON فقط: {{"suggestions": ["term1", "term2", ...]}}"""

    try:
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 300,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=15,
        )
        text = resp.json()["content"][0]["text"]
        import json as _j
        clean = text.strip().replace("```json","").replace("```","").strip()
        return jsonify(_j.loads(clean))
    except Exception as e:
        return jsonify({"suggestions": [], "error": str(e)})


# ═══ Winners Clear ════════════════════════════════════════════════════════════

@app.route("/api/winners/clear", methods=["POST"])
@login_required
def api_winners_clear():
    """امسح سجل الـ winners المرسلة عشان تظهر من جديد في الـ digest."""
    conn = get_conn()
    conn.execute("DELETE FROM agent_events WHERE type = 'creative_digest_sent'")
    conn.commit()
    count = conn.execute("SELECT changes()").fetchone()
    conn.close()
    return jsonify({"ok": True, "message": "تم مسح سجل الـ Winners — ستظهر مجدداً في التقرير الجاي"})


# ═══ Market Intelligence ══════════════════════════════════════════════════════

@app.route("/api/market-intel", methods=["POST"])
@login_required
def api_market_intel():
    """تحليل شامل لجدوى السوق بناءً على بيانات الـ DB."""
    import requests as req
    import json as _j
    from datetime import timedelta, datetime, timezone

    data    = request.get_json(force=True) or {}
    keyword = data.get("keyword", "").strip()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    conn = get_conn()
    now  = datetime.now(timezone.utc)

    # ── جمع البيانات من الـ DB ──────────────────────────────────────────────
    # كل الإعلانات
    rows = conn.execute(
        """SELECT page_name, country,
                  EXTRACT(DAY FROM (now()-start_time))::int AS days,
                  body, title, start_time
           FROM competitor_snapshots
           WHERE start_time IS NOT NULL
             AND (stop_time IS NULL OR stop_time > now())
             AND (%s = '' OR
                  body    ILIKE %s OR
                  title   ILIKE %s OR
                  page_name ILIKE %s)
           ORDER BY days DESC LIMIT 300""",
        (keyword, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
    ).fetchall()

    # إحصائيات الدول
    by_country = conn.execute(
        """SELECT country, COUNT(*) as ads,
                  COUNT(DISTINCT page_name) as advertisers,
                  AVG(EXTRACT(DAY FROM (now()-start_time)))::int as avg_days
           FROM competitor_snapshots
           WHERE start_time IS NOT NULL AND (stop_time IS NULL OR stop_time > now())
             AND (%s = '' OR body ILIKE %s OR title ILIKE %s OR page_name ILIKE %s)
           GROUP BY country ORDER BY ads DESC""",
        (keyword, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
    ).fetchall()

    # المنافسون الجدد (آخر 14 يوم)
    new_entrants = conn.execute(
        """SELECT COUNT(DISTINCT page_name) FROM competitor_snapshots
           WHERE first_seen >= now() - INTERVAL '14 days'
             AND (%s = '' OR body ILIKE %s OR title ILIKE %s)""",
        (keyword, f"%{keyword}%", f"%{keyword}%")
    ).fetchone()[0]

    # توزيع الأعمار
    age_dist = conn.execute(
        """SELECT
             COUNT(*) FILTER (WHERE EXTRACT(DAY FROM (now()-start_time)) < 14) as new_ads,
             COUNT(*) FILTER (WHERE EXTRACT(DAY FROM (now()-start_time)) BETWEEN 14 AND 30) as mid_ads,
             COUNT(*) FILTER (WHERE EXTRACT(DAY FROM (now()-start_time)) BETWEEN 30 AND 90) as mature_ads,
             COUNT(*) FILTER (WHERE EXTRACT(DAY FROM (now()-start_time)) > 90) as veteran_ads,
             COUNT(DISTINCT page_name) as total_advertisers,
             COUNT(*) as total_ads,
             AVG(EXTRACT(DAY FROM (now()-start_time)))::int as avg_days,
             MAX(EXTRACT(DAY FROM (now()-start_time)))::int as max_days
           FROM competitor_snapshots
           WHERE start_time IS NOT NULL AND (stop_time IS NULL OR stop_time > now())
             AND (%s = '' OR body ILIKE %s OR title ILIKE %s OR page_name ILIKE %s)""",
        (keyword, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
    ).fetchone()

    conn.close()

    if not age_dist or age_dist[5] == 0:
        return jsonify({"error": "لا توجد بيانات كافية في الـ DB — شغّل run أول"})

    total_ads        = age_dist[5] or 0
    total_advertisers= age_dist[4] or 0
    avg_days         = age_dist[6] or 0
    max_days         = age_dist[7] or 0
    veteran_pct      = round((age_dist[3] or 0) / max(total_ads, 1) * 100)
    mature_pct       = round((age_dist[2] or 0) / max(total_ads, 1) * 100)

    # ── نص الإعلانات للتحليل ──────────────────────────────────────────────
    sample_texts = []
    seen = set()
    for r in rows[:50]:
        txt = (r[3] or r[4] or "").strip()[:200]
        if txt and txt not in seen:
            seen.add(txt)
            sample_texts.append({"advertiser": r[0], "country": r[1],
                                  "days": r[2], "text": txt})

    # ── إحصائيات ──────────────────────────────────────────────────────────
    country_data = [{"country": r[0], "ads": r[1],
                     "advertisers": r[2], "avg_days": r[3]}
                    for r in by_country[:8]]

    stats = {
        "keyword": keyword or "كل الإعلانات",
        "total_ads": total_ads,
        "total_advertisers": total_advertisers,
        "avg_days": avg_days,
        "max_days": max_days,
        "veteran_pct": veteran_pct,
        "mature_pct": mature_pct,
        "new_entrants_14d": new_entrants,
        "by_country": country_data,
        "age_dist": {
            "new": age_dist[0], "mid": age_dist[1],
            "mature": age_dist[2], "veteran": age_dist[3]
        }
    }

    # ── Claude Analysis ────────────────────────────────────────────────────
    if not api_key:
        return jsonify({"stats": stats, "analysis": None,
                        "error": "ANTHROPIC_API_KEY not set — add to dashboard variables"})

    prompt = f"""أنت محلل تسويقي متخصص في السوق العربي للـ ecommerce.
بناءً على بيانات إعلانات Meta Ad Library:

الـ Keyword: "{keyword or 'كل الإعلانات'}"
إجمالي الإعلانات: {total_ads} | المعلنون: {total_advertisers}
متوسط عمر الإعلان: {avg_days} يوم | أطول: {max_days} يوم
إعلانات +90 يوم (veterans): {veteran_pct}%
إعلانات 30-90 يوم (mature): {mature_pct}%
منافسون جدد آخر 14 يوم: {new_entrants}

توزيع الدول:
{_j.dumps(country_data, ensure_ascii=False, indent=2)}

عينة من الإعلانات الرابحة (+30 يوم):
{_j.dumps([x for x in sample_texts if (x.get('days') or 0) >= 30][:15], ensure_ascii=False, indent=2)}

أجب بـ JSON فقط بهذا الشكل:
{{
  "viability_score": 0-100,
  "viability_label": "ممتاز/جيد/متوسط/محفوف بالمخاطر/اتجنب",
  "signal": "شراء الآن/انتظر/اتجنب",
  "signal_reason": "سبب القرار في جملة",
  "best_country": "أفضل دولة للدخول",
  "best_country_reason": "سبب",
  "longevity_verdict": "تفسير توزيع الأعمار (هل المنتج يبيع؟)",
  "winning_angles": ["زاوية 1", "زاوية 2", "زاوية 3"],
  "price_points": ["سعر مذكور 1", "سعر 2"],
  "dominant_hooks": ["hook رابح 1", "hook 2"],
  "fatigue_alert": "هل في creative fatigue؟ وما هو؟",
  "entry_timing": "متى أفضل وقت للدخول؟",
  "avoid_angles": ["زاوية مشبعة تجنبها 1", "2"],
  "new_entrants_signal": "ماذا يعني دخول {new_entrants} منافس جديد؟",
  "summary": "ملخص تنفيذي في 2-3 جمل"
}}"""

    try:
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-sonnet-4-6", "max_tokens": 1500,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        text  = resp.json()["content"][0]["text"]
        clean = text.strip().replace("```json","").replace("```","").strip()
        analysis = _j.loads(clean)
        return jsonify({"stats": stats, "analysis": analysis})
    except Exception as e:
        return jsonify({"stats": stats, "analysis": None, "error": str(e)})

