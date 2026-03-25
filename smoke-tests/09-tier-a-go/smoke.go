// Smoke test: Tier A — Go (native OTel SDK, full O11y: traces + logs + metrics).
//
// Business scenario: API gateway request routing — authenticate JWT, look up
// route, forward to upstream, record latency.
//
// Run (requires go 1.21+):
//   cd smoke-tests/09-tier-a-go && go run smoke.go
//
// Or via the Python runner:
//   cd smoke-tests && python3 09-tier-a-go/smoke.py

package main

import (
	"bufio"
	"context"
	"fmt"
	"log"
	"math/rand"
	"os"
	"strings"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.21.0"
	"go.opentelemetry.io/otel/trace"
)

const svcName = "smoke-tier-a-go"

func loadEnv() {
	f, err := os.Open("../.env")
	if err != nil {
		return
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		os.Setenv(parts[0], parts[1])
	}
}

func main() {
	loadEnv()
	endpoint := os.Getenv("ELASTIC_OTLP_ENDPOINT")
	apiKey   := os.Getenv("ELASTIC_API_KEY")
	envName  := os.Getenv("OTEL_DEPLOYMENT_ENVIRONMENT")
	if envName == "" { envName = "smoke-test" }

	ctx := context.Background()
	headers := map[string]string{"Authorization": "ApiKey " + apiKey}

	res, _ := resource.Merge(resource.Default(), resource.NewWithAttributes(
		semconv.SchemaURL,
		semconv.ServiceName(svcName),
		attribute.String("deployment.environment", envName),
	))

	traceExporter, _ := otlptracehttp.New(ctx,
		otlptracehttp.WithEndpointURL(endpoint+"/v1/traces"),
		otlptracehttp.WithHeaders(headers),
		otlptracehttp.WithInsecure(),
	)
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(traceExporter),
		sdktrace.WithResource(res),
	)
	defer tp.Shutdown(ctx)
	otel.SetTracerProvider(tp)

	metricExporter, _ := otlpmetrichttp.New(ctx,
		otlpmetrichttp.WithEndpointURL(endpoint+"/v1/metrics"),
		otlpmetrichttp.WithHeaders(headers),
		otlpmetrichttp.WithInsecure(),
	)
	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(metricExporter,
			sdkmetric.WithInterval(5*time.Second))),
		sdkmetric.WithResource(res),
	)
	defer mp.ForceFlush(ctx)
	defer mp.Shutdown(ctx)

	tracer := tp.Tracer(svcName)
	meter  := mp.Meter(svcName)

	reqCounter, _ := meter.Int64Counter("gateway.requests_total")
	latencyHist, _ := meter.Float64Histogram("gateway.upstream_latency_ms",
		metric.WithUnit("ms"))
	authFailures, _ := meter.Int64Counter("gateway.auth_failures")

	type Request struct {
		method, path, upstreamSvc, tier, authHeader string
	}
	requests := []Request{
		{"GET",  "/api/v2/products",  "product-catalog",   "public",      "Bearer eyJhbGci..."},
		{"POST", "/api/v2/orders",    "order-service",     "enterprise",  "Bearer eyJhbGci..."},
		{"GET",  "/api/v2/inventory", "inventory-service", "internal",    "Bearer eyJhbGci..."},
		{"POST", "/api/v2/payments",  "payment-service",   "enterprise",  "Bearer eyJhbGci..."},
		{"GET",  "/api/v2/reports",   "analytics-service", "pro",         "Bearer eyJhbGci..."},
	}

	fmt.Printf("\n[%s] Routing API requests via native Go OTel SDK...\n", svcName)

	for _, req := range requests {
		t0 := time.Now()
		ctx, span := tracer.Start(ctx, "gateway.route_request",
			trace.WithSpanKind(trace.SpanKindServer),
			trace.WithAttributes(
				attribute.String("http.method",   req.method),
				attribute.String("http.route",    req.path),
				attribute.String("net.peer.name", req.upstreamSvc),
				attribute.String("customer.tier", req.tier),
			),
		)

		// Auth
		_, authSpan := tracer.Start(ctx, "gateway.authenticate_jwt",
			trace.WithSpanKind(trace.SpanKindInternal))
		time.Sleep(time.Duration(rand.Intn(10)+5) * time.Millisecond)
		authSpan.SetAttributes(attribute.Bool("auth.valid", true))
		authSpan.End()

		// Upstream
		_, upSpan := tracer.Start(ctx, "gateway.forward_upstream",
			trace.WithSpanKind(trace.SpanKindClient),
			trace.WithAttributes(
				attribute.String("http.url",    "https://"+req.upstreamSvc+".internal"+req.path),
				attribute.String("peer.service", req.upstreamSvc),
			),
		)
		upstreamMs := rand.Float64()*80 + 20
		time.Sleep(time.Duration(upstreamMs) * time.Millisecond)
		statusCode := 200
		upSpan.SetAttributes(attribute.Int("http.status_code", statusCode))
		upSpan.SetStatus(codes.Ok, "")
		upSpan.End()

		dur := float64(time.Since(t0).Milliseconds())
		span.SetAttributes(
			attribute.Float64("gateway.total_latency_ms", dur),
			attribute.Int("http.status_code", statusCode),
		)
		span.SetStatus(codes.Ok, "")
		span.End()

		attrs := attribute.NewSet(
			attribute.String("http.method", req.method),
			attribute.String("customer.tier", req.tier),
		)
		reqCounter.Add(ctx, 1, metric.WithAttributeSet(attrs))
		latencyHist.Record(ctx, dur, metric.WithAttributeSet(attrs))

		log.Printf("request routed  method=%s path=%s upstream=%s dur=%.0fms",
			req.method, req.path, req.upstreamSvc, dur)
		fmt.Printf("  ✅ %s %-25s → %-22s %dms\n",
			req.method, req.path, req.upstreamSvc, int(dur))

		_ = authFailures
	}

	tp.ForceFlush(ctx)
	mp.ForceFlush(ctx)
	fmt.Printf("[%s] Done → Kibana APM → %s\n", svcName, svcName)
}
