# Citations and References

This project builds on the following specifications, documentation, and open-source projects.

---

## 1. Elastic EDOT Documentation

**URL:** https://www.elastic.co/docs/reference/opentelemetry

The official documentation for Elastic Distributions of OpenTelemetry (EDOT). Provides the SDK packaging, auto-instrumentation agents, and exporter configuration used for Tier A and Tier B instrumentation in this project. The `-javaagent`, `edot-bootstrap`, and `require()` patterns referenced in Phase 2 follow EDOT's documented setup procedures.

---

## 2. OpenTelemetry Specification

**URL:** https://opentelemetry.io/docs/specs/otel/

The CNCF specification that defines the trace, metric, and log data model, API semantics, context propagation contracts, and SDK requirements. All span structures, attribute naming conventions, and propagator behavior in this project implement this specification.

---

## 3. CNCF OpenTelemetry Project

**URL:** https://opentelemetry.io

The CNCF project hosting the OpenTelemetry standard and SDKs for 11+ languages. The auto-instrumentation libraries referenced in Phase 2 (Tier A) — for Java, Python, Node.js, .NET, and PHP — are maintained under this project.

---

## 4. OpenTelemetry Hardware Metrics Semantic Conventions

**URL:** https://opentelemetry.io/docs/specs/semconv/hardware/gpu/

The `hw.gpu.*` semantic conventions used for CUDA and GPU observability in Tier C smoke tests. Defines the standard attribute names for GPU utilization, memory usage, temperature, and power draw that appear in the GPU-related tests in this repository.

---

## 5. Elastic Agent Skills

**URL:** https://github.com/elastic/agent-skills

The `slo-management` and related skills referenced in Phase 4 of `CLAUDE.md` for creating SLOs via the Kibana API. This project invokes those skills to generate SLO definitions grounded in the timeout and retry values discovered during codebase reconnaissance.

---

## 6. OTLP Specification

**URL:** https://opentelemetry.io/docs/specs/otlp/

The OpenTelemetry Protocol wire specification. The otel-sidecar (`otel-sidecar.py`) uses OTLP/HTTP to export spans directly to Elastic without an intermediate collector. The `/v1/traces` endpoint and protobuf encoding are defined by this specification.

---

## 7. OpenTelemetry Python SDK

**URL:** https://opentelemetry-python.readthedocs.io/

The Python SDK used in the otel-sidecar (`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`) and in all Python-based smoke tests. The `TracerProvider`, `BatchSpanProcessor`, `OTLPSpanExporter`, and `TraceContextTextMapPropagator` classes are part of this SDK.

---

## 8. NVIDIA DCGM Exporter

**URL:** https://github.com/NVIDIA/dcgm-exporter

Referenced in smoke test 52 (Tier D DCGM simulation) for multi-GPU training observability. The DCGM Exporter provides GPU metrics via Prometheus; the smoke test demonstrates how to bridge those metrics into OTel spans via the sidecar for workloads where the DCGM Exporter cannot be replaced.

---

## 9. llms.txt Standard

**URL:** https://llmstxt.org

The emerging convention this project follows (via the `llms.txt` file at the repository root) to help AI systems understand the project's purpose, structure, and key files when used as context. The `llms.txt` file provides a concise, AI-readable summary of EDOT Autopilot for consumption by language models and agentic tools.

---

## 10. OpenTelemetry Semantic Conventions

**URL:** https://opentelemetry.io/docs/specs/semconv/

The standard attribute names used throughout this project for HTTP spans (`http.method`, `http.route`, `http.status_code`), database spans, messaging spans, and hardware spans. Business-specific attributes (e.g., `order.value_usd`, `customer.tier`) follow the naming style of these conventions while extending them with domain context.
