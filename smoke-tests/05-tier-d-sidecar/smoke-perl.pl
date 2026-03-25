#!/usr/bin/perl
# Smoke test: Tier D — Perl → OTEL Sidecar (traces + logs + metrics)
# Sends invoice processing spans, structured logs, and metrics via LWP.
# Run: OTEL_SIDECAR_URL=http://127.0.0.1:9411 perl smoke-perl.pl

use strict;
use warnings;
use JSON;
use LWP::UserAgent;
use Time::HiRes qw(gettimeofday tv_interval);

my $SIDECAR = $ENV{OTEL_SIDECAR_URL} // 'http://127.0.0.1:9411';
my $SVC     = 'smoke-tier-d-perl';
my $ua      = LWP::UserAgent->new(timeout => 2);

sub post_sidecar {
    my ($payload) = @_;
    my $resp = $ua->post($SIDECAR,
        'Content-Type' => 'application/json',
        Content         => encode_json($payload));
    return $resp->is_success ? decode_json($resp->content) : {};
}

sub otel_event {
    my ($name, %attrs) = @_;
    post_sidecar({ action => 'event', name => $name, attributes => \%attrs });
}

sub otel_start {
    my ($name, $traceparent, %attrs) = @_;
    my $payload = { action => 'start_span', name => $name, attributes => \%attrs };
    $payload->{traceparent} = $traceparent if $traceparent;
    my $r = post_sidecar($payload);
    return ($r->{span_id} // '', $r->{traceparent} // '');
}

sub otel_end {
    my ($span_id, %opts) = @_;
    return unless $span_id;
    post_sidecar({
        action     => 'end_span',
        span_id    => $span_id,
        attributes => $opts{attributes} // {},
        $opts{error} ? (error => $opts{error}) : (),
    });
}

sub otel_log {
    my ($severity, $message, $traceparent, %attrs) = @_;
    my $payload = {
        action     => 'log',
        severity   => $severity,
        body       => $message,
        attributes => \%attrs,
    };
    $payload->{traceparent} = $traceparent if $traceparent;
    post_sidecar($payload);
}

sub otel_counter {
    my ($name, $value, %attrs) = @_;
    post_sidecar({ action => 'metric_counter', name => $name,
                   value => $value, attributes => \%attrs });
}

sub otel_histogram {
    my ($name, $value, %attrs) = @_;
    post_sidecar({ action => 'metric_histogram', name => $name,
                   value => $value, attributes => \%attrs });
}

print "[$SVC] Sending Perl invoice spans + logs + metrics via sidecar at $SIDECAR...\n";

my @invoices = (
    { id => 'INV-PERL-001', amount => 4200.00, customer => 'CUST-ENT-001', tier => 'enterprise' },
    { id => 'INV-PERL-002', amount => 29.99,   customer => 'CUST-FREE-042', tier => 'free' },
    { id => 'INV-PERL-003', amount => 1250.00, customer => 'CUST-PRO-007',  tier => 'pro' },
    { id => 'INV-PERL-004', amount => 750.00,  customer => 'CUST-PRO-015',  tier => 'pro' },
);

my $t0 = [gettimeofday];
my ($batch_id, $batch_tp) = otel_start('invoice.batch', '',
    'batch.count'  => scalar @invoices,
    'batch.source' => 'legacy-perl-billing',
    'billing.cycle' => 'monthly');

otel_log('INFO', 'Invoice batch started', $batch_tp,
    'batch.count' => scalar @invoices,
    'batch.source' => 'legacy-perl-billing');
otel_counter('invoice.batch.started', 1, 'billing.cycle' => 'monthly');

my ($delivered, $failed) = (0, 0);

for my $inv (@invoices) {
    my $t_inv = [gettimeofday];
    my ($span_id, $inv_tp) = otel_start('invoice.process', $batch_tp,
        'invoice.id'      => $inv->{id},
        'invoice.amount'  => $inv->{amount},
        'customer.id'     => $inv->{customer},
        'customer.tier'   => $inv->{tier});

    select(undef, undef, undef, 0.05);  # simulate work

    my $sent     = (rand() > 0.1) ? 1 : 0;
    my $dur_ms   = int(tv_interval($t_inv) * 1000);
    my $status   = $sent ? 'delivered' : 'failed';

    otel_end($span_id, attributes => {
        'invoice.sent'        => $sent ? 'true' : 'false',
        'invoice.status'      => $status,
        'invoice.duration_ms' => $dur_ms,
    }, $sent ? () : (error => 'SMTP timeout'));

    otel_histogram('invoice.processing_ms', $dur_ms,
        'customer.tier' => $inv->{tier}, 'invoice.status' => $status);
    otel_counter('invoice.processed', 1,
        'customer.tier' => $inv->{tier}, 'invoice.status' => $status);

    if ($sent) {
        $delivered++;
        otel_log('INFO', "Invoice $inv->{id} delivered to $inv->{customer}", $inv_tp,
            'invoice.id'     => $inv->{id},
            'invoice.amount' => $inv->{amount},
            'customer.tier'  => $inv->{tier});
    } else {
        $failed++;
        otel_log('ERROR', "Invoice $inv->{id} delivery failed: SMTP timeout", $inv_tp,
            'invoice.id'    => $inv->{id},
            'customer.tier' => $inv->{tier},
            'error.type'    => 'smtp_timeout');
    }

    printf "  %s %s  \$%.2f  [%s]\n",
        $sent ? '✅' : '🚫',
        $inv->{id}, $inv->{amount}, $inv->{tier};
}

my $batch_dur = int(tv_interval($t0) * 1000);
otel_end($batch_id, attributes => {
    'batch.invoices_processed' => scalar @invoices,
    'batch.delivered'          => $delivered,
    'batch.failed'             => $failed,
    'batch.duration_ms'        => $batch_dur,
    'batch.status'             => ($failed == 0 ? 'success' : 'partial'),
});

otel_histogram('invoice.batch.duration_ms', $batch_dur, 'batch.source' => 'legacy-perl-billing');
otel_log('INFO', "Invoice batch complete: $delivered delivered, $failed failed", $batch_tp,
    'batch.delivered'   => $delivered,
    'batch.failed'      => $failed,
    'batch.duration_ms' => $batch_dur);

print "[$SVC] Done → Kibana APM → $SVC\n";
