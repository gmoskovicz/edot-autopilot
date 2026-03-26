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

COPY --from=build /build/target/edot-springboot-tier-a-1.0.0.jar app.jar

# The pom.xml uses opentelemetry-spring-boot-starter (library instrumentation).
# No -javaagent needed — the starter handles OTel at compile time, not via agent.
CMD ["java", "-jar", "app.jar"]
