"""
Trigger the Scout by inserting a run_trigger record in the shared Postgres DB.
The Scout checks for pending triggers every 5 minutes (*/5 cron).
Max wait: 5 minutes.

NO Railway API token needed for this — just DATABASE_URL.
"""

import os
import psycopg
from pgvector.psycopg import register_vector


def trigger_scout_run() -> tuple[bool, str]:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return False, "DATABASE_URL غير موجود"

    try:
        conn = psycopg.connect(database_url)
        register_vector(conn)
        row = conn.execute(
            "INSERT INTO run_triggers (source) VALUES ('dashboard') RETURNING id"
        ).fetchone()
        conn.commit()
        conn.close()
        trigger_id = row[0]
        return True, (
            f"✅ تم إنشاء trigger #{trigger_id}\n"
            f"⏳ الـ Scout هيلتقطه خلال 5 دقائق كحد أقصى\n"
            f"تحقق من Scout → Cron Runs لمتابعة التشغيل"
        )
    except Exception as e:
        return False, f"❌ {e}"
