# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jdk-jammy AS build

WORKDIR /build
COPY pom.xml .
COPY src src/

RUN apt-get update -qq && apt-get install -y -qq maven > /dev/null 2>&1 && \
    mvn package -q -DskipTests

# ── Stage 2: run ──────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jre-jammy

WORKDIR /app

# Download upstream OTel Java agent (EDOT agent is on Maven Central, not GitHub releases)
RUN curl -fsSL -o /app/opentelemetry-javaagent.jar \
    https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/latest/download/opentelemetry-javaagent.jar

COPY --from=build /build/target/edot-springboot-tier-a-1.0.0.jar app.jar

# -javaagent injects EDOT auto-instrumentation at JVM startup — zero code changes needed
CMD ["java", \
     "-javaagent:/app/opentelemetry-javaagent.jar", \
     "-jar", "app.jar"]
