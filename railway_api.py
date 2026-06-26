"""
Trigger the Scout cron service via Railway GraphQL API.

Required env vars:
  RAILWAY_API_TOKEN          — Personal Account Token (Account Settings → Tokens)
  RAILWAY_SCOUT_SERVICE_ID   — Scout service ID
  RAILWAY_ENVIRONMENT_ID     — environment ID
"""

import os
import requests

RAILWAY_API = "https://backboard.railway.app/graphql/v2"


def _post(token: str, query: str, variables: dict = None) -> dict:
    resp = requests.post(
        RAILWAY_API,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type":  "application/json"},
        timeout=15,
    )
    return resp.json()


def _get_latest_deployment_id(token: str, service_id: str, environment_id: str) -> str | None:
    """اجيب آخر deployment ID للـ Scout service."""
    query = """
    query Deployments($serviceId: String!, $environmentId: String!) {
      deployments(
        input: { serviceId: $serviceId, environmentId: $environmentId }
      ) {
        edges { node { id status createdAt } }
      }
    }
    """
    data = _post(token, query, {"serviceId": service_id, "environmentId": environment_id})
    edges = (data.get("data") or {}).get("deployments", {}).get("edges", [])
    if not edges:
        return None
    # آخر deployment (الأحدث)
    return edges[-1]["node"]["id"]


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

    # ── Step 1: اجيب الـ deployment ID ───────────────────────────────────
    deployment_id = _get_latest_deployment_id(token, service_id, environment_id)
    if not deployment_id:
        return False, "مش قادر أجيب الـ deployment ID — تحقق من RAILWAY_SCOUT_SERVICE_ID و RAILWAY_ENVIRONMENT_ID"

    # ── Step 2: deploymentInstanceExecutionCreate (زرار Trigger في Railway UI) ──
    mutation_exec = """
    mutation ExecutionCreate($input: DeploymentInstanceExecutionCreateInput!) {
      deploymentInstanceExecutionCreate(input: $input)
    }
    """
    try:
        data = _post(token, mutation_exec, {
            "input": {"deploymentId": deployment_id}
        })
        if "errors" not in data:
            return True, f"✅ تم تشغيل الـ Scout — تحقق من Scout → Cron Runs"
        exec_error = data["errors"][0].get("message", str(data["errors"]))
    except Exception as e:
        exec_error = str(e)

    # ── Step 3: deploymentRestart fallback ────────────────────────────────
    mutation_restart = """
    mutation Restart($id: String!) { deploymentRestart(id: $id) }
    """
    try:
        data = _post(token, mutation_restart, {"id": deployment_id})
        if "errors" not in data:
            return True, f"✅ تم restart الـ deployment (id: {deployment_id[:8]}...) — تحقق من Scout → Deployments"
        restart_error = data["errors"][0].get("message", str(data["errors"]))
    except Exception as e:
        restart_error = str(e)

    # ── Step 4: serviceInstanceRedeploy fallback ──────────────────────────
    mutation_redeploy = """
    mutation Redeploy($serviceId: String!, $environmentId: String!) {
      serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
    }
    """
    try:
        data = _post(token, mutation_redeploy, {
            "serviceId": service_id, "environmentId": environment_id
        })
        if "errors" not in data:
            return True, "✅ تم الـ redeploy — تحقق من Scout → Deployments"
        redeploy_error = data["errors"][0].get("message", str(data["errors"]))
    except Exception as e:
        redeploy_error = str(e)

    return False, (
        f"فشلت كل المحاولات:\n"
        f"1. deploymentInstanceExecutionCreate: {exec_error}\n"
        f"2. deploymentRestart: {restart_error}\n"
        f"3. serviceInstanceRedeploy: {redeploy_error}"
    )