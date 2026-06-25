"""
Trigger the Scout service via Railway GraphQL API.

Required env vars:
  RAILWAY_API_TOKEN          — from railway.app → Account Settings → Tokens
  RAILWAY_SCOUT_SERVICE_ID   — Scout service ID (from Railway URL)
  RAILWAY_ENVIRONMENT_ID     — environment ID (from Railway URL)

How to find the IDs:
  1. Open your Railway project
  2. Click on the Scout service
  3. The URL looks like:
     railway.app/project/PROJECT_ID/service/SERVICE_ID
  4. For environment ID: click on the environment name (e.g. "Production")
     URL: railway.app/project/PROJECT_ID/environment/ENVIRONMENT_ID
"""

import os
import requests

RAILWAY_API = "https://backboard.railway.app/graphql/v2"


def trigger_scout_run() -> tuple[bool, str]:
    """Trigger an immediate run of the Scout cron service via Railway API."""
    token        = os.environ.get("RAILWAY_API_TOKEN", "")
    service_id   = os.environ.get("RAILWAY_SCOUT_SERVICE_ID", "")
    environment_id = os.environ.get("RAILWAY_ENVIRONMENT_ID", "")

    missing = [k for k, v in {
        "RAILWAY_API_TOKEN":         token,
        "RAILWAY_SCOUT_SERVICE_ID":  service_id,
        "RAILWAY_ENVIRONMENT_ID":    environment_id,
    }.items() if not v]

    if missing:
        return False, f"Variables ناقصة: {', '.join(missing)}"

    # Railway mutation to redeploy / trigger a service instance
    mutation = """
    mutation ServiceInstanceRedeploy($serviceId: String!, $environmentId: String!) {
      serviceInstanceRedeploy(
        serviceId: $serviceId
        environmentId: $environmentId
      )
    }
    """
    try:
        resp = requests.post(
            RAILWAY_API,
            json={
                "query":     mutation,
                "variables": {
                    "serviceId":     service_id,
                    "environmentId": environment_id,
                },
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            timeout=15,
        )
        data = resp.json()
        if "errors" in data:
            msg = data["errors"][0].get("message", "Unknown Railway API error")
            return False, f"Railway API error: {msg}"
        return True, "✅ تم إرسال طلب التشغيل — تحقق من Scout → Deployments"
    except Exception as e:
        return False, f"❌ {e}"
