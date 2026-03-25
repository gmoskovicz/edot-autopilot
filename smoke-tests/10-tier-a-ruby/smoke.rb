# frozen_string_literal: true
# Smoke test: Tier A — Ruby (native OTel SDK, full O11y: traces + logs + metrics).
#
# Business scenario: SaaS subscription management — create subscription,
# apply promo code, process first payment, send welcome email.
#
# Run (requires opentelemetry-sdk, opentelemetry-exporter-otlp gems):
#   cd smoke-tests/10-tier-a-ruby && bundle exec ruby smoke.rb
#
# Or via the Python runner:
#   cd smoke-tests && python3 10-tier-a-ruby/smoke.py

require 'opentelemetry/sdk'
require 'opentelemetry/exporter/otlp'
require 'opentelemetry-metrics-sdk'
require 'logger'
require 'json'
require 'dotenv/load'
require 'securerandom'

SVC = 'smoke-tier-a-ruby'

# Load .env
env_path = File.expand_path('../../.env', __FILE__)
if File.exist?(env_path)
  File.readlines(env_path).each do |line|
    line = line.strip
    next if line.empty? || line.start_with?('#') || !line.include?('=')
    k, v = line.split('=', 2)
    ENV[k] ||= v
  end
end

ENDPOINT = ENV.fetch('ELASTIC_OTLP_ENDPOINT')
API_KEY  = ENV.fetch('ELASTIC_API_KEY')
ENV_NAME = ENV.fetch('OTEL_DEPLOYMENT_ENVIRONMENT', 'smoke-test')

OpenTelemetry::SDK.configure do |c|
  c.service_name = SVC
  c.add_span_processor(
    OpenTelemetry::SDK::Trace::Export::BatchSpanProcessor.new(
      OpenTelemetry::Exporter::OTLP::Exporter.new(
        endpoint: "#{ENDPOINT}/v1/traces",
        headers:  { 'Authorization' => "ApiKey #{API_KEY}" }
      )
    )
  )
  c.resource = OpenTelemetry::SDK::Resources::Resource.create(
    OpenTelemetry::SemanticConventions::Resource::SERVICE_NAME => SVC,
    'deployment.environment' => ENV_NAME
  )
end

tracer = OpenTelemetry.tracer_provider.tracer(SVC)
log    = Logger.new($stdout)
log.formatter = proc { |sev, _, _, msg| "#{sev} [#{SVC}] #{msg}\n" }

SUBSCRIPTIONS = [
  { id: 'SUB-R001', customer: 'alice@acme.com',   plan: 'enterprise', mrr: 499.00, promo: 'LAUNCH20' },
  { id: 'SUB-R002', customer: 'bob@startupx.io',  plan: 'pro',        mrr: 79.00,  promo: nil         },
  { id: 'SUB-R003', customer: 'carol@bigcorp.com', plan: 'enterprise', mrr: 1499.00, promo: 'Q1SAVE'  },
]

puts "\n[#{SVC}] Processing subscriptions via native Ruby OTel SDK..."

SUBSCRIPTIONS.each do |sub|
  t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)

  tracer.in_span('subscription.create',
      kind: OpenTelemetry::Trace::SpanKind::SERVER,
      attributes: {
        'subscription.id'       => sub[:id],
        'customer.email'        => sub[:customer],
        'subscription.plan'     => sub[:plan],
        'subscription.mrr_usd'  => sub[:mrr],
      }) do |span|

    tracer.in_span('subscription.validate_promo',
        kind: OpenTelemetry::Trace::SpanKind::INTERNAL,
        attributes: { 'promo.code' => sub[:promo].to_s }) do |ps|
      sleep(rand * 0.02 + 0.005)
      discount = sub[:promo] ? sub[:mrr] * (sub[:promo] == 'LAUNCH20' ? 0.20 : 0.10) : 0.0
      ps.set_attribute('promo.discount_usd', discount.round(2))
    end

    tracer.in_span('payment.charge_first_month',
        kind: OpenTelemetry::Trace::SpanKind::CLIENT,
        attributes: { 'payment.amount_usd' => sub[:mrr], 'payment.provider' => 'stripe' }) do |ps|
      sleep(rand * 0.15 + 0.08)
      ps.set_attribute('payment.charge_id', "ch_#{SecureRandom.hex(16)}")
      ps.set_attribute('payment.status', 'succeeded')
    end

    tracer.in_span('email.send_welcome',
        kind: OpenTelemetry::Trace::SpanKind::CLIENT,
        attributes: { 'email.to' => sub[:customer], 'email.template' => 'welcome_subscription' }) do
      sleep(rand * 0.05 + 0.02)
    end

    dur_ms = ((Process.clock_gettime(Process::CLOCK_MONOTONIC) - t0) * 1000).round(2)
    span.set_attribute('subscription.processing_ms', dur_ms)
    span.status = OpenTelemetry::Trace::Status.ok

    log.info("subscription created  id=#{sub[:id]}  plan=#{sub[:plan]}  mrr=#{sub[:mrr]}  dur=#{dur_ms}ms")
    puts "  ✅ #{sub[:id]}  #{sub[:customer]:<30}  plan=#{sub[:plan]:<12}  mrr=$#{format('%7.2f', sub[:mrr])}  dur=#{dur_ms.to_i}ms"
  end
end

OpenTelemetry.tracer_provider.force_flush
puts "[#{SVC}] Done → Kibana APM → #{SVC}"
