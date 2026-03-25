package io.edot.test;

import io.opentelemetry.api.trace.Span;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.Random;
import java.util.UUID;

@RestController
public class OrderController {

    private static final Random RNG = new Random();

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }

    /**
     * POST /orders — simulates order placement.
     * EDOT Java agent auto-instruments the HTTP layer.
     * Business enrichment (Phase 3) added via Span.current().
     */
    @PostMapping("/orders")
    public ResponseEntity<?> createOrder(@RequestBody Map<String, Object> body) {
        Span span = Span.current();

        String customerId   = (String) body.getOrDefault("customerId", "unknown");
        double orderValue   = Double.parseDouble(body.getOrDefault("orderValue", 0.0).toString());
        String customerTier = (String) body.getOrDefault("customerTier", "free");

        // Phase 3: business enrichment
        span.setAttribute("order.customer_id", customerId);
        span.setAttribute("order.value_usd",   orderValue);
        span.setAttribute("customer.tier",      customerTier);

        // Simulate fraud check
        double fraudScore = RNG.nextDouble();
        span.setAttribute("fraud.score",    fraudScore);
        span.setAttribute("fraud.decision", fraudScore > 0.85 ? "blocked" : "approved");

        if (fraudScore > 0.85) {
            return ResponseEntity.status(402)
                .body(Map.of("error", "blocked_by_fraud", "fraud_score", fraudScore));
        }

        String orderId = "ORD-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase();
        span.setAttribute("order.id", orderId);

        return ResponseEntity.status(201)
            .body(Map.of("order_id", orderId, "status", "confirmed"));
    }
}
