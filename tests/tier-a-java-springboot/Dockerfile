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

# Download Elastic EDOT Java agent
ADD https://github.com/elastic/elastic-otel-java/releases/latest/download/elastic-otel-javaagent.jar /app/elastic-otel-javaagent.jar

COPY --from=build /build/target/edot-springboot-tier-a-1.0.0.jar app.jar

# -javaagent injects EDOT auto-instrumentation at JVM startup — zero code changes needed
CMD ["java", \
     "-javaagent:/app/elastic-otel-javaagent.jar", \
     "-jar", "app.jar"]
