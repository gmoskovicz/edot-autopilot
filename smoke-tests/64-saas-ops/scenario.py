#!/usr/bin/env python3
"""
B2B SaaS Tenant Provisioning Platform — Distributed Tracing Scenario
======================================================================

Services modeled:
  tenant-portal → billing-service
               → provisioner → resource-allocator
               → dns-manager
               → notification-hub
               → compliance-auditor

25 trace scenarios with realistic error mix:
  40% new tenant provisioning (full happy path)
  20% plan upgrade (pro → enterprise)
  15% payment failure
  10% quota exceeded / auto-scale
  10% tenant deactivation (GDPR)
   5% provisioning failure + rollback

Run:
    cd smoke-tests
    python3 64-saas-ops/scenario.py
"""

import os, sys, uuid, time, random
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap

from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

ENDPOINT = os.environ["ELASTIC_OTLP_ENDPOINT"]
API_KEY  = os.environ["ELASTIC_API_KEY"]
ENV      = os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test")

propagator = TraceContextTextMapPropagator()

# ── Per-service O11y bootstrap ────────────────────────────────────────────────
portal      = O11yBootstrap("tenant-portal",      ENDPOINT, API_KEY, ENV)
billing     = O11yBootstrap("billing-service",    ENDPOINT, API_KEY, ENV)
provisioner = O11yBootstrap("provisioner",        ENDPOINT, API_KEY, ENV)
allocator   = O11yBootstrap("resource-allocator", ENDPOINT, API_KEY, ENV)
dns         = O11yBootstrap("dns-manager",        ENDPOINT, API_KEY, ENV)
notifhub    = O11yBootstrap("notification-hub",   ENDPOINT, API_KEY, ENV)
compliance  = O11yBootstrap("compliance-auditor", ENDPOINT, API_KEY, ENV)

# ── Metrics instruments ───────────────────────────────────────────────────────
# tenant-portal
tp_requests       = portal.meter.create_counter("tenant.requests",           description="Tenant management API requests")
tp_latency        = portal.meter.create_histogram("provisioning.duration_ms",description="Provisioning end-to-end latency", unit="ms")
tp_errors         = portal.meter.create_counter("tenant.errors",             description="Tenant operation errors by type")

# billing-service
bil_mrr           = billing.meter.create_histogram("billing.mrr_usd",        description="Monthly recurring revenue delta", unit="USD")
bil_payments      = billing.meter.create_counter("billing.payments",         description="Payment attempts")
bil_failures      = billing.meter.create_counter("billing.payment_failures", description="Payment failures by reason")
bil_upgrades      = billing.meter.create_counter("billing.plan_upgrades",    description="Plan upgrade events")

# provisioner
prov_created      = provisioner.meter.create_counter("tenants.provisioned",  description="Tenants provisioned")
prov_duration     = provisioner.meter.create_histogram("provisioner.steps_ms",description="Individual provisioning step duration", unit="ms")
prov_rollbacks    = provisioner.meter.create_counter("provisioner.rollbacks", description="Provisioning rollbacks")
prov_failures     = provisioner.meter.create_counter("provisioner.failures",  description="Provisioning failures")

# resource-allocator
res_cores         = allocator.meter.create_histogram("resources.allocated_cores",   description="CPU cores allocated", unit="cores")
res_memory        = allocator.meter.create_histogram("resources.allocated_memory_gb",description="Memory allocated", unit="GB")
res_violations    = allocator.meter.create_counter("quota.violations",              description="Quota violation events")
res_autoscale     = allocator.meter.create_counter("quota.autoscale_events",        description="Auto-scale triggered")

# dns-manager
dns_zones         = dns.meter.create_counter("dns.zones_created",            description="DNS zones created")
ssl_certs         = dns.meter.create_counter("ssl.certificates_issued",      description="SSL certs issued")
dns_latency       = dns.meter.create_histogram("dns.provision_ms",           description="DNS provisioning latency", unit="ms")

# notification-hub
notif_sent        = notifhub.meter.create_counter("notifications.sent",      description="Notifications sent by channel")
notif_latency     = notifhub.meter.create_histogram("notification.send_ms",  description="Notification delivery latency", unit="ms")

# compliance-auditor
comp_checks       = compliance.meter.create_counter("compliance.checks_passed",  description="Compliance checks passed")
comp_violations   = compliance.meter.create_counter("compliance.violations",     description="Compliance violations found")
gdpr_exports      = compliance.meter.create_counter("gdpr.data_exports",         description="GDPR data export requests")

# Observable gauge callbacks
def _tenant_active_cb(options):
    from opentelemetry.metrics import Observation
    yield Observation(random.randint(45, 180), {"region": "us-east-1"})

def _resource_pool_cb(options):
    from opentelemetry.metrics import Observation
    yield Observation(random.uniform(0.45, 0.85), {"resource": "cpu"})

billing.meter.create_observable_gauge(
    "billing.active_tenants", [_tenant_active_cb],
    description="Number of active tenants")
allocator.meter.create_observable_gauge(
    "resource.pool_utilization", [_resource_pool_cb],
    description="Resource pool utilization ratio")


# ── Plans & tenant profiles ────────────────────────────────────────────────────
PLANS = {
    "starter": {
        "price_usd": 49.0,  "cpu_cores": 2,  "memory_gb": 4,   "storage_gb": 50,
        "max_users": 10,    "sla": "99.5%",   "support": "community"
    },
    "pro": {
        "price_usd": 299.0, "cpu_cores": 8,  "memory_gb": 16,  "storage_gb": 500,
        "max_users": 100,   "sla": "99.9%",   "support": "email+chat"
    },
    "enterprise": {
        "price_usd": 1499.0,"cpu_cores": 32, "memory_gb": 128, "storage_gb": 5000,
        "max_users": -1,    "sla": "99.99%",  "support": "24x7-dedicated"
    },
    "enterprise-plus": {
        "price_usd": 4999.0,"cpu_cores": 128,"memory_gb": 512, "storage_gb": 50000,
        "max_users": -1,    "sla": "99.999%", "support": "white-glove"
    },
}

REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "eu-central-1", "ap-southeast-1", "ap-northeast-1"]

TENANTS = [
    {"id": "TEN-001", "name": "Acme Startup",          "plan": "starter",          "region": "us-east-1",    "domain": "acme-startup.app.saas.io",   "billing_email": "billing@acme-startup.com",    "compliance": ["soc2"],           "gdpr_subject": False},
    {"id": "TEN-002", "name": "BlueSky Analytics",     "plan": "pro",              "region": "us-west-2",    "domain": "bluesky.app.saas.io",         "billing_email": "finance@bluesky.ai",          "compliance": ["soc2", "iso27001"],"gdpr_subject": False},
    {"id": "TEN-003", "name": "EuroFinance AG",        "plan": "enterprise",       "region": "eu-central-1", "domain": "eurofinance.app.saas.io",     "billing_email": "it@eurofinance.de",           "compliance": ["soc2", "gdpr", "pci"],"gdpr_subject": True},
    {"id": "TEN-004", "name": "MediCorp Solutions",    "plan": "enterprise",       "region": "us-east-1",    "domain": "medicorp.app.saas.io",        "billing_email": "ops@medicorp.health",         "compliance": ["hipaa", "soc2"],  "gdpr_subject": False},
    {"id": "TEN-005", "name": "TechVentures Ltd",      "plan": "pro",              "region": "ap-southeast-1","domain": "techventures.app.saas.io",   "billing_email": "admin@techventures.sg",       "compliance": ["soc2"],           "gdpr_subject": False},
    {"id": "TEN-006", "name": "Nordic Cloud AS",       "plan": "enterprise-plus",  "region": "eu-west-1",    "domain": "nordiccloud.app.saas.io",     "billing_email": "cto@nordiccloud.no",          "compliance": ["soc2", "gdpr"],   "gdpr_subject": True},
    {"id": "TEN-007", "name": "DataPulse Inc",         "plan": "starter",          "region": "us-east-1",    "domain": "datapulse.app.saas.io",       "billing_email": "pay@datapulse.io",            "compliance": ["soc2"],           "gdpr_subject": False},
    {"id": "TEN-008", "name": "QuantumRetail Co",      "plan": "pro",              "region": "us-west-2",    "domain": "quantumretail.app.saas.io",   "billing_email": "ar@quantumretail.shop",       "compliance": ["pci", "soc2"],    "gdpr_subject": False},
    {"id": "TEN-009", "name": "HealthFirst Platform",  "plan": "enterprise",       "region": "us-east-1",    "domain": "healthfirst.app.saas.io",     "billing_email": "billing@healthfirst.care",    "compliance": ["hipaa", "soc2"],  "gdpr_subject": False},
    {"id": "TEN-010", "name": "Solaris Technologies",  "plan": "enterprise-plus",  "region": "us-east-1",    "domain": "solaris.app.saas.io",         "billing_email": "finance@solaris.tech",        "compliance": ["soc2", "iso27001"],"gdpr_subject": False},
    {"id": "TEN-011", "name": "GreenLeaf SaaS",        "plan": "starter",          "region": "eu-west-1",    "domain": "greenleaf.app.saas.io",       "billing_email": "pay@greenleaf.eco",           "compliance": ["gdpr"],           "gdpr_subject": True},
    {"id": "TEN-012", "name": "Velocity CRM",          "plan": "pro",              "region": "us-east-1",    "domain": "velocitycrm.app.saas.io",     "billing_email": "billing@velocitycrm.com",    "compliance": ["soc2"],           "gdpr_subject": False},
    {"id": "TEN-013", "name": "Pacific Logistics",     "plan": "enterprise",       "region": "ap-northeast-1","domain": "paclogistics.app.saas.io",   "billing_email": "it@paclogistics.jp",          "compliance": ["iso27001"],       "gdpr_subject": False},
    {"id": "TEN-014", "name": "LegalDocs Online",      "plan": "pro",              "region": "eu-central-1", "domain": "legaldocs.app.saas.io",       "billing_email": "finance@legaldocs.eu",        "compliance": ["gdpr", "soc2"],   "gdpr_subject": True},
    {"id": "TEN-015", "name": "RocketShip Startup",    "plan": "starter",          "region": "us-west-2",    "domain": "rocketship.app.saas.io",      "billing_email": "admin@rocketship.dev",        "compliance": [],                 "gdpr_subject": False},
]

COMPLIANCE_FRAMEWORKS = ["soc2", "gdpr", "hipaa", "pci", "iso27001"]
BILLING_ERRORS        = ["card_expired", "insufficient_funds", "do_not_honor",
                          "card_declined", "billing_address_mismatch"]
SSL_PROVIDERS         = ["lets-encrypt", "digicert", "sectigo"]


# ── Helper ─────────────────────────────────────────────────────────────────────
def inject_traceparent(span) -> str:
    sc = span.get_span_context()
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-01"

def extract_context(tp: str):
    return propagator.extract({"traceparent": tp})


# ── Service functions ──────────────────────────────────────────────────────────

def svc_billing(operation_id: str, tenant: dict, plan: str, action: str,
                 parent_tp: str, force_failure: bool = False) -> tuple:
    """Stripe subscription management (create, upgrade, cancel)."""
    parent_ctx   = extract_context(parent_tp)
    plan_details = PLANS[plan]
    t0 = time.time()

    with portal.tracer.start_as_current_span(
        "http.client.billing_service", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "billing-service",
                    "http.url": "http://billing-service/api/v2/subscriptions",
                    "operation.id": operation_id, "tenant.id": tenant["id"],
                    "billing.action": action, "tenant.plan": plan}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with billing.tracer.start_as_current_span(
            f"billing.{action}_subscription", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST",
                        "http.route": "/api/v2/subscriptions",
                        "operation.id": operation_id, "tenant.id": tenant["id"],
                        "tenant.name": tenant["name"], "tenant.plan": plan,
                        "billing.action": action,
                        "billing.amount_usd": plan_details["price_usd"],
                        "billing.cycle": "monthly",
                        "billing.provider": "stripe",
                        "billing.email": tenant["billing_email"]}
        ) as entry_span:
            time.sleep(random.uniform(0.05, 0.15))
            bil_payments.add(1, attributes={"billing.action": action, "tenant.plan": plan})

            if force_failure:
                error_code = random.choice(BILLING_ERRORS)
                err = Exception(f"StripeSubscriptionError: {error_code}")
                entry_span.record_exception(err)
                entry_span.set_status(StatusCode.ERROR, str(err))
                exit_span.record_exception(RuntimeError("billing_failed"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "billing_failed")
                bil_failures.add(1, attributes={"billing.error_code": error_code})
                billing.logger.error(
                    f"billing {action} failed: {error_code} for {tenant['name']}",
                    extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                           "billing.action": action, "billing.error_code": error_code,
                           "billing.amount_usd": plan_details["price_usd"]}
                )
                raise err

            subscription_id = f"sub_{uuid.uuid4().hex[:20]}"
            entry_span.set_attribute("billing.subscription_id", subscription_id)
            entry_span.set_attribute("billing.status",          "active")
            entry_span.set_attribute("billing.next_invoice",    int(time.time()) + 2592000)

            dur_ms = (time.time() - t0) * 1000
            bil_mrr.record(plan_details["price_usd"],
                           attributes={"billing.action": action, "tenant.plan": plan})
            if action == "upgrade":
                bil_upgrades.add(1, attributes={"tenant.plan": plan})

            billing.logger.info(
                f"billing {action} successful: sub={subscription_id} ${plan_details['price_usd']}/mo",
                extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                       "billing.subscription_id": subscription_id,
                       "billing.amount_usd": plan_details["price_usd"],
                       "billing.action": action, "billing.cycle": "monthly"}
            )
            return subscription_id, inject_traceparent(entry_span)


def svc_resource_allocator(operation_id: str, tenant: dict, plan: str,
                             parent_tp: str, force_quota_exceeded: bool = False) -> tuple:
    """Allocate Kubernetes namespace, CPU, memory, and storage."""
    parent_ctx   = extract_context(parent_tp)
    plan_details = PLANS[plan]
    t0 = time.time()
    namespace    = f"tenant-{tenant['id'].lower()}-{tenant['region']}"

    with provisioner.tracer.start_as_current_span(
        "http.client.resource_allocator", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "resource-allocator",
                    "http.url": "http://resource-allocator/api/v1/allocate",
                    "operation.id": operation_id, "tenant.id": tenant["id"],
                    "tenant.plan": plan, "k8s.namespace": namespace}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with allocator.tracer.start_as_current_span(
            "allocator.provision_namespace", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST",
                        "http.route": "/api/v1/allocate",
                        "operation.id": operation_id, "tenant.id": tenant["id"],
                        "k8s.namespace": namespace, "k8s.cluster": f"k8s-{tenant['region']}",
                        "resource.cpu_cores": plan_details["cpu_cores"],
                        "resource.memory_gb": plan_details["memory_gb"],
                        "resource.storage_gb": plan_details["storage_gb"],
                        "tenant.plan": plan, "tenant.region": tenant["region"]}
        ) as entry_span:
            time.sleep(random.uniform(0.1, 0.4))

            if force_quota_exceeded:
                # Tenant is over quota, trigger auto-scale
                current_usage_pct = random.uniform(0.92, 0.99)
                entry_span.set_attribute("resource.usage_pct",     current_usage_pct)
                entry_span.set_attribute("quota.exceeded",         True)
                entry_span.set_attribute("quota.autoscale_triggered", True)

                res_violations.add(1, attributes={"tenant.plan": plan, "tenant.region": tenant["region"]})
                res_autoscale.add(1, attributes={"tenant.plan": plan})

                # Auto-scale: add 50% more resources
                new_cpu   = int(plan_details["cpu_cores"] * 1.5)
                new_mem   = int(plan_details["memory_gb"] * 1.5)
                entry_span.set_attribute("resource.autoscaled_cpu", new_cpu)
                entry_span.set_attribute("resource.autoscaled_mem", new_mem)

                allocator.logger.warning(
                    f"quota exceeded for {tenant['name']}: {current_usage_pct:.0%} utilized — auto-scaling",
                    extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                           "resource.usage_pct": current_usage_pct, "quota.exceeded": True,
                           "resource.autoscaled_cpu": new_cpu, "resource.autoscaled_mem": new_mem,
                           "k8s.namespace": namespace}
                )
                cpu = new_cpu
                mem = new_mem
            else:
                cpu = plan_details["cpu_cores"]
                mem = plan_details["memory_gb"]

            entry_span.set_attribute("k8s.namespace_created",  True)
            entry_span.set_attribute("resource.cpu_allocated",  cpu)
            entry_span.set_attribute("resource.mem_allocated",  mem)
            entry_span.set_attribute("resource.stor_allocated", plan_details["storage_gb"])

            dur_ms = (time.time() - t0) * 1000
            res_cores.record(cpu,  attributes={"tenant.plan": plan})
            res_memory.record(mem, attributes={"tenant.plan": plan})

            allocator.logger.info(
                f"resources allocated: ns={namespace} cpu={cpu} mem={mem}GB",
                extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                       "k8s.namespace": namespace, "resource.cpu_allocated": cpu,
                       "resource.mem_allocated": mem, "allocator.duration_ms": round(dur_ms, 2)}
            )
            return namespace, cpu, mem, inject_traceparent(entry_span)


def svc_provisioner(operation_id: str, tenant: dict, plan: str, subscription_id: str,
                     parent_tp: str, force_k8s_failure: bool = False,
                     force_quota: bool = False) -> tuple:
    """Orchestrate full tenant infrastructure provisioning."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    with portal.tracer.start_as_current_span(
        "http.client.provisioner", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "provisioner",
                    "http.url": "http://provisioner/api/v1/provision",
                    "operation.id": operation_id, "tenant.id": tenant["id"],
                    "tenant.plan": plan, "billing.subscription_id": subscription_id}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with provisioner.tracer.start_as_current_span(
            "provisioner.create_tenant", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST",
                        "http.route": "/api/v1/provision",
                        "operation.id": operation_id, "tenant.id": tenant["id"],
                        "tenant.name": tenant["name"], "tenant.plan": plan,
                        "tenant.region": tenant["region"],
                        "billing.subscription_id": subscription_id,
                        "provisioner.workflow": "terraform+helm"}
        ) as entry_span:
            provisioner_tp = inject_traceparent(entry_span)

            entry_span.add_event("provisioning.started", {
                "tenant.id": tenant["id"],
                "tenant.plan": plan,
                "tenant.region": tenant["region"],
            })

            provisioner.logger.info(
                f"provisioning started: {tenant['name']} plan={plan} region={tenant['region']}",
                extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                       "tenant.plan": plan, "tenant.region": tenant["region"]}
            )

            # Step 1: resource allocation
            try:
                namespace, cpu, mem, tp_res = svc_resource_allocator(
                    operation_id, tenant, plan, provisioner_tp,
                    force_quota_exceeded=force_quota)
                entry_span.add_event("provisioning.resources.allocated", {
                    "cpu.cores": cpu,
                    "memory.gb": mem,
                    "k8s.namespace": namespace,
                })
            except Exception as e:
                entry_span.record_exception(e)
                entry_span.set_status(StatusCode.ERROR, str(e))
                exit_span.record_exception(RuntimeError("resource_allocation_failed"), attributes={"exception.escaped": True})
                exit_span.set_status(StatusCode.ERROR, "resource_allocation_failed")
                prov_failures.add(1, attributes={"error.type": type(e).__name__})
                raise

            # Step 2: simulate Terraform apply
            if force_k8s_failure:
                with provisioner.tracer.start_as_current_span(
                    "provisioner.terraform_apply", kind=SpanKind.INTERNAL,
                    attributes={"operation.id": operation_id, "terraform.workspace": tenant["region"],
                                "terraform.modules": "k8s-namespace,rbac,network-policy,pvc"}
                ) as tf_span:
                    time.sleep(random.uniform(2.0, 4.0))
                    err = Exception(
                        f"KubernetesAPIError: UNAVAILABLE 503 — "
                        f"kube-apiserver {tenant['region']} not responding (circuit breaker open)"
                    )
                    tf_span.record_exception(err)
                    tf_span.set_status(StatusCode.ERROR, str(err))
                    entry_span.record_exception(err)
                    entry_span.set_status(StatusCode.ERROR, str(err))
                    exit_span.record_exception(ConnectionRefusedError("kube-apiserver not responding (circuit breaker open)"), attributes={"exception.escaped": True})
                    exit_span.set_status(StatusCode.ERROR, "k8s_api_unreachable")

                    # Trigger rollback
                    with provisioner.tracer.start_as_current_span(
                        "provisioner.rollback", kind=SpanKind.INTERNAL,
                        attributes={"operation.id": operation_id, "rollback.reason": str(err),
                                    "rollback.steps": "delete-namespace,revoke-rbac,release-quota"}
                    ) as rb_span:
                        time.sleep(random.uniform(0.5, 1.5))
                        prov_rollbacks.add(1, attributes={"error.type": "KubernetesAPIError"})
                        prov_failures.add(1, attributes={"error.type": "KubernetesAPIError"})
                        rb_span.set_attribute("rollback.completed", True)
                        provisioner.logger.error(
                            f"provisioning FAILED + rolled back: {err}",
                            extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                                   "rollback.completed": True, "error.type": "KubernetesAPIError",
                                   "error.message": str(err)}
                        )
                    raise err

            # Terraform success
            with provisioner.tracer.start_as_current_span(
                "provisioner.terraform_apply", kind=SpanKind.INTERNAL,
                attributes={"operation.id": operation_id, "terraform.workspace": tenant["region"],
                            "terraform.modules": "k8s-namespace,rbac,network-policy,pvc,secrets"}
            ) as tf_span:
                time.sleep(random.uniform(0.5, 2.0))
                tf_span.set_attribute("terraform.resources_created", random.randint(12, 35))
                tf_span.set_attribute("terraform.plan_hash", uuid.uuid4().hex[:16])
                provisioner.logger.info(
                    "terraform apply successful",
                    extra={"operation.id": operation_id, "terraform.workspace": tenant["region"],
                           "terraform.resources_created": 24}
                )

            dur_ms = (time.time() - t0) * 1000
            prov_created.add(1, attributes={"tenant.plan": plan, "tenant.region": tenant["region"]})
            prov_duration.record(dur_ms, attributes={"tenant.plan": plan})

            entry_span.set_attribute("provisioner.status",    "complete")
            entry_span.set_attribute("k8s.namespace",         namespace)
            entry_span.set_attribute("resource.cpu_cores",    cpu)
            entry_span.set_attribute("resource.memory_gb",    mem)

            provisioner.logger.info(
                f"provisioning complete: ns={namespace} in {dur_ms:.0f}ms",
                extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                       "k8s.namespace": namespace, "provisioning.duration_ms": round(dur_ms, 2)}
            )
            return namespace, inject_traceparent(entry_span)


def svc_dns_manager(operation_id: str, tenant: dict, parent_tp: str) -> tuple:
    """Create DNS zone and issue SSL certificate."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()
    ssl_provider = random.choice(SSL_PROVIDERS)

    with portal.tracer.start_as_current_span(
        "http.client.dns_manager", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "dns-manager",
                    "http.url": "http://dns-manager/api/v1/zones",
                    "operation.id": operation_id, "dns.domain": tenant["domain"]}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with dns.tracer.start_as_current_span(
            "dns.provision_zone", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/zones",
                        "operation.id": operation_id, "tenant.id": tenant["id"],
                        "dns.domain": tenant["domain"],
                        "dns.zone_type": "A+CNAME+TXT",
                        "ssl.provider": ssl_provider,
                        "dns.ttl_seconds": 300,
                        "dns.backend": "route53"}
        ) as entry_span:
            # DNS propagation + cert issuance
            time.sleep(random.uniform(0.3, 1.2))

            with dns.tracer.start_as_current_span(
                "ssl.issue_certificate", kind=SpanKind.CLIENT,
                attributes={"ssl.provider": ssl_provider, "ssl.domain": tenant["domain"],
                            "ssl.type": "DV", "ssl.validity_days": 90}
            ) as ssl_span:
                time.sleep(random.uniform(0.1, 0.5))  # ACME challenge
                cert_id = f"cert_{uuid.uuid4().hex[:16]}"
                ssl_span.set_attribute("ssl.cert_id",     cert_id)
                ssl_span.set_attribute("ssl.issued",      True)
                ssl_span.set_attribute("ssl.expires_at",  int(time.time()) + 7776000)
                ssl_certs.add(1, attributes={"ssl.provider": ssl_provider})

            dur_ms = (time.time() - t0) * 1000
            entry_span.set_attribute("dns.zone_created",  True)
            entry_span.set_attribute("ssl.cert_id",       cert_id)
            entry_span.set_attribute("dns.domain",        tenant["domain"])
            entry_span.add_event("provisioning.dns.registered", {
                "dns.domain": tenant["domain"],
                "ssl.cert_id": cert_id,
                "ssl.provider": ssl_provider,
            })

            dns_zones.add(1, attributes={"dns.backend": "route53"})
            dns_latency.record(dur_ms, attributes={"ssl.provider": ssl_provider})

            dns.logger.info(
                f"DNS zone + SSL cert provisioned: {tenant['domain']}",
                extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                       "dns.domain": tenant["domain"], "ssl.cert_id": cert_id,
                       "ssl.provider": ssl_provider, "dns.duration_ms": round(dur_ms, 2)}
            )
            return cert_id, inject_traceparent(entry_span)


def svc_notification_hub(operation_id: str, tenant: dict, event_type: str,
                           plan: str, parent_tp: str, extra_ctx: dict = None) -> None:
    """Send multi-channel notifications (email, Slack, webhook)."""
    parent_ctx = extract_context(parent_tp)
    t0 = time.time()

    channels = ["email"]
    if plan in ["enterprise", "enterprise-plus"]:
        channels += ["slack", "webhook"]

    with portal.tracer.start_as_current_span(
        "http.client.notification_hub", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "notification-hub",
                    "http.url": "http://notification-hub/api/v1/notify",
                    "operation.id": operation_id, "notification.event": event_type,
                    "notification.channels": ",".join(channels)}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with notifhub.tracer.start_as_current_span(
            "notification.dispatch", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/notify",
                        "operation.id": operation_id, "tenant.id": tenant["id"],
                        "notification.event": event_type,
                        "notification.channels": ",".join(channels),
                        "notification.template": f"{event_type}_v2",
                        "notification.recipient": tenant["billing_email"],
                        **(extra_ctx or {})}
        ) as entry_span:
            for channel in channels:
                with notifhub.tracer.start_as_current_span(
                    f"notification.send_{channel}", kind=SpanKind.CLIENT,
                    attributes={"notification.channel": channel,
                                "notification.event": event_type}
                ) as chan_span:
                    time.sleep(random.uniform(0.02, 0.08))
                    notif_sent.add(1, attributes={"notification.channel": channel,
                                                   "notification.event": event_type})
                    chan_span.set_attribute("notification.delivered", True)
                    notifhub.logger.info(
                        f"notification sent via {channel}: {event_type}",
                        extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                               "notification.channel": channel, "notification.event": event_type}
                    )

            dur_ms = (time.time() - t0) * 1000
            notif_latency.record(dur_ms, attributes={"notification.event": event_type})
            entry_span.set_attribute("notification.channels_sent", len(channels))
            entry_span.set_attribute("notification.all_delivered", True)


def svc_compliance_auditor(operation_id: str, tenant: dict, action: str,
                             parent_tp: str) -> tuple:
    """Run compliance checks and write audit trail."""
    parent_ctx   = extract_context(parent_tp)
    t0 = time.time()
    frameworks   = tenant.get("compliance", [])

    with portal.tracer.start_as_current_span(
        "http.client.compliance_auditor", kind=SpanKind.CLIENT,
        context=parent_ctx,
        attributes={"http.method": "POST", "net.peer.name": "compliance-auditor",
                    "http.url": "http://compliance-auditor/api/v1/audit",
                    "operation.id": operation_id, "audit.action": action,
                    "compliance.frameworks": ",".join(frameworks) if frameworks else "none"}
    ) as exit_span:
        tp = inject_traceparent(exit_span)

        with compliance.tracer.start_as_current_span(
            "compliance.run_checks", kind=SpanKind.SERVER,
            context=extract_context(tp),
            attributes={"http.method": "POST", "http.route": "/api/v1/audit",
                        "operation.id": operation_id, "tenant.id": tenant["id"],
                        "tenant.name": tenant["name"], "audit.action": action,
                        "compliance.frameworks": ",".join(frameworks) if frameworks else "none",
                        "gdpr.subject": tenant.get("gdpr_subject", False),
                        "compliance.check_count": len(frameworks) * 5 if frameworks else 0}
        ) as entry_span:
            time.sleep(random.uniform(0.05, 0.2))

            checks_passed  = len(frameworks) * 5
            checks_failed  = 0

            # GDPR: data export
            if action == "deactivate" and tenant.get("gdpr_subject"):
                with compliance.tracer.start_as_current_span(
                    "compliance.gdpr_data_export", kind=SpanKind.INTERNAL,
                    attributes={"gdpr.data_export_requested": True,
                                "gdpr.export_format": "json+csv",
                                "gdpr.subject_id": tenant["id"]}
                ) as gdpr_span:
                    time.sleep(random.uniform(0.3, 1.0))
                    export_id = f"GDPR-{uuid.uuid4().hex[:12].upper()}"
                    gdpr_span.set_attribute("gdpr.export_id",       export_id)
                    gdpr_span.set_attribute("gdpr.export_completed", True)
                    gdpr_exports.add(1, attributes={"tenant.region": tenant["region"]})
                    compliance.logger.info(
                        f"GDPR data export completed: {export_id}",
                        extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                               "gdpr.export_id": export_id, "gdpr.data_export_requested": True}
                    )
                entry_span.set_attribute("gdpr.export_completed", True)

            dur_ms = (time.time() - t0) * 1000
            entry_span.set_attribute("compliance.checks_passed",  checks_passed)
            entry_span.set_attribute("compliance.checks_failed",  checks_failed)
            entry_span.set_attribute("compliance.audit_trail_id", f"AUD-{uuid.uuid4().hex[:12].upper()}")

            comp_checks.add(checks_passed, attributes={"audit.action": action})
            if checks_failed: comp_violations.add(checks_failed)

            compliance.logger.info(
                f"compliance audit complete: {action} — {checks_passed} checks passed",
                extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                       "audit.action": action, "compliance.checks_passed": checks_passed,
                       "compliance.frameworks": ",".join(frameworks) if frameworks else "none"}
            )
            return checks_passed, inject_traceparent(entry_span)


# ── Main scenario runner ───────────────────────────────────────────────────────

def run_saas_scenario(scenario: str, tenant: dict):
    """Execute a SaaS tenant operation scenario."""
    operation_id = f"OPS-{uuid.uuid4().hex[:12].upper()}"
    t_start      = time.time()

    force_billing_fail  = scenario == "payment_failure"
    force_quota         = scenario == "quota_exceeded"
    force_k8s_fail      = scenario == "provisioning_failure"
    is_upgrade          = scenario == "plan_upgrade"
    is_deactivation     = scenario == "tenant_deactivation"
    is_new_tenant       = scenario == "new_tenant"

    plan = tenant["plan"]
    if is_upgrade:
        # Upgrade to next tier
        tier_order = ["starter", "pro", "enterprise", "enterprise-plus"]
        idx = tier_order.index(plan)
        if idx < len(tier_order) - 1:
            new_plan = tier_order[idx + 1]
        else:
            new_plan = plan  # already max tier
        plan = new_plan

    print(f"\n  [{scenario}] tenant={tenant['name']} plan={plan} region={tenant['region']}")

    with portal.tracer.start_as_current_span(
        "portal.tenant_operation", kind=SpanKind.SERVER,
        attributes={"http.method": "POST", "http.route": f"/api/v1/tenants/{scenario}",
                    "operation.id": operation_id, "tenant.id": tenant["id"],
                    "tenant.name": tenant["name"], "tenant.plan": plan,
                    "tenant.region": tenant["region"], "operation.type": scenario,
                    "billing.cycle": "monthly",
                    "compliance.frameworks": ",".join(tenant.get("compliance", [])),
                    "gdpr.subject": tenant.get("gdpr_subject", False),
                    "scenario": scenario}
    ) as root_span:
        tp_root = inject_traceparent(root_span)
        tp_requests.add(1, attributes={"operation.type": scenario, "tenant.plan": plan})

        portal.logger.info(
            f"tenant operation: {scenario} for {tenant['name']}",
            extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                   "operation.type": scenario, "tenant.plan": plan}
        )

        try:
            if is_deactivation:
                # Special flow: compliance → billing cancel → notify
                compliance_ok, tp = svc_compliance_auditor(
                    operation_id, tenant, "deactivate", tp_root)
                sub_id, tp = svc_billing(
                    operation_id, tenant, tenant["plan"], "cancel", tp_root,
                    force_failure=False)
                svc_notification_hub(
                    operation_id, tenant, "tenant_deactivated", tenant["plan"], tp_root,
                    extra_ctx={"gdpr.data_export": str(tenant.get("gdpr_subject", False))})

                root_span.set_attribute("operation.status",   "deactivated")
                dur_ms = (time.time() - t_start) * 1000
                tp_latency.record(dur_ms, attributes={"operation.type": scenario})
                portal.logger.info(
                    f"tenant deactivated: {tenant['name']}",
                    extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                           "operation.duration_ms": dur_ms}
                )
                print(f"    ✅ Tenant deactivated: {tenant['name']} "
                      f"({'+ GDPR export' if tenant.get('gdpr_subject') else 'no GDPR'})")
                return True

            # Step 1: billing
            billing_action = "upgrade" if is_upgrade else "create"
            sub_id, tp = svc_billing(
                operation_id, tenant, plan, billing_action, tp_root,
                force_failure=force_billing_fail)

            # Step 2: provision infrastructure (not needed for quota scenario alone)
            if not is_upgrade or force_quota:
                namespace, tp = svc_provisioner(
                    operation_id, tenant, plan, sub_id, tp_root,
                    force_k8s_failure=force_k8s_fail,
                    force_quota=force_quota)
            else:
                # Upgrade: just re-allocate resources
                namespace, _, _, tp = svc_resource_allocator(
                    operation_id, tenant, plan, tp_root, force_quota_exceeded=force_quota)

            # Step 3: DNS + SSL (new tenants only)
            if is_new_tenant:
                cert_id, tp = svc_dns_manager(operation_id, tenant, tp_root)
                root_span.set_attribute("dns.domain",  tenant["domain"])
                root_span.set_attribute("ssl.cert_id", cert_id)

            # Step 4: compliance audit
            checks_ok, tp = svc_compliance_auditor(
                operation_id, tenant,
                "provision" if is_new_tenant else "upgrade" if is_upgrade else "quota_adjustment",
                tp_root)

            # Step 5: notifications
            event = ("tenant_provisioned" if is_new_tenant
                     else "plan_upgraded" if is_upgrade
                     else "quota_scaled")
            svc_notification_hub(
                operation_id, tenant, event, plan, tp_root,
                extra_ctx={"billing.subscription_id": sub_id,
                           "compliance.checks_passed": str(checks_ok)})

            dur_ms = (time.time() - t_start) * 1000
            root_span.set_attribute("operation.status",    "success")
            root_span.set_attribute("tenant.plan",         plan)
            root_span.set_attribute("billing.subscription_id", sub_id)
            root_span.set_attribute("compliance.checks_passed", checks_ok)

            tp_latency.record(dur_ms, attributes={"operation.type": scenario})
            portal.logger.info(
                f"operation complete: {scenario} for {tenant['name']} in {dur_ms:.0f}ms",
                extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                       "operation.type": scenario, "tenant.plan": plan,
                       "operation.duration_ms": round(dur_ms, 2),
                       "billing.subscription_id": sub_id}
            )

            icon = "⚠️" if force_quota else "✅"
            suffix = " (auto-scaled)" if force_quota else ""
            print(f"    {icon} {scenario.replace('_', ' ').title()}{suffix}: "
                  f"{tenant['name']} plan={plan} ({dur_ms:.0f}ms)")
            return True

        except Exception as e:
            root_span.record_exception(e)
            root_span.set_status(StatusCode.ERROR, str(e))
            dur_ms = (time.time() - t_start) * 1000
            err_type = type(e).__name__
            tp_errors.add(1, attributes={"error.type": err_type, "operation.type": scenario})
            tp_latency.record(dur_ms, attributes={"operation.type": scenario,
                                                   "result": "error"})
            portal.logger.error(
                f"operation failed: {scenario} for {tenant['name']}: {e}",
                extra={"operation.id": operation_id, "tenant.id": tenant["id"],
                       "operation.type": scenario, "error.type": err_type,
                       "error.message": str(e), "operation.duration_ms": round(dur_ms, 2)}
            )

            if "Stripe" in str(e) or "billing" in str(e).lower():
                print(f"    ❌ Billing failure: {e}")
            elif "Kubernetes" in str(e) or "kube" in str(e).lower():
                print(f"    ❌ K8s provisioning failure + rollback triggered")
            else:
                print(f"    ❌ Operation failed: {e}")
            return False


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'='*70}")
    print("  B2B SaaS Tenant Provisioning Platform — Distributed Tracing Demo")
    print("  Services: tenant-portal → billing-service → provisioner")
    print("            → resource-allocator → dns-manager")
    print("            → notification-hub → compliance-auditor")
    print(f"{'='*70}")

    # 25 scenarios
    scenario_pool = (
        ["new_tenant"] * 10 +
        ["plan_upgrade"] * 5 +
        ["payment_failure"] * 4 +
        ["quota_exceeded"] * 2 +
        ["tenant_deactivation"] * 3 +
        ["provisioning_failure"] * 1
    )
    random.shuffle(scenario_pool)

    stats = {"new_tenant": 0, "plan_upgrade": 0, "payment_failure": 0,
             "quota_exceeded": 0, "tenant_deactivation": 0,
             "provisioning_failure": 0, "total": 0}

    for i, scenario in enumerate(scenario_pool):
        tenant = random.choice(TENANTS)

        print(f"\n{'─'*70}")
        print(f"  Scenario {i+1:02d}/25  [{scenario}]")
        result = run_saas_scenario(scenario, tenant)
        stats["total"] += 1
        stats[scenario] = stats.get(scenario, 0) + 1

        time.sleep(random.uniform(0.1, 0.4))

    print(f"\n{'='*70}")
    print("  Flushing all telemetry providers...")
    for svc in [portal, billing, provisioner, allocator, dns, notifhub, compliance]:
        svc.flush()

    print(f"\n  Results: {stats['total']} scenarios")
    print(f"    ✅ New provisioning:    {stats['new_tenant']}")
    print(f"    ⬆️  Plan upgrades:       {stats['plan_upgrade']}")
    print(f"    ❌ Payment failures:    {stats['payment_failure']}")
    print(f"    ⚠️  Quota exceeded:      {stats['quota_exceeded']}")
    print(f"    🗑️  Deactivations:       {stats['tenant_deactivation']}")
    print(f"    💥 Prov. failures:      {stats['provisioning_failure']}")

    print(f"\n  Kibana:")
    print(f"    Service Map → Observability → APM → Service Map")
    print(f"    Filter: tenant-portal (7 connected nodes expected)")
    print(f"\n  ES|QL query:")
    print(f'    FROM traces-apm*,logs-*')
    print(f'    | WHERE service.name IN ("tenant-portal","billing-service","provisioner",')
    print(f'        "resource-allocator","dns-manager","notification-hub","compliance-auditor")')
    print(f'    | SORT @timestamp DESC | LIMIT 100')
    print(f"{'='*70}\n")
