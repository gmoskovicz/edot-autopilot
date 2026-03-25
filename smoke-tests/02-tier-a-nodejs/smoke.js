'use strict';
/**
 * Smoke test: Tier A — Node.js (raw OTel SDK, no framework needed).
 *
 * Sends checkout spans with business attributes directly to Elastic via OTLP/HTTP.
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

// ── OTel SDK setup ────────────────────────────────────────────────────────────
const {
  NodeTracerProvider,
  SimpleSpanProcessor,
} = require('@opentelemetry/sdk-trace-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-proto');
const { Resource } = require('@opentelemetry/resources');
const { trace, SpanKind, SpanStatusCode } = require('@opentelemetry/api');

const provider = new NodeTracerProvider({
  resource: new Resource({
    'service.name':           SVC,
    'service.version':        'smoke',
    'deployment.environment': ENV,
  }),
});

const exporter = new OTLPTraceExporter({
  url: `${ENDPOINT}/v1/traces`,
  headers: { 'Authorization': `ApiKey ${API_KEY}` },
});

provider.addSpanProcessor(new SimpleSpanProcessor(exporter));
provider.register();
const tracer = trace.getTracer(SVC);

// ── Test spans ────────────────────────────────────────────────────────────────
const orders = [
  { id: 'ORD-NODE-001', value: 4200.00, tier: 'enterprise', fraud: 0.15 },
  { id: 'ORD-NODE-002', value: 29.99,   tier: 'free',       fraud: 0.91 },
  { id: 'ORD-NODE-003', value: 1250.00, tier: 'pro',        fraud: 0.42 },
];

console.log(`\n[${SVC}] Sending spans to ${ENDPOINT}...`);

async function run() {
  for (const order of orders) {
    await new Promise(resolve => {
      const span = tracer.startSpan('checkout.complete', { kind: SpanKind.SERVER });
      const ctx  = trace.setSpan(require('@opentelemetry/api').context.active(), span);

      span.setAttributes({
        'order.id':           order.id,
        'order.value_usd':    order.value,
        'customer.tier':      order.tier,
        'fraud.score':        order.fraud,
        'fraud.decision':     order.fraud > 0.85 ? 'blocked' : 'approved',
        'test.run_id':        SVC,
      });

      // Nested payment span
      const paySpan = tracer.startSpan('payment.process', { kind: SpanKind.CLIENT }, ctx);
      paySpan.setAttributes({ 'payment.provider': 'stripe', 'payment.amount_usd': order.value });
      paySpan.end();

      if (order.fraud > 0.85) {
        span.setStatus({ code: SpanStatusCode.ERROR, message: 'Fraud block' });
      }

      span.end();

      const icon   = order.fraud > 0.85 ? '🚫' : '✅';
      const status = order.fraud > 0.85 ? 'blocked' : 'confirmed';
      console.log(`  ${icon} ${order.id}  $${order.value.toFixed(2).padStart(8)}  [${order.tier.padEnd(10)}]  fraud=${order.fraud.toFixed(2)}  → ${status}`);
      resolve();
    });
  }

  await provider.forceFlush();
  console.log(`\n[${SVC}] Done. Verify: Kibana → APM → Services → ${SVC}`);
  process.exit(0);
}

run().catch(e => { console.error(e); process.exit(1); });
