# Tier A — Java Spring Boot (Native EDOT)

Tests EDOT Java agent (`-javaagent`) zero-config instrumentation for Spring Boot.

**What the EDOT Java agent auto-instruments:**
- Spring MVC / Spring WebFlux routes
- JDBC / JPA queries
- Outbound HTTP (RestTemplate, WebClient, OkHttp)
- gRPC, Kafka, RabbitMQ (if present)

**No code changes required** — the agent attaches at JVM startup via `-javaagent`.

## Build & Run

```bash
# Build
mvn package -DskipTests

# Run with Docker Compose
cp ../.env.example .env
docker compose up

# Test
curl -X POST http://localhost:8080/orders \
  -H "Content-Type: application/json" \
  -d '{"customerId":"CUST-001","orderValue":4200,"customerTier":"enterprise"}'
```

## Manual run (without Docker)

```bash
export OTEL_SERVICE_NAME=edot-springboot-tier-a
export OTEL_EXPORTER_OTLP_ENDPOINT=https://YOUR-DEPLOYMENT.ingest.REGION.gcp.elastic.cloud:443
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=ApiKey YOUR_KEY"

# Download agent
curl -L -o elastic-otel-javaagent.jar \
  https://github.com/elastic/elastic-otel-java/releases/latest/download/elastic-otel-javaagent.jar

java -javaagent:elastic-otel-javaagent.jar -jar target/edot-springboot-tier-a-1.0.0.jar
```

## Verify in Elastic

Kibana → Observability → APM → Services → `edot-springboot-tier-a`
