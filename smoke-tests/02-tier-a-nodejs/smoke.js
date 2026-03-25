'use strict';
/**
 * Smoke test: Tier A — Node.js (full O11y: traces + logs + metrics).
 *
 * Sends checkout spans with business attributes, correlated logs, and
 * counters/histograms directly to Elastic via OTLP/HTTP.
 *
 * Run:
 *   cd smoke-tests && node 02-tier-a-nodejs/smoke.js
 */

const path = require('path');
const fs   = require('fs');

// ── Load .env ─────────────────────────────────────────────────────────────────
const envFile = path.join(__dirname, '..', '.env');
if (fs.existsSync(envFile)) {
  fs.readFileSync(envFile, 'utf8').split('\n').forEach(line => {
    line = line.trim();
    if (line && !line.startsWith('#') && line.includes('=')) {
      const [k, ...v] = line.split('=');
      process.env[k.trim()] ??= v.join('=').trim();
    }
  });
}

const ENDPOINT = (process.env.ELASTIC_OTLP_ENDPOINT || '').replace(/\/$/, '');
const API_KEY  = process.env.ELASTIC_API_KEY || '';
const ENV      = process.env.OTEL_DEPLOYMENT_ENVIRONMENT || 'smoke-test';
const SVC      = 'smoke-tier-a-nodejs';

if (!ENDPOINT || !API_KEY) {
  console.error('Missing ELASTIC_OTLP_ENDPOINT or ELASTIC_API_KEY');
  process.exit(1);
}

const AUTH_HEADER = { 'Authorization': `ApiKey ${API_KEY}` };

// ── Traces ────────────────────────────────────────────────────────────────────
const { NodeTracerProvider, SimpleSpanProcessor } = require('@opentelemetry/sdk-trace-node');
const { OTLPTraceExporter }   = require('@opentelemetry/exporter-trace-otlp-proto');
const { Resource }            = require('@opentelemetry/resources');
const { trace, SpanKind, SpanStatusCode, context } = require('@opentelemetry/api');

const resource = new Resource({
  'service.name':           SVC,
  'service.version':        'smoke',
  'deployment.environment': ENV,
});

const traceProvider = new NodeTracerProvider({ resource });
traceProvider.addSpanProcessor(new SimpleSpanProcessor(
  new OTLPTraceExporter({ url: `${ENDPOINT}/v1/traces`, headers: AUTH_HEADER })
));
traceProvider.register();
const tracer = trace.getTracer(SVC);

// ── Metrics ────────────────────────────────────────────────────────────────────
const { MeterProvider, PeriodicExportingMetricReader } = require('@opentelemetry/sdk-metrics');
const { OTLPMetricExporter } = require('@opentelemetry/exporter-metrics-otlp-proto');

const meterProvider = new MeterProvider({
  resource,
  readers: [new PeriodicExportingMetricReader({
    exporter: new OTLPMetricExporter({ url: `${ENDPOINT}/v1/metrics`, headers: AUTH_HEADER }),
    exportIntervalMillis: 5000,
  })],
});
const meter = meterProvider.getMeter(SVC);

const checkoutCounter  = meter.createCounter('checkout.requests',
  { description: 'Total checkout attempts' });
const orderValueHist   = meter.createHistogram('checkout.order_value_usd',
  { description: 'Order value in USD', unit: 'USD' });
const fraudScoreHist   = meter.createHistogram('checkout.fraud_score',
  { description: 'Fraud score distribution' });
const paymentDuration  = meter.createHistogram('payment.duration_ms',
  { description: 'Payment processing latency', unit: 'ms' });

// ── Logs ──────────────────────────────────────────────────────────────────────
const { LoggerProvider, SimpleLogRecordProcessor } = require('@opentelemetry/sdk-logs');
const { OTLPLogExporter }  = require('@opentelemetry/exporter-logs-otlp-proto');
const { SeverityNumber }   = require('@opentelemetry/api-logs');

const logProvider = new LoggerProvider({ resource });
logProvider.addLogRecordProcessor(new SimpleLogRecordProcessor(
  new OTLPLogExporter({ url: `${ENDPOINT}/v1/logs`, headers: AUTH_HEADER })
));
const otelLogger = logProvider.getLogger(SVC);

function emitLog(severity, severityNumber, body, attributes, spanContext) {
  otelLogger.emit({
    severityText:   severity,
    severityNumber: severityNumber,
    body,
    attributes,
    // Correlate to current trace/span
    ...(spanContext ? {
      traceId: spanContext.traceId,
      spanId:  spanContext.spanId,
    } : {}),
  });
}

// ── Test data ──────────────────────────────────────────────────────────────────
const orders = [
  { id: 'ORD-NODE-001', value: 4200.00, tier: 'enterprise', fraud: 0.15, method: 'wire_transfer' },
  { id: 'ORD-NODE-002', value: 29.99,   tier: 'free',       fraud: 0.91, method: 'card' },
  { id: 'ORD-NODE-003', value: 1250.00, tier: 'pro',        fraud: 0.42, method: 'paypal' },
  { id: 'ORD-NODE-004', value: 8750.00, tier: 'enterprise', fraud: 0.08, method: 'wire_transfer' },
];

console.log(`\n[${SVC}] Sending traces + logs + metrics to Elastic...`);

async function run() {
  for (const order of orders) {
    const decision = order.fraud > 0.85 ? 'blocked' : 'approved';

    const rootSpan = tracer.startSpan('checkout.complete', { kind: SpanKind.SERVER });
    const ctx      = trace.setSpan(context.active(), rootSpan);
    const sc       = rootSpan.spanContext();

    rootSpan.setAttributes({
      'order.id':           order.id,
      'order.value_usd':    order.value,
      'customer.tier':      order.tier,
      'fraud.score':        order.fraud,
      'fraud.decision':     decision,
      'payment.method':     order.method,
      'inventory.reserved': order.fraud < 0.85,
      'test.run_id':        SVC,
    });

    // Nested payment span
    const t0      = Date.now();
    const paySpan = tracer.startSpan('payment.process', { kind: SpanKind.CLIENT }, ctx);
    paySpan.setAttributes({ 'payment.provider': 'stripe', 'payment.amount_usd': order.value });
    if (order.fraud > 0.85) {
      paySpan.setStatus({ code: SpanStatusCode.ERROR, message: 'payment skipped — fraud block' });
    }
    paySpan.end();
    const payMs = Date.now() - t0;

    if (order.fraud > 0.85) {
      rootSpan.setStatus({ code: SpanStatusCode.ERROR, message: 'Fraud block' });
    }
    rootSpan.end();

    // Metrics (recorded after span ends — trace context already captured)
    const attrs = { 'customer.tier': order.tier, 'fraud.decision': decision };
    checkoutCounter.add(1, attrs);
    orderValueHist.record(order.value, attrs);
    fraudScoreHist.record(order.fraud,  { 'customer.tier': order.tier });
    paymentDuration.record(payMs,        { 'payment.method': order.method });

    // Structured log correlated to span
    if (order.fraud > 0.85) {
      emitLog('WARN', SeverityNumber.WARN,
        'checkout blocked by fraud engine',
        { 'order.id': order.id, 'fraud.score': order.fraud,
          'customer.tier': order.tier, 'order.value_usd': order.value },
        sc);
    } else {
      emitLog('INFO', SeverityNumber.INFO,
        'checkout completed successfully',
        { 'order.id': order.id, 'payment.method': order.method,
          'customer.tier': order.tier, 'order.value_usd': order.value },
        sc);
    }

    const icon = order.fraud > 0.85 ? '🚫' : '✅';
    console.log(`  ${icon} ${order.id}  $${order.value.toFixed(2).padStart(8)}  ` +
      `[${order.tier.padEnd(10)}]  fraud=${order.fraud.toFixed(2)}  → ${decision}`);

    await new Promise(r => setTimeout(r, 20));
  }

  await Promise.all([
    traceProvider.forceFlush(),
    meterProvider.forceFlush(),
    logProvider.forceFlush(),
  ]);
  console.log(`\n[${SVC}] Done. Kibana → APM → ${SVC} | Logs: service.name:${SVC} | ` +
    `Metrics: checkout.requests`);
  process.exit(0);
}

run().catch(e => { console.error(e); process.exit(1); });
