"""
Lightweight DB layer for the Dashboard service.
Read-only queries + config save/load. No Scout-specific code.
Shares the same Railway Postgres with the Scout service.
"""

import json
from datetime import datetime, timezone, timedelta

import psycopg
from pgvector.psycopg import register_vector


def get_conn(database_url: str):
    conn = psycopg.connect(database_url)
    register_vector(conn)
    return conn


# ── Config ───────────────────────────────────────────────────────────────────

def load_config(conn) -> dict:
    row = conn.execute(
        "SELECT data FROM scout_config WHERE id = 1"
    ).fetchone()
    if row:
        d = row[0]
        return d if isinstance(d, dict) else json.loads(d)
    return {}


def save_config(conn, data: dict) -> None:
    conn.execute(
        """INSERT INTO scout_config (id, data, updated_at, updated_by)
           VALUES (1, %s, now(), 'dashboard')
           ON CONFLICT (id) DO UPDATE
           SET data = EXCLUDED.data,
               updated_at = now(),
               updated_by = 'dashboard'""",
        (json.dumps(data, ensure_ascii=False),),
    )
    conn.commit()


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(conn) -> dict:
    total = conn.execute(
        "SELECT COUNT(*) FROM competitor_snapshots"
    ).fetchone()[0]

    by_country = conn.execute(
        """SELECT country, COUNT(*)
           FROM competitor_snapshots
           GROUP BY country ORDER BY 2 DESC"""
    ).fetchall()

    last_event = conn.execute(
        "SELECT type, confidence, ts FROM agent_events ORDER BY ts DESC LIMIT 1"
    ).fetchone()

    last_run = conn.execute(
        "SELECT MAX(run_date) FROM clusters"
    ).fetchone()[0]

    return {
        "total_ads": total,
        "by_country": [{"country": r[0], "count": r[1]} for r in by_country],
        "last_event": {
            "type":       last_event[0],
            "confidence": round(float(last_event[1] or 0), 2),
            "ts":         last_event[2].strftime("%Y-%m-%d %H:%M UTC") if last_event[2] else "—",
        } if last_event else {},
        "last_run": last_run.isoformat() if last_run else "لم يُشغَّل بعد",
    }


# ── Runs history ──────────────────────────────────────────────────────────────

def get_runs(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """SELECT id, type, confidence, ts, payload
           FROM agent_events
           ORDER BY ts DESC LIMIT %s""",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        payload = r[4]
        if isinstance(payload, str):
            try: payload = json.loads(payload)
            except: payload = {}
        out.append({
            "id":         r[0],
            "type":       r[1],
            "confidence": round(float(r[2] or 0), 2),
            "ts":         r[3].strftime("%Y-%m-%d %H:%M") if r[3] else "",
            "theme":      (payload or {}).get("theme", ""),
        })
    return out


# ── Winners ───────────────────────────────────────────────────────────────────

def get_winners(conn, min_days: int = 14, limit: int = 40) -> list[dict]:
    rows = conn.execute(
        """SELECT ad_id, page_name, country, body, snapshot_url,
                  EXTRACT(DAY FROM (now() - start_time))::int AS days
           FROM competitor_snapshots
           WHERE start_time IS NOT NULL
             AND (stop_time IS NULL OR stop_time > now())
           ORDER BY start_time ASC
           LIMIT 200"""
    ).fetchall()
    cols = ["ad_id", "page_name", "country", "body", "snapshot_url", "days"]
    result = [dict(zip(cols, r)) for r in rows if (r[5] or 0) >= min_days]
    result.sort(key=lambda x: x["days"] or 0, reverse=True)
    return result[:limit]


# ── Competitor activity ───────────────────────────────────────────────────────

def get_competitor_activity(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT page_name, country,
             COUNT(*) FILTER (WHERE first_seen >= now() - INTERVAL '7 days')  AS this_week,
             COUNT(*) FILTER (WHERE first_seen >= now() - INTERVAL '14 days'
                                AND first_seen <  now() - INTERVAL '7 days')  AS last_week,
             COUNT(*) AS total
           FROM competitor_snapshots
           GROUP BY page_name, country
           HAVING COUNT(*) >= 2
           ORDER BY this_week DESC, total DESC
           LIMIT 30"""
    ).fetchall()
    cols = ["page_name", "country", "this_week", "last_week", "total"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["delta"] = (d["this_week"] or 0) - (d["last_week"] or 0)
        out.append(d)
    return out


# ── Themes history ────────────────────────────────────────────────────────────

def get_themes(conn, limit: int = 80) -> list[dict]:
    rows = conn.execute(
        """SELECT run_date, theme, size, competitor_count
           FROM clusters
           ORDER BY run_date DESC, size DESC
           LIMIT %s""",
        (limit,),
    ).fetchall()
    cols = ["run_date", "theme", "size", "competitor_count"]
    return [dict(zip(cols, r)) | {"run_date": str(r[0])} for r in rows]


# ── Swipe file ────────────────────────────────────────────────────────────────

def get_swipe(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT id, ad_id, page_name, country, body, snapshot_url,
                  notes, tags, saved_at
           FROM swipe_file
           ORDER BY saved_at DESC"""
    ).fetchall()
    cols = ["id", "ad_id", "page_name", "country", "body",
            "snapshot_url", "notes", "tags", "saved_at"]
    return [
        dict(zip(cols, r)) | {"saved_at": r[8].strftime("%Y-%m-%d") if r[8] else ""}
        for r in rows
    ]


def add_swipe(conn, ad_id, page_name, country, body, snapshot_url, notes, tags) -> None:
    conn.execute(
        """INSERT INTO swipe_file
           (ad_id, page_name, country, body, snapshot_url, notes, tags)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (ad_id, page_name, country, body, snapshot_url, notes, tags),
    )
    conn.commit()


def delete_swipe(conn, item_id: int) -> None:
    conn.execute("DELETE FROM swipe_file WHERE id = %s", (item_id,))
    conn.commit()
