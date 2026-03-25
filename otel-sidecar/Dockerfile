FROM python:3.12-slim

RUN pip install --no-cache-dir \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp-proto-http

COPY otel-sidecar.py /otel-sidecar.py

# Non-root user for security
RUN useradd -r -s /bin/false sidecar
USER sidecar

EXPOSE 9411

CMD ["python", "/otel-sidecar.py"]
