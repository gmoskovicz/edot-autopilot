// API Gateway — Go + net/http
//
// No observability. Run `Observe this project.` to add OpenTelemetry.
//
// Routes:
//   GET  /health                   — liveness probe
//   GET  /api/v1/products          — list products (proxies catalog-svc)
//   POST /api/v1/orders            — create order (proxies order-svc)
//   GET  /api/v1/inventory/{sku}   — check stock (proxies inventory-svc)
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"strings"
	"time"
)

// ── Upstream service stubs ────────────────────────────────────────────────────

type Order struct {
	OrderID      string  `json:"order_id"`
	CustomerID   string  `json:"customer_id"`
	CustomerTier string  `json:"customer_tier"`
	TotalUSD     float64 `json:"total_usd"`
	Status       string  `json:"status"`
}

var orders = make(map[string]Order)

func callUpstream(service, path string, latencyMs int) error {
	// Simulate upstream call latency
	time.Sleep(time.Duration(latencyMs) * time.Millisecond)
	// 5% error rate on non-internal services
	if rand.Float64() < 0.05 && service != "internal" {
		return fmt.Errorf("upstream %s: connection timeout", service)
	}
	return nil
}

// ── Handlers ─────────────────────────────────────────────────────────────────

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func productsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	if err := callUpstream("catalog-svc", "/products", 20+rand.Intn(30)); err != nil {
		log.Printf("upstream error: %v", err)
		http.Error(w, "upstream error", http.StatusBadGateway)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode([]map[string]interface{}{
		{"sku": "LAPTOP-PRO", "name": "Laptop Pro 14", "price_usd": 1999.00, "in_stock": true},
		{"sku": "HEADPHONE",  "name": "Noise-Cancel Headphones", "price_usd": 299.99, "in_stock": true},
		{"sku": "KEYBOARD",   "name": "Mech Keyboard", "price_usd": 129.99, "in_stock": false},
	})
}

func ordersHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var body map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}

	customerID, _ := body["customer_id"].(string)
	if customerID == "" {
		customerID = "anon"
	}
	customerTier, _ := body["customer_tier"].(string)
	if customerTier == "" {
		customerTier = "standard"
	}

	var totalUSD float64
	if items, ok := body["items"].([]interface{}); ok {
		for _, item := range items {
			if m, ok := item.(map[string]interface{}); ok {
				price, _ := m["price_usd"].(float64)
				qty, _ := m["qty"].(float64)
				if qty == 0 {
					qty = 1
				}
				totalUSD += price * qty
			}
		}
	}

	if totalUSD <= 0 {
		http.Error(w, `{"error":"order total must be > 0"}`, http.StatusBadRequest)
		return
	}

	// Fraud check
	fraudScore := rand.Float64() * 0.5
	if totalUSD > 500 {
		fraudScore += 0.1
	}
	if strings.ToLower(customerTier) == "enterprise" {
		fraudScore -= 0.15
	}
	if fraudScore > 0.7 {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusPaymentRequired)
		json.NewEncoder(w).Encode(map[string]string{
			"error": "order blocked", "reason": "fraud_check_failed",
		})
		return
	}

	if err := callUpstream("order-svc", "/orders", 50+rand.Intn(100)); err != nil {
		http.Error(w, "upstream error", http.StatusBadGateway)
		return
	}

	orderID := fmt.Sprintf("ORD-%06d", rand.Intn(999999))
	orders[orderID] = Order{
		OrderID:      orderID,
		CustomerID:   customerID,
		CustomerTier: customerTier,
		TotalUSD:     totalUSD,
		Status:       "confirmed",
	}

	log.Printf("Order created: %s customer=%s total=$%.2f", orderID, customerID, totalUSD)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"order_id":  orderID,
		"status":    "confirmed",
		"total_usd": totalUSD,
	})
}

func inventoryHandler(w http.ResponseWriter, r *http.Request) {
	parts := strings.Split(r.URL.Path, "/")
	sku := ""
	if len(parts) > 0 {
		sku = parts[len(parts)-1]
	}

	if err := callUpstream("inventory-svc", "/inventory/"+sku, 10+rand.Intn(20)); err != nil {
		http.Error(w, "upstream error", http.StatusBadGateway)
		return
	}

	inStock := rand.Float64() > 0.2
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"sku":      sku,
		"in_stock": inStock,
		"quantity": rand.Intn(200),
	})
}

// ── Main ──────────────────────────────────────────────────────────────────────

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/api/v1/products", productsHandler)
	mux.HandleFunc("/api/v1/orders", ordersHandler)
	mux.HandleFunc("/api/v1/inventory/", inventoryHandler)

	log.Printf("API Gateway listening on :%s", port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
