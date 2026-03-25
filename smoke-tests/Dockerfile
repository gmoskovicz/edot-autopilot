# EDOT Autopilot — Smoke Test Runner Image
#
# Pre-installs all Python OTel dependencies so container startup is fast.
# All smoke tests (Tier A Python, Tier B, Tier C, Tier D simulations, cross-tier)
# run from this single image.
#
# Build:
#   docker build -t edot-smoke-runner .
#
# Run directly (mount .env):
#   docker run --rm --env-file ../.env -v $(pwd):/smoke edot-smoke-runner

FROM python:3.12-slim

LABEL org.opencontainers.image.title="EDOT Autopilot Smoke Test Runner"
LABEL org.opencontainers.image.description="Runs all Python-based OTel smoke tests against Elastic Cloud"

# Install Python OTel packages
RUN pip install --no-cache-dir \
    opentelemetry-sdk==1.25.0 \
    opentelemetry-exporter-otlp-proto-http==1.25.0 \
    opentelemetry-semantic-conventions==0.46b0

WORKDIR /smoke

# Copy everything at build time (or mount at runtime via -v)
COPY . /smoke/

# Default: run all tests via runner.sh
CMD ["bash", "runner.sh"]
