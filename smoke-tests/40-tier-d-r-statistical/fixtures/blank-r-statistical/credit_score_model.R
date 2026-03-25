# ================================================================
# FILE:       credit_score_model.R
# DESCRIPTION: Credit risk scoring pipeline
#              Loads loan applications from PostgreSQL, runs
#              logistic regression model (GLM), applies decision
#              rules (A/B/C/D grade + APPROVE/REVIEW/DECLINE),
#              writes results back to loan_decisions table.
#
# RUNTIME:    R 4.3.x
# PACKAGES:   DBI, RPostgres, dplyr, tidyr
# SCHEDULE:   Triggered per batch via rscript or cron
# ================================================================

suppressPackageStartupMessages({
  library(DBI)
  library(RPostgres)
  library(dplyr)
})

# ---- Configuration -------------------------------------------
DB_HOST <- Sys.getenv("CREDIT_DB_HOST", "pg-credit-prod.internal")
DB_PORT <- as.integer(Sys.getenv("CREDIT_DB_PORT", "5432"))
DB_NAME <- Sys.getenv("CREDIT_DB_NAME", "creditdb")
DB_USER <- Sys.getenv("CREDIT_DB_USER", "scoring_svc")
DB_PASS <- Sys.getenv("CREDIT_DB_PASS", "")

MODEL_PATH <- "models/logistic_v4.2.rds"
BATCH_ID   <- format(Sys.time(), "%Y%m%d%H%M%S")

cat(sprintf("=== Credit Scoring Pipeline ===\n"))
cat(sprintf("Batch:  %s\n", BATCH_ID))
cat(sprintf("Model:  %s\n", MODEL_PATH))
cat(sprintf("DB:     %s:%d/%s\n\n", DB_HOST, DB_PORT, DB_NAME))

# ================================================================
# connect_db — return a DBI connection to PostgreSQL
# ================================================================
connect_db <- function() {
  DBI::dbConnect(
    RPostgres::Postgres(),
    host     = DB_HOST,
    port     = DB_PORT,
    dbname   = DB_NAME,
    user     = DB_USER,
    password = DB_PASS
  )
}

# ================================================================
# load_applications — fetch pending loan applications
# ================================================================
load_applications <- function(con) {
  sql <- "
    SELECT app_id, fico_score, dti_ratio, ltv_ratio,
           annual_income_k, loan_amount, loan_purpose
    FROM   loan_applications
    WHERE  scoring_status = 'PENDING'
    ORDER  BY submitted_at
    LIMIT  500
  "
  DBI::dbGetQuery(con, sql)
}

# ================================================================
# score_application — run logistic regression to compute
#                     probability of default and credit grade
# ================================================================
score_application <- function(model, app_row) {
  # Build feature vector matching model formula
  features <- data.frame(
    fico_score      = app_row$fico_score,
    dti_ratio       = app_row$dti_ratio,
    ltv_ratio       = app_row$ltv_ratio,
    annual_income_k = app_row$annual_income_k,
    loan_amount     = app_row$loan_amount,
    loan_purpose    = app_row$loan_purpose
  )

  # Run GLM prediction (probability of default)
  prob_default <- predict(model, newdata = features, type = "response")

  # Map to internal credit score (300-850)
  credit_score <- as.integer(850 - prob_default * 400)
  credit_score <- max(300L, min(850L, credit_score))

  list(
    credit_score = credit_score,
    prob_default = round(prob_default, 4)
  )
}

# ================================================================
# apply_decision_rules — convert score to grade + decision
# ================================================================
apply_decision_rules <- function(credit_score, loan_amount, loan_purpose) {
  grade <- dplyr::case_when(
    credit_score >= 750 ~ "A",
    credit_score >= 700 ~ "B",
    credit_score >= 650 ~ "C",
    TRUE                ~ "D"
  )

  decision <- dplyr::case_when(
    grade %in% c("A", "B") ~ "APPROVE",
    grade == "C"            ~ "REVIEW",
    TRUE                    ~ "DECLINE"
  )

  offered_rate <- 3.5 + (850 - credit_score) * 0.02

  list(grade = grade, decision = decision, offered_rate_pct = round(offered_rate, 2))
}

# ================================================================
# write_results — persist decisions to loan_decisions table
# ================================================================
write_results <- function(con, results_df) {
  DBI::dbWriteTable(
    con,
    name      = "loan_decisions",
    value     = results_df,
    append    = TRUE,
    row.names = FALSE
  )
  cat(sprintf("  Wrote %d decisions to loan_decisions\n", nrow(results_df)))
}

# ================================================================
# MAIN
# ================================================================
tryCatch({
  # 1. Connect to database
  con <- connect_db()
  on.exit(DBI::dbDisconnect(con), add = TRUE)

  # 2. Load model from RDS file
  model <- readRDS(MODEL_PATH)
  cat(sprintf("Model loaded: %s\n", MODEL_PATH))

  # 3. Fetch pending applications
  apps <- load_applications(con)
  cat(sprintf("Applications to score: %d\n\n", nrow(apps)))

  if (nrow(apps) == 0) {
    cat("No pending applications — exiting.\n")
    quit(status = 0)
  }

  # 4. Score each application
  results <- vector("list", nrow(apps))
  for (i in seq_len(nrow(apps))) {
    app <- apps[i, ]

    scored   <- score_application(model, app)
    decision <- apply_decision_rules(
      scored$credit_score, app$loan_amount, app$loan_purpose
    )

    results[[i]] <- data.frame(
      app_id          = app$app_id,
      batch_id        = BATCH_ID,
      credit_score    = scored$credit_score,
      prob_default    = scored$prob_default,
      credit_grade    = decision$grade,
      credit_decision = decision$decision,
      offered_rate_pct = decision$offered_rate_pct,
      scored_at       = Sys.time(),
      stringsAsFactors = FALSE
    )

    cat(sprintf("  %s  fico=%d  score=%d  grade=%s  %s  rate=%.2f%%\n",
        app$app_id, app$fico_score, scored$credit_score,
        decision$grade, decision$decision, decision$offered_rate_pct))
  }

  # 5. Write all results
  results_df <- dplyr::bind_rows(results)
  write_results(con, results_df)

  # 6. Summary
  cat(sprintf("\n=== Batch %s Complete ===\n", BATCH_ID))
  cat(sprintf("Scored:   %d\n", nrow(results_df)))
  cat(sprintf("Approved: %d\n", sum(results_df$credit_decision == "APPROVE")))
  cat(sprintf("Review:   %d\n", sum(results_df$credit_decision == "REVIEW")))
  cat(sprintf("Declined: %d\n", sum(results_df$credit_decision == "DECLINE")))

}, error = function(e) {
  cat(sprintf("FATAL ERROR: %s\n", conditionMessage(e)))
  quit(status = 1)
})
