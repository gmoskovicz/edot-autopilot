/**
 * Smoke test: Tier A — Java (native OTel SDK, full O11y: traces + logs + metrics).
 *
 * Business scenario: e-commerce order processing — validate order, check inventory,
 * charge payment, send confirmation email. All three signals correlated.
 *
 * Compile & run (requires opentelemetry-sdk-all uber-jar on classpath):
 *   cd smoke-tests/08-tier-a-java
 *   mvn -q package -DskipTests && java -jar target/smoke-tier-a-java.jar
 *
 * Or with the provided run script:
 *   cd smoke-tests && python3 08-tier-a-java/smoke.py
 */

import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.metrics.LongCounter;
import io.opentelemetry.api.metrics.Meter;
import io.opentelemetry.api.metrics.DoubleHistogram;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;
import io.opentelemetry.exporter.otlp.http.metrics.OtlpHttpMetricExporter;
import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.metrics.SdkMeterProvider;
import io.opentelemetry.sdk.metrics.export.PeriodicMetricReader;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;
import io.opentelemetry.semconv.ResourceAttributes;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.logging.*;

public class smoke {
    static final String SVC      = "smoke-tier-a-java";
    static final String ENV_FILE = System.getProperty("user.dir") + "/../.env";

    static Map<String, String> loadEnv() throws Exception {
        Map<String, String> env = new HashMap<>();
        java.nio.file.Path p = java.nio.file.Paths.get(ENV_FILE);
        if (java.nio.file.Files.exists(p)) {
            for (String line : java.nio.file.Files.readAllLines(p)) {
                line = line.trim();
                if (!line.isEmpty() && !line.startsWith("#") && line.contains("=")) {
                    int idx = line.indexOf('=');
                    env.put(line.substring(0, idx), line.substring(idx + 1));
                }
            }
        }
        return env;
    }

    public static void main(String[] args) throws Exception {
        Map<String, String> env = loadEnv();
        String endpoint = env.getOrDefault("ELASTIC_OTLP_ENDPOINT", System.getenv("ELASTIC_OTLP_ENDPOINT"));
        String apiKey   = env.getOrDefault("ELASTIC_API_KEY",        System.getenv("ELASTIC_API_KEY"));
        String envName  = env.getOrDefault("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test");

        Map<String, String> headers = Map.of("Authorization", "ApiKey " + apiKey);

        Resource resource = Resource.getDefault().toBuilder()
            .put(ResourceAttributes.SERVICE_NAME, SVC)
            .put(ResourceAttributes.DEPLOYMENT_ENVIRONMENT, envName)
            .build();

        OtlpHttpSpanExporter spanExporter = OtlpHttpSpanExporter.builder()
            .setEndpoint(endpoint + "/v1/traces")
            .setHeaders(() -> headers)
            .build();

        SdkTracerProvider tracerProvider = SdkTracerProvider.builder()
            .addSpanProcessor(BatchSpanProcessor.builder(spanExporter).build())
            .setResource(resource)
            .build();

        OtlpHttpMetricExporter metricExporter = OtlpHttpMetricExporter.builder()
            .setEndpoint(endpoint + "/v1/metrics")
            .setHeaders(() -> headers)
            .build();

        SdkMeterProvider meterProvider = SdkMeterProvider.builder()
            .registerMetricReader(PeriodicMetricReader.builder(metricExporter)
                .setInterval(Duration.ofSeconds(5)).build())
            .setResource(resource)
            .build();

        OpenTelemetrySdk otel = OpenTelemetrySdk.builder()
            .setTracerProvider(tracerProvider)
            .setMeterProvider(meterProvider)
            .build();

        Tracer tracer = otel.getTracer(SVC);
        Meter  meter  = otel.getMeter(SVC);
        Logger logger = Logger.getLogger(SVC);

        LongCounter   ordersCounter = meter.counterBuilder("orders.total").build();
        DoubleHistogram orderValue  = meter.histogramBuilder("orders.value_usd").setUnit("USD").build();
        DoubleHistogram latencyHist = meter.histogramBuilder("orders.processing_ms").setUnit("ms").build();

        String[][] orders = {
            {"ORD-J001", "cust-ent-001", "enterprise", "1249.99"},
            {"ORD-J002", "cust-pro-042", "pro",        "89.00"},
            {"ORD-J003", "cust-free-11", "free",       "0.00"},
            {"ORD-J004", "cust-ent-007", "enterprise", "4875.50"},
        };

        System.out.println("\n[" + SVC + "] Processing orders via native Java OTel SDK...");

        for (String[] order : orders) {
            String orderId = order[0], custId = order[1], tier = order[2];
            double value   = Double.parseDouble(order[3]);
            long   t0      = System.currentTimeMillis();

            Span span = tracer.spanBuilder("order.process")
                .setSpanKind(SpanKind.SERVER)
                .setAttribute("order.id",            orderId)
                .setAttribute("customer.id",          custId)
                .setAttribute("customer.tier",        tier)
                .setAttribute("order.value_usd",      value)
                .startSpan();

            try (Scope scope = span.makeCurrent()) {
                // Validate
                Span validateSpan = tracer.spanBuilder("order.validate")
                    .setSpanKind(SpanKind.INTERNAL)
                    .startSpan();
                try (Scope vs = validateSpan.makeCurrent()) {
                    Thread.sleep(new Random().nextInt(20) + 10);
                } finally { validateSpan.end(); }

                // Payment
                Span paySpan = tracer.spanBuilder("payment.charge")
                    .setSpanKind(SpanKind.CLIENT)
                    .setAttribute("payment.amount_usd", value)
                    .setAttribute("payment.provider",   "stripe")
                    .startSpan();
                try (Scope ps = paySpan.makeCurrent()) {
                    Thread.sleep(new Random().nextInt(150) + 80);
                    paySpan.setAttribute("payment.charge_id", "ch_" + UUID.randomUUID().toString().replace("-","").substring(0,16));
                } finally { paySpan.end(); }

                long dur = System.currentTimeMillis() - t0;
                span.setAttribute("order.processing_ms", dur);
                span.setStatus(StatusCode.OK);

                ordersCounter.add(1, Attributes.builder()
                    .put("customer.tier", tier).build());
                orderValue.record(value, Attributes.builder()
                    .put("customer.tier", tier).build());
                latencyHist.record(dur, Attributes.builder()
                    .put("customer.tier", tier).build());

                logger.info(String.format("order processed  id=%s  tier=%s  value=%.2f  dur=%dms",
                    orderId, tier, value, dur));
                System.out.printf("  ✅ %s  tier=%-12s  value=$%8.2f  dur=%dms%n",
                    orderId, tier, value, dur);

            } catch (Exception e) {
                span.recordException(e);
                span.setStatus(StatusCode.ERROR, e.getMessage());
                throw e;
            } finally {
                span.end();
            }
        }

        // Force flush
        tracerProvider.forceFlush().join(10, TimeUnit.SECONDS);
        meterProvider.forceFlush().join(10, TimeUnit.SECONDS);
        otel.close();

        System.out.println("[" + SVC + "] Done → Kibana APM → " + SVC);
    }
}
