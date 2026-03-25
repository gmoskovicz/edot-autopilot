# OpenTelemetry for Perl — Complete Guide

> How to get distributed traces out of Perl applications — CGI scripts, mod_perl apps, bioinformatics pipelines, and finance systems — and into Elastic APM.

## The problem

Perl has no official OpenTelemetry SDK. There is a CPAN module called `OpenTelemetry` that was started in 2023, but it is incomplete, lacks exporter support for OTLP/HTTP in production use, and has essentially no adoption. The major APM vendors either do not list Perl in their supported languages at all, or offer an agent so limited it covers only basic HTTP timing.

This matters more than most people admit. Perl is not a dead language. It runs:

- **Finance**: trade reconciliation scripts, risk calculation batch jobs, SWIFT message parsers
- **Bioinformatics**: genome pipeline orchestration, BLAST wrappers, lab instrument integrations
- **Web**: legacy CGI and mod_perl applications on Apache that process real customer traffic
- **Operations**: system administration scripts, log parsers, monitoring daemons
- **Publishing**: content management backends (Movable Type and its descendants still have users)

These workloads are often the ones that matter most to the business and are least observed. A genome pipeline that silently fails halfway through costs days of researcher time. A trade reconciliation script that slows from 30 minutes to 4 hours may trigger a compliance breach.

No OTel SDK means all of this is invisible in APM tools.

## The solution: Telemetry Sidecar

The EDOT Autopilot telemetry sidecar is a Python HTTP server that runs alongside your Perl process. Your Perl code uses `LWP::UserAgent` — a module that ships with virtually every Perl installation and has been available since Perl 5.6 — to POST events to the sidecar. The sidecar translates those events into OTLP spans and forwards them to Elastic.

Architecture:

```
[Perl Process]
    |
    | LWP::UserAgent POST http://127.0.0.1:9411
    |
    v
[otel-sidecar.py :9411]   (Python, same host)
    |
    | OTLP/HTTP
    v
[Elastic Cloud APM]
```

The sidecar fires and forgets. With `timeout=>1`, your Perl script waits at most one second if the sidecar is down — and in practice the call returns in under 10ms.

If `LWP::UserAgent` is not available (stripped-down environment), you can use `curl` via backticks instead — see the alternative below.

## Step-by-step setup

### Step 1: Deploy the sidecar

```bash
git clone https://github.com/gmoskovicz/edot-autopilot
cd edot-autopilot
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

Set environment variables and start:

```bash
export OTEL_SERVICE_NAME=perl-reconciliation-service
export ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
export ELASTIC_API_KEY=<your-base64-encoded-id:key>
export OTEL_DEPLOYMENT_ENVIRONMENT=production

python otel-sidecar/otel-sidecar.py &
```

### Step 2: Verify connectivity from Perl

```perl
#!/usr/bin/perl
use strict;
use warnings;
use LWP::UserAgent;
use JSON;

my $ua = LWP::UserAgent->new(timeout => 1);
my $res = $ua->post(
    'http://127.0.0.1:9411',
    'Content-Type' => 'application/json',
    Content => encode_json({
        action     => 'event',
        name       => 'sidecar.test',
        attributes => { test => 'true' }
    })
);
print $res->is_success ? "Sidecar OK\n" : "Sidecar failed: " . $res->status_line . "\n";
```

### Step 3: Add the helper function to your Perl code

Copy the `otel_event` helper into your script or a shared module, then call it at each business event.

### Step 4: For long-running processes, use start_span / end_span

If your Perl process performs a multi-step operation (e.g., a reconciliation job with distinct phases), use the `start_span` and `end_span` actions to capture duration per phase.

## Code example

### Basic event emission

```perl
use LWP::UserAgent;
use JSON;

# Helper — paste this into your script or a shared Telemetry.pm module
sub otel_event {
    my ($name, %attrs) = @_;
    eval {
        LWP::UserAgent->new(timeout => 1)->post(
            'http://127.0.0.1:9411',
            'Content-Type' => 'application/json',
            Content => encode_json({
                action     => 'event',
                name       => $name,
                attributes => \%attrs,
            })
        );
    };
    # Never propagate telemetry errors into application logic
}

# Usage — invoice processing
sub process_invoice {
    my ($invoice_id, $customer_id, $amount) = @_;

    # ... invoice processing logic ...

    otel_event(
        'invoice.sent',
        invoice_id  => $invoice_id,
        customer_id => $customer_id,
        amount      => $amount,
        currency    => 'USD',
    );
}
```

### Multi-step spans with duration measurement

```perl
sub otel_start_span {
    my ($name, %attrs) = @_;
    my $span_id;
    eval {
        my $ua  = LWP::UserAgent->new(timeout => 1);
        my $res = $ua->post(
            'http://127.0.0.1:9411',
            'Content-Type' => 'application/json',
            Content => encode_json({
                action     => 'start_span',
                name       => $name,
                attributes => \%attrs,
            })
        );
        if ($res->is_success) {
            my $body = decode_json($res->content);
            $span_id = $body->{span_id};
        }
    };
    return $span_id;
}

sub otel_end_span {
    my ($span_id, $error, %attrs) = @_;
    eval {
        LWP::UserAgent->new(timeout => 1)->post(
            'http://127.0.0.1:9411',
            'Content-Type' => 'application/json',
            Content => encode_json({
                action     => 'end_span',
                span_id    => $span_id,
                ($error ? (error => $error) : ()),
                attributes => \%attrs,
            })
        );
    };
}

# Usage — trade reconciliation with per-phase spans
sub run_reconciliation {
    my ($trade_date, $account_id) = @_;

    my $span = otel_start_span(
        'reconciliation.run',
        'trade.date'  => $trade_date,
        'account.id'  => $account_id,
    );

    my ($matched, $unmatched) = (0, 0);

    eval {
        ($matched, $unmatched) = perform_reconciliation($trade_date, $account_id);
    };

    if ($@) {
        otel_end_span($span, $@,
            'records.matched'   => $matched,
            'records.unmatched' => $unmatched,
        );
        die $@;
    }

    otel_end_span($span, undef,
        'records.matched'   => $matched,
        'records.unmatched' => $unmatched,
        'reconciliation.status' => $unmatched == 0 ? 'clean' : 'exceptions',
    );
}
```

### Bioinformatics pipeline instrumentation

```perl
# Genome pipeline — instrument each stage
sub run_blast_search {
    my ($query_id, $database, $sequence) = @_;

    my $span = otel_start_span(
        'blast.search',
        'query.id'   => $query_id,
        'db.name'    => $database,
        'seq.length' => length($sequence),
    );

    my $result = execute_blast($query_id, $database, $sequence);

    otel_end_span($span, undef,
        'hits.count'   => scalar @{$result->{hits}},
        'best.evalue'  => $result->{hits}[0]{evalue} // 'none',
    );

    return $result;
}
```

### CGI / mod_perl: wrapping the request handler

```perl
# In your CGI script or Apache::Registry handler
use CGI;

my $cgi     = CGI->new;
my $action  = $cgi->param('action') // '';
my $user_id = $cgi->param('user_id') // '';

my $span = otel_start_span(
    "cgi.$action",
    'http.method' => $ENV{REQUEST_METHOD},
    'http.path'   => $ENV{PATH_INFO} // $ENV{SCRIPT_NAME},
    'user.id'     => $user_id,
);

# ... handler logic ...

otel_end_span($span, undef, 'http.status_code' => 200);
```

### Fallback: curl via backticks (if LWP not available)

```perl
sub otel_event_curl {
    my ($name, $attrs_json) = @_;
    $attrs_json //= '{}';
    my $payload = "{\"action\":\"event\",\"name\":\"$name\",\"attributes\":$attrs_json}";
    $payload =~ s/'/'"'"'/g;  # escape single quotes for shell
    system("curl -sf -X POST http://127.0.0.1:9411 "
         . "-H 'Content-Type: application/json' "
         . "-d '$payload' >/dev/null 2>&1 &");
}

otel_event_curl('batch.complete', '{"records":50000,"status":"ok"}');
```

## What you'll see in Elastic

After deploying the sidecar and adding instrumentation calls, you will see:

- **Named services** in Kibana APM matching your `OTEL_SERVICE_NAME`, e.g., `perl-reconciliation-service`.
- **Business-named spans**: `reconciliation.run`, `invoice.sent`, `blast.search` — not just script filenames or HTTP method + path.
- **Duration histograms**: For `start_span` / `end_span` pairs, Elastic records the full span duration, giving you p50/p95/p99 latency per business operation over time.
- **Failure analysis**: When `error` is set in `end_span`, the span appears in the Errors tab with the error message attached.
- **Custom attributes as filterable fields**: Every attribute (`account.id`, `records.matched`, `db.name`) becomes a searchable field in Kibana Discover.

Example ES|QL query to find reconciliation runs with exceptions:

```esql
FROM traces-apm*
| WHERE service.name == "perl-reconciliation-service"
  AND span.name == "reconciliation.run"
  AND attributes.reconciliation\.status == "exceptions"
| STATS
    count       = COUNT(*),
    avg_unmatched = AVG(TO_DOUBLE(attributes.records\.unmatched))
  BY attributes.account\.id
| SORT avg_unmatched DESC
```

## Related

- [Telemetry Sidecar Pattern — full documentation](./telemetry-sidecar-pattern.md)
- [OpenTelemetry for Legacy Runtimes — overview](./opentelemetry-legacy-runtimes.md)
- [OpenTelemetry for Bash scripts](./opentelemetry-bash-shell-scripts.md)
- [Business Span Enrichment](./business-span-enrichment.md)
- [otel-sidecar.py source](../otel-sidecar/otel-sidecar.py)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other Perl developers find this solution.
