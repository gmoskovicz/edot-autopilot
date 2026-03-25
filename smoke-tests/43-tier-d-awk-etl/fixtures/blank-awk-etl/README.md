# blank-awk-etl — Access Log ETL Pipeline (AWK + Shell)

## What this script does

`parse_access_logs.awk` is an AWK program that implements an access log ETL
pipeline for Apache/Nginx web servers:

1. **parse_log** — reads Combined Log Format lines, splits by space, and
   extracts IP address, HTTP method, request path, status code, bytes
   transferred, and response time (milliseconds in field 13)
2. **normalize_path** — strips query strings and normalizes numeric path
   segments to `:id` placeholders (e.g. `/api/v1/products/12345` →
   `/api/v1/products/:id`)
3. **aggregate_by_endpoint** — accumulates request counts, error counts
   (status ≥ 400), total bytes, and total response time per `(path, status)`
   key using AWK associative arrays
4. **write_summary_csv** — in the `END` block, computes average response time
   and approximate p99 from a 100-sample ring buffer, then writes the summary
   CSV to the `reports/` directory

Input: Nginx/Apache Combined Log Format with an appended response time field.
Output: `reports/<server>_summary.csv` with columns `endpoint, http_status,
request_count, error_count, avg_ms, p99_ms, total_bytes`.

## Why it has no observability

This is a **Tier D** legacy pipeline. AWK scripts have no OpenTelemetry SDK.
The AWK runtime cannot load native OTel agents.

There are no HTTP calls, no sidecar references, no trace/span IDs — just
stderr `print` statements for progress.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `parse_access_logs.awk` to add `curl` system calls or wrap it in
   a shell script that POSTs span data to the sidecar for each ETL stage
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
