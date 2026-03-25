# Tier D — Perl

Perl has no OpenTelemetry SDK. But it has `LWP::UserAgent` — available on virtually every Perl 5.8+ installation since 2002. If LWP isn't present, the code falls back to `curl`.

## The pattern

```perl
use LWP::UserAgent; use JSON;

sub otel_event {
    my ($name, %a) = @_;
    LWP::UserAgent->new(timeout=>1)->post($SIDECAR,
        'Content-Type' => 'application/json',
        Content => encode_json({action=>'event', name=>$name, attributes=>\%a}));
}

otel_event('invoice.sent',
    invoice_id => $id,
    amount     => $total,
    customer   => $cid,
    tier       => $tier,
);
```

## Run

```bash
# Install dependencies
cpan install LWP::UserAgent JSON

# Start sidecar
cd ../../otel-sidecar
OTEL_SERVICE_NAME=perl-tier-d docker compose up -d

# Run demo
cd ../tests/tier-d-perl
perl demo.pl
```

## Platforms

Works on: any Linux/Unix with Perl 5.8+, AIX, HP-UX, legacy CGI servers, mod_perl applications.
