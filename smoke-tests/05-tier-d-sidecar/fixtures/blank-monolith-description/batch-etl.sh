#!/bin/bash
# Batch ETL Pipeline — Bash
# No observability. Run `Observe this project.` to add sidecar OTel.
#
# Reads from Oracle DB, transforms, writes to S3.

set -euo pipefail

BATCH_ID="BATCH-$(date +%Y%m%d-%H%M%S)"
echo "Starting ETL batch: $BATCH_ID"

# Extract phase (simulated)
ROWS_EXTRACTED=49832
echo "Extracted $ROWS_EXTRACTED rows from Oracle"

# Transform phase
ROWS_TRANSFORMED=$ROWS_EXTRACTED
echo "Transformed $ROWS_TRANSFORMED rows"

# Load phase (simulated S3 upload)
echo "Loaded $ROWS_TRANSFORMED rows to s3://data-lake/etl/$(date +%Y/%m/%d)/"

echo "ETL complete: $BATCH_ID rows=$ROWS_TRANSFORMED"
