#!/usr/bin/env python3
"""
Smoke test: Tier D — R statistical computing (sidecar simulation).

Simulates an R script submitting observability via the HTTP sidecar bridge.
Business scenario: credit risk model scoring — load loan applications, run
logistic regression scoring model, apply decision rules, output risk grades.

Run:
    cd smoke-tests && python3 40-tier-d-r-statistical/smoke.py
"""

import os, sys, time, random, math
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind

SVC = "smoke-tier-d-r-statistical"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

applications_scored = meter.create_counter("r.applications_scored")
model_score         = meter.create_histogram("r.credit_score")
scoring_duration_ms = meter.create_histogram("r.scoring_duration_ms", unit="ms")
approval_counter    = meter.create_counter("r.credit_decisions")

LOAN_APPLICATIONS = [
    {"app_id": "APP-20001", "fico": 742, "dti": 0.28, "ltv": 0.80, "income_k": 95,  "loan_amt": 280000, "purpose": "mortgage"},
    {"app_id": "APP-20002", "fico": 598, "dti": 0.45, "ltv": 0.95, "income_k": 48,  "loan_amt": 25000,  "purpose": "personal"},
    {"app_id": "APP-20003", "fico": 810, "dti": 0.18, "ltv": 0.65, "income_k": 210, "loan_amt": 500000, "purpose": "mortgage"},
    {"app_id": "APP-20004", "fico": 655, "dti": 0.38, "ltv": 0.85, "income_k": 72,  "loan_amt": 35000,  "purpose": "auto"},
    {"app_id": "APP-20005", "fico": 720, "dti": 0.31, "ltv": 0.75, "income_k": 88,  "loan_amt": 180000, "purpose": "refi"},
]

def score_application(app):
    t0 = time.time()
    # Simulate logistic regression score
    log_odds = (app["fico"] - 700) * 0.012 - app["dti"] * 2.5 - (app["ltv"] - 0.75) * 1.8
    prob_default = 1 / (1 + math.exp(log_odds))
    credit_score = int(850 - prob_default * 400)
    grade = "A" if credit_score >= 750 else "B" if credit_score >= 700 else "C" if credit_score >= 650 else "D"
    decision = "APPROVE" if grade in ("A", "B") else "REVIEW" if grade == "C" else "DECLINE"
    rate_pct = 3.5 + (850 - credit_score) * 0.02

    with tracer.start_as_current_span("R.credit_scoring_pipeline", kind=SpanKind.INTERNAL,
            attributes={"r.script": "credit_score_model.R", "r.function": "score_application",
                        "loan.app_id": app["app_id"], "loan.purpose": app["purpose"],
                        "loan.amount": app["loan_amt"], "applicant.fico": app["fico"]}) as span:

        with tracer.start_as_current_span("R.readRDS_load_model", kind=SpanKind.INTERNAL,
                attributes={"r.function": "readRDS", "r.model_file": "models/logistic_v4.2.rds"}):
            time.sleep(random.uniform(0.02, 0.06))

        with tracer.start_as_current_span("R.predict_glm", kind=SpanKind.INTERNAL,
                attributes={"r.function": "predict.glm", "r.family": "binomial",
                            "r.predictors": 8}):
            time.sleep(random.uniform(0.01, 0.04))

        with tracer.start_as_current_span("R.apply_decision_rules", kind=SpanKind.INTERNAL,
                attributes={"r.function": "apply_decision_rules", "credit.grade": grade}):
            time.sleep(0.005)

        with tracer.start_as_current_span("R.dbWriteTable_results", kind=SpanKind.CLIENT,
                attributes={"db.system": "postgresql", "db.operation": "INSERT",
                            "db.table": "loan_decisions", "loan.app_id": app["app_id"]}):
            time.sleep(random.uniform(0.02, 0.05))

        dur = (time.time() - t0) * 1000
        span.set_attribute("credit.score",            credit_score)
        span.set_attribute("credit.grade",             grade)
        span.set_attribute("credit.decision",          decision)
        span.set_attribute("credit.prob_default",      round(prob_default, 4))
        span.set_attribute("credit.offered_rate_pct",  round(rate_pct, 2))
        span.set_attribute("r.scoring_ms",             round(dur, 2))

        applications_scored.add(1, attributes={"loan.purpose": app["purpose"]})
        model_score.record(credit_score, attributes={"loan.purpose": app["purpose"]})
        scoring_duration_ms.record(dur, attributes={"r.function": "score_application"})
        approval_counter.add(1, attributes={"credit.decision": decision, "credit.grade": grade})

        logger.info("credit application scored",
                    extra={"loan.app_id": app["app_id"], "applicant.fico": app["fico"],
                           "credit.score": credit_score, "credit.grade": grade,
                           "credit.decision": decision, "credit.prob_default": round(prob_default, 4),
                           "credit.offered_rate_pct": round(rate_pct, 2)})

    return credit_score, grade, decision, rate_pct

print(f"\n[{SVC}] Simulating R credit scoring model pipeline...")
for app in LOAN_APPLICATIONS:
    score, grade, decision, rate = score_application(app)
    icon = "✅" if decision == "APPROVE" else "⚠️ " if decision == "REVIEW" else "❌"
    print(f"  {icon} {app['app_id']}  fico={app['fico']}  score={score}  grade={grade}  {decision}  rate={rate:.2f}%")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
