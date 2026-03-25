"""
Tenant Portal — B2B SaaS Provisioning Platform (Flask)

No observability. Run `Observe this project.` to add OpenTelemetry.

This is the API gateway for a SaaS tenant provisioning platform. Downstream:
  - billing-service     — Stripe subscription management
  - provisioner         — Kubernetes namespace + resource allocation
  - dns-manager         — custom subdomain provisioning
  - notification-hub    — welcome/upgrade emails + Slack
  - compliance-auditor  — GDPR/SOC2 event logging

Routes:
  GET  /health                        — liveness probe
  POST /tenants                       — provision new tenant
  GET  /tenants/{tenant_id}           — get tenant details
  POST /tenants/{tenant_id}/upgrade   — upgrade plan
  DELETE /tenants/{tenant_id}         — deactivate tenant (GDPR)
"""

import os
import uuid
import random
import logging
import time
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
tenants = {}


PLAN_LIMITS = {
    "starter":    {"cpu_cores": 2,  "memory_gb": 4,   "storage_gb": 20,  "price_monthly": 49},
    "pro":        {"cpu_cores": 8,  "memory_gb": 16,  "storage_gb": 100, "price_monthly": 199},
    "enterprise": {"cpu_cores": 32, "memory_gb": 64,  "storage_gb": 500, "price_monthly": 999},
}


def call_billing_service(tenant_id: str, plan: str, email: str) -> dict:
    """Create Stripe subscription."""
    time.sleep(random.uniform(0.080, 0.200))
    # 15% payment failure
    if random.random() < 0.15:
        return {"ok": False, "reason": "card_declined"}
    price = PLAN_LIMITS[plan]["price_monthly"]
    return {
        "ok": True,
        "subscription_id": f"sub_{uuid.uuid4().hex[:16]}",
        "amount_usd": price,
        "billing_cycle": "monthly",
    }


def call_provisioner(tenant_id: str, plan: str) -> dict:
    """Provision Kubernetes namespace and resources."""
    limits = PLAN_LIMITS[plan]
    time.sleep(random.uniform(0.500, 2.000))  # k8s provisioning takes time
    # 5% provisioning failure
    if random.random() < 0.05:
        raise RuntimeError(f"provisioner: failed to allocate namespace for {tenant_id}")
    return {
        "namespace": f"tenant-{tenant_id[:8]}",
        "cpu_cores": limits["cpu_cores"],
        "memory_gb": limits["memory_gb"],
        "storage_gb": limits["storage_gb"],
        "cluster":   "us-east-1-prod",
    }


def call_dns_manager(tenant_id: str, domain: str) -> dict:
    """Provision subdomain."""
    time.sleep(random.uniform(0.100, 0.500))
    subdomain = f"{domain}.app.example.com"
    return {"ok": True, "subdomain": subdomain, "ttl": 300}


def call_notification_hub(tenant_id: str, email: str, event: str, plan: str) -> None:
    """Send welcome/notification email."""
    time.sleep(random.uniform(0.020, 0.080))


def call_compliance_auditor(tenant_id: str, event: str, actor: str) -> None:
    """Log compliance event."""
    time.sleep(random.uniform(0.005, 0.020))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/tenants", methods=["POST"])
def create_tenant():
    body   = request.get_json(force=True) or {}
    email  = body.get("email")
    plan   = body.get("plan", "starter")
    domain = body.get("domain", uuid.uuid4().hex[:8])

    if not email:
        return jsonify({"error": "email required"}), 400
    if plan not in PLAN_LIMITS:
        return jsonify({"error": f"unknown plan: {plan}"}), 400

    tenant_id = f"ten_{uuid.uuid4().hex[:12]}"

    # Step 1: Billing
    billing = call_billing_service(tenant_id, plan, email)
    if not billing["ok"]:
        return jsonify({"error": "payment_failed", "reason": billing["reason"]}), 402

    # Step 2: Provision infrastructure
    try:
        infra = call_provisioner(tenant_id, plan)
    except RuntimeError as e:
        logger.error("Provisioning failed for tenant %s: %s", tenant_id, e)
        return jsonify({"error": "provisioning_failed", "detail": str(e)}), 503

    # Step 3: DNS
    dns = call_dns_manager(tenant_id, domain)

    # Step 4: Notify
    call_notification_hub(tenant_id, email, "tenant_created", plan)

    # Step 5: Audit
    call_compliance_auditor(tenant_id, "tenant_created", email)

    tenant = {
        "tenant_id":       tenant_id,
        "email":           email,
        "plan":            plan,
        "status":          "active",
        "subdomain":       dns["subdomain"],
        "namespace":       infra["namespace"],
        "subscription_id": billing["subscription_id"],
        "billing_amount":  billing["amount_usd"],
    }
    tenants[tenant_id] = tenant

    logger.info("Tenant created: %s plan=%s email=%s", tenant_id, plan, email)
    return jsonify(tenant), 201


@app.route("/tenants/<tenant_id>")
def get_tenant(tenant_id):
    tenant = tenants.get(tenant_id)
    if not tenant:
        return jsonify({"error": "not found"}), 404
    return jsonify(tenant)


@app.route("/tenants/<tenant_id>/upgrade", methods=["POST"])
def upgrade_tenant(tenant_id):
    tenant = tenants.get(tenant_id)
    if not tenant:
        return jsonify({"error": "not found"}), 404

    body     = request.get_json(force=True) or {}
    new_plan = body.get("plan")
    if not new_plan or new_plan not in PLAN_LIMITS:
        return jsonify({"error": f"unknown plan: {new_plan}"}), 400

    billing = call_billing_service(tenant_id, new_plan, tenant["email"])
    if not billing["ok"]:
        return jsonify({"error": "payment_failed"}), 402

    call_provisioner(tenant_id, new_plan)
    call_notification_hub(tenant_id, tenant["email"], "plan_upgraded", new_plan)
    call_compliance_auditor(tenant_id, "plan_upgraded", tenant["email"])

    tenants[tenant_id]["plan"] = new_plan
    tenants[tenant_id]["billing_amount"] = billing["amount_usd"]

    logger.info("Tenant upgraded: %s -> %s", tenant_id, new_plan)
    return jsonify(tenants[tenant_id])


@app.route("/tenants/<tenant_id>", methods=["DELETE"])
def deactivate_tenant(tenant_id):
    tenant = tenants.get(tenant_id)
    if not tenant:
        return jsonify({"error": "not found"}), 404

    call_compliance_auditor(tenant_id, "tenant_deactivated_gdpr", "admin")
    call_notification_hub(tenant_id, tenant["email"], "tenant_deactivated", tenant["plan"])

    tenants[tenant_id]["status"] = "deactivated"
    logger.info("Tenant deactivated (GDPR): %s", tenant_id)
    return jsonify({"tenant_id": tenant_id, "status": "deactivated"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6004))
    app.run(host="0.0.0.0", port=port, debug=False)
