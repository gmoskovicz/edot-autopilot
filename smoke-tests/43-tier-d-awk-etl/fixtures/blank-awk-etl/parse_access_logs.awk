#!/usr/bin/awk -f
# ================================================================
# FILE:        parse_access_logs.awk
# DESCRIPTION: Apache/Nginx access log ETL pipeline
#              Parses combined log format, aggregates by endpoint
#              and HTTP status, computes p50/p99 latency buckets,
#              writes summary CSV for reporting.
#
# USAGE:
#   awk -f parse_access_logs.awk \
#       -v OUTPUT_CSV=reports/web-01_summary.csv \
#       /var/log/nginx/access_2026-02-28.log
#
# INPUT FORMAT (Combined Log Format + response time):
#   CLIENT IP - USER [TIMESTAMP] "METHOD PATH PROTO" STATUS BYTES REFERER UA RESP_MS
#
# OUTPUT CSV COLUMNS:
#   endpoint, http_status, request_count, error_count,
#   avg_ms, p50_ms, p99_ms, total_bytes
# ================================================================

BEGIN {
    FS    = " "
    OFS   = ","
    LINES = 0
    ERRORS = 0

    if (OUTPUT_CSV == "") {
        OUTPUT_CSV = "reports/access_summary.csv"
    }

    print "=== AWK Access Log ETL Pipeline ===" > "/dev/stderr"
    print "Output: " OUTPUT_CSV > "/dev/stderr"

    # Print CSV header
    print "endpoint,http_status,request_count,error_count," \
          "avg_ms,p99_ms,total_bytes" > OUTPUT_CSV
}

# ================================================================
# Parse each log line
# ================================================================
{
    LINES++

    # Field layout for combined log:
    # 1=ip  3=user  4=timestamp(date  5=timestamp(time])
    # 6="METHOD  7=PATH  8=PROTO"  9=status  10=bytes
    # 11=referer  12=useragent  13=resp_ms

    # Skip malformed lines
    if (NF < 10) {
        ERRORS++
        next
    }

    # Extract fields
    ip      = $1
    status  = $9
    bytes   = ($10 == "-") ? 0 : $10 + 0
    resp_ms = (NF >= 13) ? $NF + 0 : 0

    # Extract path (strip query string)
    request_field = $7
    split(request_field, path_parts, "?")
    path = path_parts[1]

    # Normalize long paths (e.g. /api/v1/products/12345 -> /api/v1/products/:id)
    if (match(path, /^\/api\/v[0-9]+\/[a-z_]+\/[0-9]+/)) {
        n = split(path, seg, "/")
        path = "/" seg[2] "/" seg[3] "/" seg[4] "/:id"
    }

    # Build aggregation key: path + status
    key = path SUBSEP status

    # Accumulate counters
    count[key]++
    total_bytes[key] += bytes
    total_ms[key]    += resp_ms

    if (status >= 400) {
        err_count[key]++
    }

    # Rough p99 tracking: store last 100 response times per bucket
    bucket_idx[key] = (bucket_idx[key] + 1) % 100
    bucket[key, bucket_idx[key]] = resp_ms
}

# ================================================================
# Aggregation and output
# ================================================================
END {
    print "Lines read:   " LINES > "/dev/stderr"
    print "Parse errors: " ERRORS > "/dev/stderr"

    rows_written = 0

    for (key in count) {
        split(key, parts, SUBSEP)
        endpoint = parts[1]
        status   = parts[2]

        n     = count[key]
        errs  = (key in err_count) ? err_count[key] : 0
        avg   = (n > 0) ? int(total_ms[key] / n) : 0

        # Compute approximate p99 from the ring buffer
        max_sample = 0
        for (i = 0; i < 100; i++) {
            v = bucket[key, i]
            if (v > max_sample) max_sample = v
        }
        p99 = max_sample  # approximation (ring buffer max)

        tb = total_bytes[key]

        print endpoint, status, n, errs, avg, p99, tb >> OUTPUT_CSV
        rows_written++
    }

    print "Endpoints found: " rows_written > "/dev/stderr"
    print "Output written:  " OUTPUT_CSV > "/dev/stderr"
    print "=== ETL Complete ===" > "/dev/stderr"
}
