"""
Trigger the Scout cron service via Railway GraphQL API.

Required env vars:
  RAILWAY_API_TOKEN          — Personal Account Token
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


def _get_latest_deployment_id(token, service_id, environment_id) -> str | None:
    """اجيب آخر deployment ID للـ Scout service."""
    query = """
    query Deps($serviceId: String!, $environmentId: String!) {
      deployments(input: {serviceId: $serviceId, environmentId: $environmentId}) {
        edges { node { id status } }
      }
    }
    """
    data = _post(token, query, {"serviceId": service_id, "environmentId": environment_id})
    edges = (data.get("data") or {}).get("deployments", {}).get("edges", [])
    return edges[-1]["node"]["id"] if edges else None


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

    deployment_id = _get_latest_deployment_id(token, service_id, environment_id)
    errors = []

    # ── 1: deploymentInstanceExecutionCreate بـ deploymentId ──────────────
    if deployment_id:
        m = """mutation($input: DeploymentInstanceExecutionCreateInput!) {
          deploymentInstanceExecutionCreate(input: $input) }"""
        d = _post(token, m, {"input": {"deploymentId": deployment_id}})
        if "errors" not in d:
            return True, "✅ تم تشغيل الـ Scout — تحقق من Scout → Cron Runs بعد دقيقتين"
        errors.append(f"exec(deploymentId): {d['errors'][0].get('message','')}")

    # ── 2: deploymentInstanceExecutionCreate بـ serviceId + environmentId ──
    m2 = """mutation($input: DeploymentInstanceExecutionCreateInput!) {
      deploymentInstanceExecutionCreate(input: $input) }"""
    d2 = _post(token, m2, {"input": {
        "serviceId": service_id, "environmentId": environment_id}})
    if "errors" not in d2:
        return True, "✅ تم تشغيل الـ Scout — تحقق من Scout → Cron Runs بعد دقيقتين"
    errors.append(f"exec(serviceId): {d2['errors'][0].get('message','')}")

    # ── 3: serviceInstanceDeployV2 (يرجع deployment ID — يشغّل run جديد) ──
    m3 = """mutation($environmentId: String!, $serviceId: String!) {
      serviceInstanceDeployV2(environmentId: $environmentId, serviceId: $serviceId) }"""
    d3 = _post(token, m3, {"environmentId": environment_id, "serviceId": service_id})
    if "errors" not in d3:
        new_id = d3.get("data", {}).get("serviceInstanceDeployV2", "")
        return True, f"✅ تم تشغيل الـ Scout (deployment: {str(new_id)[:8]}) — انتظر 2-3 دقائق للـ build"
    errors.append(f"deployV2: {d3['errors'][0].get('message','')}")

    # ── 4: serviceInstanceRedeploy (fallback دايماً بيشتغل) ───────────────
    m4 = """mutation($serviceId: String!, $environmentId: String!) {
      serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId) }"""
    d4 = _post(token, m4, {"serviceId": service_id, "environmentId": environment_id})
    if "errors" not in d4:
        return True, (
            "✅ تم إرسال طلب الـ redeploy للـ Scout\n"
            "⏳ انتظر 2-3 دقائق للـ build ثم تحقق من Scout → Cron Runs"
        )
    errors.append(f"redeploy: {d4['errors'][0].get('message','')}")

    return False, "فشلت كل المحاولات:\n" + "\n".join(errors)