'use strict';
/**
 * Order API — Express.js REST service
 *
 * No observability. Run `Observe this project.` to add OpenTelemetry.
 *
 * Routes:
 *   GET  /health            — liveness probe
 *   POST /orders            — place a new order
 *   GET  /orders/:id        — retrieve order by ID
 *   POST /orders/:id/cancel — cancel a pending order
 */

const express = require('express');
const crypto  = require('crypto');

const app = express();
app.use(express.json());

// ── In-memory store (replace with DB in production) ───────────────────────────
const orders = new Map();

// ── Payment gateway stub (replace with real Stripe calls) ────────────────────
function chargeCard(amountUsd, customerId) {
  // Simulate payment: >$10k is declined
  if (amountUsd > 10000) {
    return { status: 'declined', reason: 'limit_exceeded' };
  }
  return { status: 'charged', chargeId: `ch_${crypto.randomBytes(8).toString('hex')}` };
}

function computeFraudScore(customerId, amountUsd, tier) {
  // Simple fraud heuristic — replace with ML model in production
  let score = Math.random() * 0.4;
  if (amountUsd > 500) score += 0.1;
  if (tier === 'enterprise') score -= 0.15;
  return Math.max(0, Math.min(1, score));
}

// ── Routes ────────────────────────────────────────────────────────────────────

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.post('/orders', (req, res) => {
  const { customer_id = 'anon', customer_tier = 'standard', items = [] } = req.body || {};

  const totalUsd = items.reduce((sum, item) => {
    return sum + (item.price_usd || 0) * (item.qty || 1);
  }, 0);

  if (totalUsd <= 0) {
    return res.status(400).json({ error: 'order total must be > 0' });
  }

  const fraudScore = computeFraudScore(customer_id, totalUsd, customer_tier);
  if (fraudScore > 0.7) {
    console.warn(`Order blocked: fraud_score=${fraudScore.toFixed(3)} customer=${customer_id}`);
    return res.status(402).json({ error: 'order blocked', reason: 'fraud_check_failed' });
  }

  const payment = chargeCard(totalUsd, customer_id);
  if (payment.status !== 'charged') {
    return res.status(402).json({ error: 'payment failed', reason: payment.reason });
  }

  const orderId = crypto.randomUUID();
  orders.set(orderId, {
    order_id:      orderId,
    customer_id,
    customer_tier,
    total_usd:     totalUsd,
    status:        'confirmed',
    fraud_score:   fraudScore,
    charge_id:     payment.chargeId,
    created_at:    new Date().toISOString(),
  });

  console.log(`Order created: ${orderId} customer=${customer_id} total=$${totalUsd.toFixed(2)}`);
  return res.status(201).json({
    order_id:  orderId,
    status:    'confirmed',
    total_usd: totalUsd,
    charge_id: payment.chargeId,
  });
});

app.get('/orders/:id', (req, res) => {
  const order = orders.get(req.params.id);
  if (!order) {
    return res.status(404).json({ error: 'not found' });
  }
  return res.json(order);
});

app.post('/orders/:id/cancel', (req, res) => {
  const order = orders.get(req.params.id);
  if (!order) {
    return res.status(404).json({ error: 'not found' });
  }
  if (order.status !== 'confirmed') {
    return res.status(409).json({ error: 'cannot cancel', current_status: order.status });
  }
  order.status = 'cancelled';
  orders.set(req.params.id, order);
  console.log(`Order cancelled: ${req.params.id}`);
  return res.json({ order_id: req.params.id, status: 'cancelled' });
});

// ── Start ─────────────────────────────────────────────────────────────────────
if (require.main === module) {
  const PORT = process.env.PORT || 3000;
  app.listen(PORT, () => {
    console.log(`Order API listening on port ${PORT}`);
  });
}

module.exports = app;
