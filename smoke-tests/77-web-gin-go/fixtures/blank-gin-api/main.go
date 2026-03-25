// Order API — Go + Gin
// No observability. Run `Observe this project.` to add OpenTelemetry.
package main

import (
	"math/rand"
	"net/http"
	"os"
	"github.com/gin-gonic/gin"
	"fmt"
)

type CreateOrderReq struct {
	CustomerID   string                 `json:"customer_id"`
	CustomerTier string                 `json:"customer_tier"`
	Items        []map[string]interface{} `json:"items"`
}

var orders = make(map[string]map[string]interface{})

func main() {
	r := gin.Default()
	r.GET("/health",       func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ok"}) })
	r.POST("/orders",      createOrder)
	r.GET("/orders/:id",   getOrder)
	port := os.Getenv("PORT"); if port == "" { port = "8080" }
	r.Run(":" + port)
}

func createOrder(c *gin.Context) {
	var req CreateOrderReq
	if err := c.ShouldBindJSON(&req); err != nil { c.JSON(400, gin.H{"error": err.Error()}); return }
	total := 0.0
	for _, item := range req.Items {
		price, _ := item["price_usd"].(float64); qty, _ := item["qty"].(float64)
		if qty == 0 { qty = 1 }; total += price * qty
	}
	if total <= 0 { c.JSON(400, gin.H{"error": "total must be > 0"}); return }
	orderID := fmt.Sprintf("ORD-%06d", rand.Intn(999999))
	order := map[string]interface{}{"order_id": orderID, "customer_id": req.CustomerID, "total_usd": total, "status": "confirmed"}
	orders[orderID] = order
	c.JSON(201, order)
}

func getOrder(c *gin.Context) {
	order, ok := orders[c.Param("id")]
	if !ok { c.JSON(404, gin.H{"error": "not found"}); return }
	c.JSON(200, order)
}
