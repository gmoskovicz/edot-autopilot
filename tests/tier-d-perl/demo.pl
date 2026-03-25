#!/usr/bin/perl
# Tier D — Perl with OTEL Sidecar
#
# Perl has no native OpenTelemetry SDK. But it has LWP::UserAgent (ubiquitous)
# or can fall back to curl via system(). Works on any Perl 5.8+ system.
#
# Usage: perl demo.pl
# Prerequisites: LWP::UserAgent (cpan install LWP::UserAgent)
#                OR curl (fallback)
#                AND otel-sidecar running on localhost:9411

use strict;
use warnings;
use JSON;

my $SIDECAR = $ENV{OTEL_SIDECAR_URL} // 'http://127.0.0.1:9411';

# ── Helper: fire-and-forget event span ───────────────────────────────────────
sub otel_event {
    my ($name, %attrs) = @_;
    my $payload = encode_json({
        action     => 'event',
        name       => $name,
        attributes => \%attrs,
    });
    _post_to_sidecar($payload);
}

# ── Helper: start a long-running span ────────────────────────────────────────
sub otel_start {
    my ($name, %attrs) = @_;
    my $payload = encode_json({
        action     => 'start_span',
        name       => $name,
        attributes => \%attrs,
    });
    my $resp = _post_to_sidecar($payload);
    return $resp ? ($resp->{span_id} // '') : '';
}

# ── Helper: end a span ────────────────────────────────────────────────────────
sub otel_end {
    my ($span_id, %opts) = @_;
    return unless $span_id;
    my $payload = encode_json({
        action     => 'end_span',
        span_id    => $span_id,
        attributes => $opts{attributes} // {},
        $opts{error} ? (error => $opts{error}) : (),
    });
    _post_to_sidecar($payload);
}

# ── Internal: POST with LWP or curl fallback ─────────────────────────────────
sub _post_to_sidecar {
    my ($payload) = @_;
    eval {
        require LWP::UserAgent;
        my $ua = LWP::UserAgent->new(timeout => 1);
        my $res = $ua->post(
            $SIDECAR,
            'Content-Type' => 'application/json',
            Content        => $payload,
        );
        if ($res->is_success) {
            return decode_json($res->content);
        }
    };
    if ($@) {
        # LWP not available — try curl
        system(qq{curl -sf -X POST $SIDECAR }
             . qq{-H "Content-Type: application/json" }
             . qq{-d '$payload' >/dev/null 2>&1});
    }
    return undef;
}

# ─────────────────────────────────────────────────────────────────────────────
# Simulated invoice processing — a typical Perl CGI / legacy web app scenario
# ─────────────────────────────────────────────────────────────────────────────

print "Invoice processing batch (Perl Tier D demo)\n";

my @invoices = (
    { id => 'INV-001', amount => 4200.00, customer => 'CUST-ENT-001', tier => 'enterprise' },
    { id => 'INV-002', amount => 29.99,   customer => 'CUST-001',     tier => 'free' },
    { id => 'INV-003', amount => 1250.00, customer => 'CUST-PRO-007', tier => 'pro' },
);

my $batch_span = otel_start('invoice.batch',
    source       => 'legacy-perl-billing',
    invoice_count => scalar @invoices,
);

for my $inv (@invoices) {
    my $span = otel_start('invoice.process',
        'invoice.id'       => $inv->{id},
        'invoice.amount'   => $inv->{amount},
        'customer.id'      => $inv->{customer},
        'customer.tier'    => $inv->{tier},
    );

    # Simulate processing delay
    select(undef, undef, undef, 0.1);

    # Simulate occasional send failure
    my $sent = rand() > 0.1;
    otel_end($span,
        attributes => {
            'invoice.sent'   => $sent ? 'true' : 'false',
            'invoice.status' => $sent ? 'delivered' : 'failed',
        },
        $sent ? () : (error => 'SMTP timeout'),
    );

    printf "  %s \$%.2f [%s] %s\n",
        $inv->{id}, $inv->{amount}, $inv->{tier}, $sent ? 'SENT' : 'FAILED';
}

otel_end($batch_span, attributes => {
    'batch.invoices_processed' => scalar @invoices,
    'batch.status'             => 'complete',
});

print "Done. Check Kibana APM → perl-tier-d\n";
