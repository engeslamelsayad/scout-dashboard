"""
Trigger the Scout cron service via Railway GraphQL API.

Required env vars:
  RAILWAY_API_TOKEN          — Personal Account Token (Account Settings → Tokens)
  RAILWAY_SCOUT_SERVICE_ID   — Scout service ID (from Railway URL or service Settings)
  RAILWAY_ENVIRONMENT_ID     — environment ID (from Railway URL)

How to find IDs:
  Service ID:     Railway → Scout service → Settings → scroll down → "Service ID"
                  OR from URL: railway.app/project/XXX/service/[THIS_PART]
  Environment ID: Railway → Project Settings → Environments → click env → URL
                  OR from URL: railway.app/project/XXX/environment/[THIS_PART]
"""

import os
import requests

RAILWAY_API = "https://backboard.railway.app/graphql/v2"


def _post(token: str, query: str, variables: dict) -> dict:
    resp = requests.post(
        RAILWAY_API,
        json={"query": query, "variables": variables},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        timeout=15,
    )
    return resp.json()


def trigger_scout_run() -> tuple[bool, str]:
    token          = os.environ.get("RAILWAY_API_TOKEN", "")
    service_id     = os.environ.get("RAILWAY_SCOUT_SERVICE_ID", "")
    environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID", "")

    missing = [k for k, v in {
        "RAILWAY_API_TOKEN":        token,
        "RAILWAY_SCOUT_SERVICE_ID": service_id,
        "RAILWAY_ENVIRONMENT_ID":   environment_id,
    }.items() if not v]

    if missing:
        return False, f"Variables ناقصة: {', '.join(missing)}"

    # ── محاولة 1: cronJobTrigger (للـ cron services) ──────────────────────
    mutation_cron = """
    mutation CronJobTrigger($serviceId: String!, $environmentId: String!) {
      cronJobTrigger(serviceId: $serviceId, environmentId: $environmentId)
    }
    """
    try:
        data = _post(token, mutation_cron, {
            "serviceId":     service_id,
            "environmentId": environment_id,
        })
        if "errors" not in data:
            return True, "✅ تم تشغيل الـ Scout — تحقق من Scout → Cron Runs"
        cron_error = data["errors"][0].get("message", "")
    except Exception as e:
        cron_error = str(e)

    # ── محاولة 2: serviceInstanceRedeploy (fallback) ──────────────────────
    mutation_redeploy = """
    mutation Redeploy($serviceId: String!, $environmentId: String!) {
      serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
    }
    """
    try:
        data = _post(token, mutation_redeploy, {
            "serviceId":     service_id,
            "environmentId": environment_id,
        })
        if "errors" not in data:
            return True, "✅ تم إرسال طلب الـ redeploy — تحقق من Scout → Deployments"
        redeploy_error = data["errors"][0].get("message", "")
    except Exception as e:
        redeploy_error = str(e)

    return False, (
        f"فشلت المحاولتين:\n"
        f"cronJobTrigger: {cron_error}\n"
        f"serviceInstanceRedeploy: {redeploy_error}\n\n"
        f"تحقق من:\n"
        f"1. RAILWAY_API_TOKEN = Personal token (مش Project token)\n"
        f"2. RAILWAY_SCOUT_SERVICE_ID = ID الـ Scout service بالظبط\n"
        f"3. RAILWAY_ENVIRONMENT_ID = ID الـ production environment"
    )