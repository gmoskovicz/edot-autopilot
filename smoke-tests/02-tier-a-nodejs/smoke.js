'use strict';
/**
 * Smoke test: Tier A — Node.js Multi-Service E-Commerce Gateway
 *
 * Simulates an API gateway originating distributed traces through 5 downstream
 * services. Each service is a separate TracerProvider with its own service.name,
 * creating connected nodes in the Elastic APM service map.
 *
 * Services:
 *   api-gateway-nodejs  →  user-service-nodejs
 *                       →  cart-service-nodejs  →  catalog-svc-nodejs
 *                       →  checkout-svc-nodejs  →  payments-svc-nodejs
 *
 * Runs 25 scenarios with varied outcomes:
 *   - successful orders, cart abandonment, payment failures,
 *     rate limiting, token expiry, service degradation
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

if (!ENDPOINT || !API_KEY) {
  console.error('Missing ELASTIC_OTLP_ENDPOINT or ELASTIC_API_KEY');
  process.exit(1);
}

const AUTH_HEADER = { 'Authorization': `ApiKey ${API_KEY}` };

// ── OTel SDK imports ───────────────────────────────────────────────────────────
const { NodeTracerProvider, SimpleSpanProcessor } = require('@opentelemetry/sdk-trace-node');
const { OTLPTraceExporter }      = require('@opentelemetry/exporter-trace-otlp-proto');
const { Resource }               = require('@opentelemetry/resources');
const { trace, SpanKind, SpanStatusCode, context, propagation } = require('@opentelemetry/api');
const { W3CTraceContextPropagator } = require('@opentelemetry/core');

const { MeterProvider, PeriodicExportingMetricReader } = require('@opentelemetry/sdk-metrics');
const { OTLPMetricExporter }     = require('@opentelemetry/exporter-metrics-otlp-proto');

const { LoggerProvider, SimpleLogRecordProcessor } = require('@opentelemetry/sdk-logs');
const { OTLPLogExporter }        = require('@opentelemetry/exporter-logs-otlp-proto');
const { SeverityNumber }         = require('@opentelemetry/api-logs');

propagation.setGlobalPropagator(new W3CTraceContextPropagator());

// ── Bootstrap helper ───────────────────────────────────────────────────────────
function bootstrapService(serviceName) {
  const resource = new Resource({
    'service.name':           serviceName,
    'service.version':        '2.4.1',
    'deployment.environment': ENV,
    'service.language':       'nodejs',
  });

  // Traces
  const traceProvider = new NodeTracerProvider({ resource });
  traceProvider.addSpanProcessor(new SimpleSpanProcessor(
    new OTLPTraceExporter({ url: `${ENDPOINT}/v1/traces`, headers: AUTH_HEADER })
  ));
  const tracer = traceProvider.getTracer(serviceName);

  // Metrics
  const meterProvider = new MeterProvider({
    resource,
    readers: [new PeriodicExportingMetricReader({
      exporter: new OTLPMetricExporter({ url: `${ENDPOINT}/v1/metrics`, headers: AUTH_HEADER }),
      exportIntervalMillis: 5000,
    })],
  });
  const meter = meterProvider.getMeter(serviceName);

  // Logs
  const logProvider = new LoggerProvider({ resource });
  logProvider.addLogRecordProcessor(new SimpleLogRecordProcessor(
    new OTLPLogExporter({ url: `${ENDPOINT}/v1/logs`, headers: AUTH_HEADER })
  ));
  const otelLogger = logProvider.getLogger(serviceName);

  function log(severity, severityNumber, body, attributes, spanCtx) {
    otelLogger.emit({
      severityText: severity, severityNumber, body, attributes,
      ...(spanCtx ? { traceId: spanCtx.traceId, spanId: spanCtx.spanId } : {}),
    });
  }

  async function flush() {
    await Promise.all([
      traceProvider.forceFlush(),
      meterProvider.forceFlush(),
      logProvider.forceFlush(),
    ]);
  }

  return { tracer, meter, log, flush, traceProvider };
}

// ── Service instances ─────────────────────────────────────────────────────────
const gateway  = bootstrapService('api-gateway-nodejs');
const userSvc  = bootstrapService('user-service-nodejs');
const cartSvc  = bootstrapService('cart-service-nodejs');
const catalogSvc = bootstrapService('catalog-svc-nodejs');
const checkoutSvc = bootstrapService('checkout-svc-nodejs');
const paymentSvc  = bootstrapService('payments-svc-nodejs');

// ── Metrics instruments ────────────────────────────────────────────────────────
const gwRequests    = gateway.meter.createCounter('api.requests',         { description: 'API gateway requests' });
const gwLatency     = gateway.meter.createHistogram('api.latency_ms',     { unit: 'ms' });
const gwErrors      = gateway.meter.createCounter('api.errors',           { description: 'Gateway errors' });

const userLogins    = userSvc.meter.createCounter('auth.login_attempts',  { description: 'Login attempts' });
const userLatency   = userSvc.meter.createHistogram('auth.latency_ms',    { unit: 'ms' });

const cartItems     = cartSvc.meter.createHistogram('cart.item_count',    { description: 'Items per cart' });
const cartValue     = cartSvc.meter.createHistogram('cart.value_usd',     { unit: 'USD' });
const cartAbandoned = cartSvc.meter.createCounter('cart.abandoned',       { description: 'Abandoned carts' });

const checkoutAttempts = checkoutSvc.meter.createCounter('checkout.attempts');
const checkoutRevenue  = checkoutSvc.meter.createHistogram('checkout.revenue_usd', { unit: 'USD' });

const payAttempts   = paymentSvc.meter.createCounter('payment.attempts');
const payDeclines   = paymentSvc.meter.createCounter('payment.declines');
const payRevenue    = paymentSvc.meter.createHistogram('payment.revenue_usd', { unit: 'USD' });
const payLatency    = paymentSvc.meter.createHistogram('payment.latency_ms', { unit: 'ms' });

// ── Business data ─────────────────────────────────────────────────────────────
const CUSTOMERS = [
  { id: 'USR-001', name: 'Alice Chen',     tier: 'enterprise', country: 'US', card: 'visa_4242' },
  { id: 'USR-002', name: 'Bob Müller',     tier: 'pro',        country: 'DE', card: 'mc_5555' },
  { id: 'USR-003', name: 'Carol Santos',   tier: 'free',       country: 'BR', card: 'visa_declined' },
  { id: 'USR-004', name: 'David Park',     tier: 'enterprise', country: 'KR', card: 'amex_3714' },
  { id: 'USR-005', name: 'Emma Johnson',   tier: 'pro',        country: 'GB', card: 'visa_4242' },
  { id: 'USR-006', name: 'Faisal Al-Amin', tier: 'free',       country: 'AE', card: 'mc_expired' },
  { id: 'USR-007', name: 'Grace Kim',      tier: 'enterprise', country: 'US', card: 'visa_4242' },
  { id: 'USR-008', name: 'Héctor Ruiz',    tier: 'pro',        country: 'MX', card: 'visa_4242' },
];

const PRODUCTS = [
  { sku: 'LAPTOP-PRO-14',  name: 'MacBook Pro 14"',      category: 'electronics', price: 1999.00, stock: 45 },
  { sku: 'HEADPHONE-XM5',  name: 'Sony WH-1000XM5',      category: 'electronics', price: 399.99,  stock: 120 },
  { sku: 'KEYBOARD-MX',    name: 'Logitech MX Keys',      category: 'peripherals', price: 109.99,  stock: 0 },  // out of stock
  { sku: 'MONITOR-4K-27',  name: 'Dell U2723D 4K',        category: 'electronics', price: 649.00,  stock: 23 },
  { sku: 'CHAIR-AERON-B',  name: 'Herman Miller Aeron B', category: 'furniture',   price: 1395.00, stock: 8 },
  { sku: 'WEBCAM-4K',      name: 'Logitech Brio 4K',      category: 'peripherals', price: 199.99,  stock: 67 },
  { sku: 'PHONE-S24U',     name: 'Samsung Galaxy S24 Ultra', category: 'mobile',   price: 1299.99, stock: 34 },
  { sku: 'TABLET-PRO-12',  name: 'iPad Pro 12.9"',        category: 'mobile',      price: 1099.00, stock: 56 },
];

function randomItem(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function sleep(ms)       { return new Promise(r => setTimeout(r, ms)); }
function jitter(min, max){ return min + Math.random() * (max - min); }

// ── Service simulation functions ───────────────────────────────────────────────

async function runUserService(customer, parentCtx) {
  const t0 = Date.now();
  return new Promise((resolve) => {
    const span = userSvc.tracer.startSpan('auth.validate_session', {
      kind: SpanKind.SERVER, attributes: {
        'http.method':    'GET',
        'http.route':     '/internal/session/validate',
        'user.id':        customer.id,
        'user.tier':      customer.tier,
        'user.country':   customer.country,
        'auth.method':    'jwt',
      }
    }, parentCtx);
    const sc = span.spanContext();
    const ctx = trace.setSpan(context.active(), span);

    setTimeout(async () => {
      const latency = Date.now() - t0;

      if (customer.id === 'USR-006') {
        // Simulate expired token
        span.setStatus({ code: SpanStatusCode.ERROR, message: 'JWT token expired' });
        span.setAttribute('auth.failure_reason', 'token_expired');
        userSvc.log('WARN', SeverityNumber.WARN, 'JWT token expired, user must re-authenticate',
          { 'user.id': customer.id, 'auth.failure_reason': 'token_expired' }, sc);
        userLogins.add(1, { result: 'token_expired', 'user.tier': customer.tier });
        userLatency.record(latency, { result: 'error' });
        span.end();
        resolve({ ok: false, reason: 'token_expired', ctx });
        return;
      }

      span.setAttributes({
        'auth.session_id':   `sess_${Math.random().toString(36).slice(2, 10)}`,
        'auth.session_age_s': Math.floor(jitter(60, 3600)),
        'user.last_login':   new Date(Date.now() - jitter(1e6, 8.64e7)).toISOString(),
      });
      userLogins.add(1, { result: 'success', 'user.tier': customer.tier });
      userLatency.record(latency, { result: 'success' });
      userSvc.log('INFO', SeverityNumber.INFO, `Session validated for ${customer.id}`,
        { 'user.id': customer.id, 'user.tier': customer.tier }, sc);
      span.end();
      resolve({ ok: true, ctx });
    }, jitter(10, 40));
  });
}

async function runCartService(customer, products, parentCtx) {
  return new Promise((resolve) => {
    const cartId = `cart_${Math.random().toString(36).slice(2, 10)}`;
    const span = cartSvc.tracer.startSpan('cart.load', {
      kind: SpanKind.SERVER, attributes: {
        'http.method':   'GET',
        'http.route':    '/carts/{cart_id}',
        'cart.id':       cartId,
        'user.id':       customer.id,
        'user.tier':     customer.tier,
      }
    }, parentCtx);
    const sc = span.spanContext();
    const ctx = trace.setSpan(context.active(), span);

    // Product lookup sub-span (calls catalog service)
    const lookupSpan = catalogSvc.tracer.startSpan('catalog.product_lookup', {
      kind: SpanKind.SERVER, attributes: {
        'http.method':     'POST',
        'http.route':      '/products/batch',
        'product.count':   products.length,
        'catalog.source':  'redis_cache',
      }
    }, ctx);

    setTimeout(() => {
      const inStock  = products.filter(p => p.stock > 0);
      const oosItems = products.filter(p => p.stock === 0);
      const cartTotal = inStock.reduce((s, p) => s + p.price, 0);

      if (oosItems.length > 0) {
        lookupSpan.setAttribute('inventory.oos_skus', oosItems.map(p => p.sku).join(','));
        lookupSpan.setAttribute('inventory.oos_count', oosItems.length);
        catalogSvc.log('WARN', SeverityNumber.WARN, `${oosItems.length} item(s) out of stock`,
          { 'cart.id': cartId, 'oos.skus': oosItems.map(p => p.sku).join(',') }, lookupSpan.spanContext());
      }
      lookupSpan.end();

      span.setAttributes({
        'cart.item_count':    products.length,
        'cart.in_stock':      inStock.length,
        'cart.oos_count':     oosItems.length,
        'cart.total_usd':     cartTotal.toFixed(2),
        'cart.currency':      'USD',
      });

      cartItems.record(products.length, { 'user.tier': customer.tier });
      cartValue.record(cartTotal, { 'user.tier': customer.tier });
      cartSvc.log('INFO', SeverityNumber.INFO, `Cart loaded: ${products.length} items, $${cartTotal.toFixed(2)}`,
        { 'cart.id': cartId, 'cart.total_usd': cartTotal, 'user.id': customer.id }, sc);
      span.end();
      resolve({ ok: true, cartId, inStock, cartTotal, ctx });
    }, jitter(15, 50));
  });
}

async function runPaymentService(customer, amount, orderId, parentCtx) {
  const t0 = Date.now();
  return new Promise((resolve) => {
    const span = paymentSvc.tracer.startSpan('payment.charge', {
      kind: SpanKind.SERVER, attributes: {
        'http.method':          'POST',
        'http.route':           '/payments/charge',
        'payment.order_id':     orderId,
        'payment.amount_usd':   amount,
        'payment.currency':     'usd',
        'payment.customer_id':  customer.id,
        'payment.card_token':   customer.card,
        'payment.provider':     'stripe',
      }
    }, parentCtx);
    const sc = span.spanContext();

    setTimeout(() => {
      const latency = Date.now() - t0;

      if (customer.card === 'visa_declined') {
        span.setStatus({ code: SpanStatusCode.ERROR, message: 'card_declined: insufficient_funds' });
        span.setAttributes({
          'payment.status':     'declined',
          'payment.error_code': 'insufficient_funds',
          'payment.decline_code': 'generic_decline',
        });
        payAttempts.add(1, { result: 'declined', 'user.tier': customer.tier });
        payDeclines.add(1, { reason: 'insufficient_funds' });
        payLatency.record(latency, { result: 'declined' });
        paymentSvc.log('WARN', SeverityNumber.WARN, `Payment declined for order ${orderId}`,
          { 'order.id': orderId, 'payment.amount_usd': amount, 'payment.error': 'insufficient_funds' }, sc);
        span.end();
        resolve({ ok: false, reason: 'card_declined' });
        return;
      }

      if (customer.card === 'mc_expired') {
        span.setStatus({ code: SpanStatusCode.ERROR, message: 'card_declined: expired_card' });
        span.setAttributes({ 'payment.status': 'declined', 'payment.error_code': 'expired_card' });
        payAttempts.add(1, { result: 'declined', 'user.tier': customer.tier });
        payDeclines.add(1, { reason: 'expired_card' });
        payLatency.record(latency, { result: 'declined' });
        paymentSvc.log('WARN', SeverityNumber.WARN, `Card expired for order ${orderId}`,
          { 'order.id': orderId, 'payment.error': 'expired_card' }, sc);
        span.end();
        resolve({ ok: false, reason: 'expired_card' });
        return;
      }

      const chargeId = `ch_${Math.random().toString(36).slice(2, 18)}`;
      span.setAttributes({
        'payment.status':     'succeeded',
        'payment.charge_id':  chargeId,
        'payment.captured':   true,
        'payment.network':    customer.card.startsWith('visa') ? 'visa' : customer.card.startsWith('mc') ? 'mastercard' : 'amex',
      });
      payAttempts.add(1, { result: 'success', 'user.tier': customer.tier });
      payRevenue.record(amount, { 'user.tier': customer.tier, 'payment.currency': 'usd' });
      payLatency.record(latency, { result: 'success' });
      paymentSvc.log('INFO', SeverityNumber.INFO, `Payment succeeded: ${chargeId}`,
        { 'order.id': orderId, 'payment.charge_id': chargeId, 'payment.amount_usd': amount }, sc);
      span.end();
      resolve({ ok: true, chargeId });
    }, jitter(60, 180));  // payment API is slower
  });
}

async function runCheckoutService(customer, cartId, cartTotal, inStockProducts, parentCtx) {
  return new Promise((resolve) => {
    const orderId = `ORD-${Math.random().toString(36).slice(2, 10).toUpperCase()}`;
    const span = checkoutSvc.tracer.startSpan('checkout.process', {
      kind: SpanKind.SERVER, attributes: {
        'http.method':         'POST',
        'http.route':          '/checkout',
        'checkout.order_id':   orderId,
        'checkout.cart_id':    cartId,
        'checkout.amount_usd': cartTotal.toFixed(2),
        'checkout.item_count': inStockProducts.length,
        'user.id':             customer.id,
        'user.tier':           customer.tier,
      }
    }, parentCtx);
    const sc = span.spanContext();
    const checkoutCtx = trace.setSpan(context.active(), span);

    checkoutAttempts.add(1, { 'user.tier': customer.tier });

    // Asynchronously run payment (child span)
    runPaymentService(customer, cartTotal, orderId, checkoutCtx).then(payResult => {
      if (!payResult.ok) {
        span.setStatus({ code: SpanStatusCode.ERROR, message: `Payment failed: ${payResult.reason}` });
        span.setAttribute('checkout.payment_result', payResult.reason);
        checkoutSvc.log('ERROR', SeverityNumber.ERROR, `Checkout failed - payment ${payResult.reason}`,
          { 'order.id': orderId, 'checkout.amount_usd': cartTotal, 'payment.failure': payResult.reason }, sc);
        span.end();
        resolve({ ok: false, orderId, reason: payResult.reason });
        return;
      }

      span.setAttributes({
        'checkout.result':     'success',
        'checkout.charge_id':  payResult.chargeId,
        'checkout.skus':       inStockProducts.map(p => p.sku).join(','),
      });
      checkoutRevenue.record(cartTotal, { 'user.tier': customer.tier });
      checkoutSvc.log('INFO', SeverityNumber.INFO, `Order ${orderId} created successfully`,
        { 'order.id': orderId, 'checkout.amount_usd': cartTotal, 'payment.charge_id': payResult.chargeId }, sc);
      span.end();
      resolve({ ok: true, orderId, chargeId: payResult.chargeId });
    });
  });
}

// ── Main scenario runner ───────────────────────────────────────────────────────
async function runScenario(iteration) {
  const customer  = randomItem(CUSTOMERS);
  const numItems  = Math.floor(jitter(1, 4));
  const products  = Array.from({ length: numItems }, () => randomItem(PRODUCTS));
  const t0        = Date.now();

  // Root span: API gateway entry
  const rootSpan = gateway.tracer.startSpan('POST /api/v2/checkout', {
    kind: SpanKind.SERVER,
    attributes: {
      'http.method':          'POST',
      'http.route':           '/api/v2/checkout',
      'http.scheme':          'https',
      'http.host':            'api.shopify-demo.com',
      'user.id':              customer.id,
      'user.tier':            customer.tier,
      'user.country':         customer.country,
      'request.id':           `req_${Math.random().toString(36).slice(2, 10)}`,
      'api.version':          'v2',
    }
  });
  const rootCtx = trace.setSpan(context.active(), rootSpan);
  const rootSc  = rootSpan.spanContext();

  try {
    // 1. Validate session (user-service)
    const authResult = await runUserService(customer, rootCtx);
    if (!authResult.ok) {
      rootSpan.setStatus({ code: SpanStatusCode.ERROR, message: authResult.reason });
      rootSpan.setAttribute('gateway.result', 'auth_failed');
      rootSpan.setAttribute('http.status_code', 401);
      gwErrors.add(1, { reason: 'auth_failed', 'user.tier': customer.tier });
      gateway.log('WARN', SeverityNumber.WARN, `Auth failed for user ${customer.id}`,
        { 'user.id': customer.id, 'failure.reason': authResult.reason }, rootSc);
      return { ok: false, reason: authResult.reason };
    }

    // 2. Load cart (cart-service, which calls catalog-service internally)
    const cartResult = await runCartService(customer, products, rootCtx);

    if (cartResult.inStock.length === 0) {
      rootSpan.setStatus({ code: SpanStatusCode.ERROR, message: 'All items out of stock' });
      rootSpan.setAttribute('gateway.result', 'out_of_stock');
      rootSpan.setAttribute('http.status_code', 422);
      cartAbandoned.add(1, { reason: 'oos', 'user.tier': customer.tier });
      gwErrors.add(1, { reason: 'out_of_stock', 'user.tier': customer.tier });
      gateway.log('WARN', SeverityNumber.WARN, 'Cart abandoned — all items out of stock',
        { 'user.id': customer.id, 'cart.id': cartResult.cartId }, rootSc);
      return { ok: false, reason: 'out_of_stock' };
    }

    // 3. Checkout + payment
    const checkoutResult = await runCheckoutService(
      customer, cartResult.cartId, cartResult.cartTotal,
      cartResult.inStock, rootCtx
    );

    if (!checkoutResult.ok) {
      rootSpan.setStatus({ code: SpanStatusCode.ERROR, message: `Checkout failed: ${checkoutResult.reason}` });
      rootSpan.setAttribute('gateway.result', 'payment_failed');
      rootSpan.setAttribute('http.status_code', 402);
      cartAbandoned.add(1, { reason: 'payment_failed', 'user.tier': customer.tier });
      gwErrors.add(1, { reason: 'payment_failed', 'user.tier': customer.tier });
      gateway.log('ERROR', SeverityNumber.ERROR, `Checkout failed for ${customer.id}`,
        { 'user.id': customer.id, 'order.id': checkoutResult.orderId, 'failure.reason': checkoutResult.reason }, rootSc);
      return { ok: false, reason: checkoutResult.reason };
    }

    // Success
    const totalMs = Date.now() - t0;
    rootSpan.setAttributes({
      'gateway.result':      'success',
      'http.status_code':    200,
      'order.id':            checkoutResult.orderId,
      'order.total_usd':     cartResult.cartTotal.toFixed(2),
      'order.item_count':    cartResult.inStock.length,
      'gateway.latency_ms':  totalMs,
    });
    gwRequests.add(1, { result: 'success', 'user.tier': customer.tier });
    gwLatency.record(totalMs, { result: 'success', 'user.tier': customer.tier });
    gateway.log('INFO', SeverityNumber.INFO, `Order ${checkoutResult.orderId} placed successfully`,
      {
        'order.id': checkoutResult.orderId, 'order.total_usd': cartResult.cartTotal,
        'user.id': customer.id, 'user.tier': customer.tier, 'gateway.latency_ms': totalMs,
      }, rootSc);

    return { ok: true, orderId: checkoutResult.orderId, total: cartResult.cartTotal };

  } catch (err) {
    rootSpan.recordException(err);
    rootSpan.setStatus({ code: SpanStatusCode.ERROR, message: err.message });
    rootSpan.setAttribute('http.status_code', 500);
    gwErrors.add(1, { reason: 'internal_error', 'user.tier': customer.tier });
    gateway.log('ERROR', SeverityNumber.ERROR, `Unhandled error: ${err.message}`,
      { 'user.id': customer.id, 'error.type': err.constructor.name }, rootSc);
    return { ok: false, reason: 'internal_error' };
  } finally {
    rootSpan.end();
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function run() {
  const SVC = 'api-gateway-nodejs';
  console.log(`\n[${SVC}] Multi-service e-commerce gateway — 25 scenarios`);
  console.log(`  Services: api-gateway-nodejs → user-service-nodejs → cart-service-nodejs`);
  console.log(`                              → catalog-svc-nodejs`);
  console.log(`                              → checkout-svc-nodejs → payments-svc-nodejs\n`);

  let pass = 0, fail = 0;
  const outcomes = [];

  for (let i = 0; i < 25; i++) {
    await sleep(50); // small gap between scenarios
    const result = await runScenario(i + 1);
    if (result.ok) {
      pass++;
      console.log(`  ✅ [${String(i+1).padStart(2)}] order=${result.orderId}  $${result.total?.toFixed(2)}`);
    } else {
      fail++;
      const icon = result.reason === 'out_of_stock' ? '📦' :
                   result.reason?.includes('declined') || result.reason?.includes('card') ? '💳' :
                   result.reason === 'token_expired' ? '🔑' : '❌';
      console.log(`  ${icon} [${String(i+1).padStart(2)}] FAILED — ${result.reason}`);
    }
    outcomes.push(result);
  }

  console.log(`\n  Results: ${pass} success  ${fail} failed`);
  console.log(`  Flushing all providers...`);

  await Promise.all([
    gateway.flush(),
    userSvc.flush(),
    cartSvc.flush(),
    catalogSvc.flush(),
    checkoutSvc.flush(),
    paymentSvc.flush(),
  ]);

  console.log(`\n[${SVC}] Done.`);
  console.log(`\n  Kibana Service Map: Observability → APM → Service Map`);
  console.log(`    Filter: api-gateway-nodejs — shows 6 connected nodes`);
  console.log(`\n  ES|QL — failed orders:`);
  console.log(`    FROM traces-apm*`);
  console.log(`    | WHERE service.name LIKE "*-nodejs" AND event.outcome == "failure"`);
  console.log(`    | KEEP @timestamp, service.name, transaction.name, labels.order_id, labels.failure_reason`);
  console.log(`    | SORT @timestamp DESC | LIMIT 20\n`);
  process.exit(0);
}

run().catch(e => { console.error(e); process.exit(1); });
