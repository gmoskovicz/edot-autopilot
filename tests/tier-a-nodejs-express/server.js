'use strict';

const express = require('express');
const { trace } = require('@opentelemetry/api');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: process.env.OTEL_SERVICE_NAME || 'nodejs-express-tier-a' });
});

/**
 * POST /checkout — simulates a checkout flow.
 * EDOT auto-instruments the HTTP layer. We enrich with business attributes (Phase 3).
 */
app.post('/checkout', (req, res) => {
  const span = trace.getActiveSpan();
  const { customerId, orderValue, customerTier, items } = req.body;

  // Phase 3: business enrichment
  if (span) {
    span.setAttributes({
      'order.customer_id':   customerId,
      'order.value_usd':     orderValue,
      'customer.tier':       customerTier || 'free',
      'order.item_count':    (items || []).length,
    });
  }

  // Simulate fraud check
  const fraudScore = Math.random();
  if (span) {
    span.setAttributes({
      'fraud.score':    parseFloat(fraudScore.toFixed(3)),
      'fraud.decision': fraudScore > 0.85 ? 'blocked' : 'approved',
    });
  }

  if (fraudScore > 0.85) {
    return res.status(402).json({ error: 'blocked_by_fraud', fraud_score: fraudScore });
  }

  const orderId = `ORD-${Math.floor(Math.random() * 90000) + 10000}`;
  if (span) span.setAttribute('order.id', orderId);

  res.status(201).json({ order_id: orderId, status: 'confirmed' });
});

app.get('/orders/:id', (req, res) => {
  const span = trace.getActiveSpan();
  if (span) span.setAttribute('order.id', req.params.id);

  if (Math.random() < 0.1) {
    return res.status(404).json({ error: 'not_found' });
  }
  res.json({ order_id: req.params.id, status: 'shipped', amount_usd: (Math.random() * 490 + 10).toFixed(2) });
});

app.listen(PORT, () => {
  console.log(`[edot-express] listening on :${PORT}`);
});
