package com.example.orders;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Order Management REST Controller — Spring Boot
 *
 * No observability. Run `Observe this project.` to add OpenTelemetry.
 */
@RestController
@RequestMapping("/")
public class OrderController {

    private final Map<String, Map<String, Object>> orders = new ConcurrentHashMap<>();

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }

    @PostMapping("/orders")
    public ResponseEntity<Map<String, Object>> createOrder(@RequestBody Map<String, Object> body) {
        String customerId   = (String) body.getOrDefault("customer_id", "anon");
        String customerTier = (String) body.getOrDefault("customer_tier", "standard");

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) body.getOrDefault("items", List.of());

        double totalUsd = items.stream()
            .mapToDouble(item -> {
                double price = ((Number) item.getOrDefault("price_usd", 0)).doubleValue();
                int    qty   = ((Number) item.getOrDefault("qty", 1)).intValue();
                return price * qty;
            }).sum();

        if (totalUsd <= 0) {
            return ResponseEntity.badRequest()
                .body(Map.of("error", "order total must be > 0"));
        }

        double fraudScore = computeFraudScore(customerId, totalUsd, customerTier);
        if (fraudScore > 0.7) {
            return ResponseEntity.status(402)
                .body(Map.of("error", "order blocked", "reason", "fraud_check_failed"));
        }

        String orderId  = UUID.randomUUID().toString();
        String chargeId = "ch_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);

        Map<String, Object> order = new HashMap<>();
        order.put("order_id", orderId);
        order.put("customer_id", customerId);
        order.put("customer_tier", customerTier);
        order.put("total_usd", totalUsd);
        order.put("status", "confirmed");
        order.put("fraud_score", fraudScore);
        order.put("charge_id", chargeId);
        orders.put(orderId, order);

        return ResponseEntity.status(201).body(Map.of(
            "order_id",  orderId,
            "status",    "confirmed",
            "total_usd", totalUsd,
            "charge_id", chargeId
        ));
    }

    @GetMapping("/orders/{id}")
    public ResponseEntity<Map<String, Object>> getOrder(@PathVariable String id) {
        Map<String, Object> order = orders.get(id);
        if (order == null) {
            return ResponseEntity.status(404).body(Map.of("error", "not found"));
        }
        return ResponseEntity.ok(order);
    }

    private double computeFraudScore(String customerId, double amountUsd, String tier) {
        double score = Math.random() * 0.4;
        if (amountUsd > 500) score += 0.1;
        if ("enterprise".equals(tier)) score -= 0.15;
        return Math.max(0, Math.min(1, score));
    }
}
