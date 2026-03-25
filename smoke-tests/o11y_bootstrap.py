#!/usr/bin/env python3
"""
O11yBootstrap — sets up traces + logs + metrics for any Python smoke test.

Usage:
    from o11y_bootstrap import O11yBootstrap

    o11y = O11yBootstrap("my-service", endpoint, api_key)
    o11y.logger.info("something happened")
    o11y.meter.create_counter("my.counter").add(1)
    with o11y.tracer.start_as_current_span("my.op") as span:
        span.set_attribute("key", "value")
    o11y.flush()
"""

import logging

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# Logs — private but stable in OTel Python SDK 1.x
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

# Metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter


class O11yBootstrap:
    """Bootstrap all three OTel signals (traces, logs, metrics) for a service."""

    def __init__(self, service_name: str, endpoint: str, api_key: str,
                 env: str = "smoke-test", version: str = "smoke"):
        endpoint = endpoint.rstrip("/")
        headers = {"Authorization": f"ApiKey {api_key}"}

        resource = Resource.create({
            "service.name":                service_name,
            "service.version":             version,
            "deployment.environment.name": env,
        })

        # ── Traces ────────────────────────────────────────────────────────
        self._trace_provider = TracerProvider(resource=resource)
        self._trace_provider.add_span_processor(SimpleSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers)
        ))
        trace.set_tracer_provider(self._trace_provider)
        self.tracer = self._trace_provider.get_tracer("io.edot-autopilot", "1.0.0")

        # ── Logs ──────────────────────────────────────────────────────────
        self._log_provider = LoggerProvider(resource=resource)
        self._log_provider.add_log_record_processor(BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", headers=headers)
        ))
        handler = LoggingHandler(logger_provider=self._log_provider)
        handler.setLevel(logging.DEBUG)

        self.logger = logging.getLogger(service_name)
        self.logger.setLevel(logging.DEBUG)
        # Avoid duplicate handlers on re-import
        if not any(isinstance(h, LoggingHandler) for h in self.logger.handlers):
            self.logger.addHandler(handler)
        self.logger.propagate = False

        # ── Metrics ───────────────────────────────────────────────────────
        self._meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", headers=headers),
                export_interval_millis=5_000,
            )],
        )
        metrics.set_meter_provider(self._meter_provider)
        self.meter = self._meter_provider.get_meter("io.edot-autopilot", "1.0.0")

    def flush(self):
        """Force-flush all three providers before process exit."""
        self._trace_provider.force_flush()
        self._log_provider.force_flush()
        self._meter_provider.force_flush()
