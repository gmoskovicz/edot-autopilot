#!/usr/bin/perl
# Smoke test: Tier D — Perl → OTEL Sidecar
# Sends invoice processing spans via LWP to the running sidecar.
# Run: OTEL_SIDECAR_URL=http://127.0.0.1:9411 perl smoke-perl.pl

use strict;
use warnings;
use JSON;
use LWP::UserAgent;

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
    my ($name, %attrs) = @_;
    my $r = post_sidecar({ action => 'start_span', name => $name, attributes => \%attrs });
    return $r->{span_id} // '';
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

print "[$SVC] Sending Perl invoice spans via sidecar at $SIDECAR...\n";

my @invoices = (
    { id => 'INV-PERL-001', amount => 4200.00, customer => 'CUST-ENT-001', tier => 'enterprise' },
    { id => 'INV-PERL-002', amount => 29.99,   customer => 'CUST-FREE-042', tier => 'free' },
    { id => 'INV-PERL-003', amount => 1250.00, customer => 'CUST-PRO-007',  tier => 'pro' },
);

my $batch = otel_start('invoice.batch',
    'batch.count' => scalar @invoices,
    'batch.source' => 'legacy-perl-billing');

for my $inv (@invoices) {
    my $span = otel_start('invoice.process',
        'invoice.id'     => $inv->{id},
        'invoice.amount' => $inv->{amount},
        'customer.id'    => $inv->{customer},
        'customer.tier'  => $inv->{tier});

    select(undef, undef, undef, 0.05);  # simulate work

    my $sent = (rand() > 0.1) ? 1 : 0;
    otel_end($span, attributes => {
        'invoice.sent'   => $sent ? 'true' : 'false',
        'invoice.status' => $sent ? 'delivered' : 'failed',
    }, $sent ? () : (error => 'SMTP timeout'));

    printf "  %s %s  \$%.2f  [%s]\n",
        $sent ? '✅' : '🚫',
        $inv->{id}, $inv->{amount}, $inv->{tier};
}

otel_end($batch, attributes => {
    'batch.invoices_processed' => scalar @invoices,
    'batch.status'             => 'complete'
});

print "[$SVC] Done → Kibana APM → $SVC\n";
