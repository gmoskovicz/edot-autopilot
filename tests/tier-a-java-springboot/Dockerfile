FROM eclipse-temurin:21-jre-jammy

WORKDIR /app

# Download Elastic EDOT Java agent
ADD https://github.com/elastic/elastic-otel-java/releases/latest/download/elastic-otel-javaagent.jar /app/elastic-otel-javaagent.jar

COPY target/edot-springboot-tier-a-1.0.0.jar app.jar

# -javaagent injects EDOT auto-instrumentation at JVM startup — zero code changes needed
CMD ["java", \
     "-javaagent:/app/elastic-otel-javaagent.jar", \
     "-jar", "app.jar"]
