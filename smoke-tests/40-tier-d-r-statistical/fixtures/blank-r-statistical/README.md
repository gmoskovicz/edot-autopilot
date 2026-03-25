# blank-r-statistical — Credit Risk Scoring Pipeline (R)

## What this script does

`credit_score_model.R` is an R script that implements a credit risk scoring
pipeline:

1. **connect_db** — opens a DBI/RPostgres connection to the PostgreSQL credit
   database (`creditdb` on `pg-credit-prod.internal`)
2. **load_applications** — fetches up to 500 pending loan applications from the
   `loan_applications` table
3. **readRDS_load_model** — loads a serialized logistic regression GLM model
   from `models/logistic_v4.2.rds`
4. **predict_glm** — runs `predict(model, type="response")` to compute
   probability of default for each application using FICO score, DTI ratio,
   LTV ratio, income, and loan amount
5. **apply_decision_rules** — maps the credit score (300–850) to a grade
   (A/B/C/D) and decision (APPROVE/REVIEW/DECLINE) using `dplyr::case_when`
6. **dbWriteTable_results** — writes all decisions back to the `loan_decisions`
   PostgreSQL table using `DBI::dbWriteTable`

## Why it has no observability

This is a **Tier D** legacy application. R has no OpenTelemetry SDK; CRAN
provides no OTel packages. The R runtime cannot load native OTel agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`cat()` console output and direct database writes.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `credit_score_model.R` to add `httr::POST` or `curl::curl_fetch_memory`
   calls targeting the sidecar so that each pipeline step emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
