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
import os
import platform
import socket
import uuid

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased, ParentBased
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
                 env: str = "smoke-test", version: str = "smoke",
                 sampler=None, extra_resource_attrs: dict = None):
        endpoint = endpoint.rstrip("/")
        headers = {"Authorization": f"ApiKey {api_key}"}

        base_attrs = {
            "service.name":                service_name,
            "service.version":             version,
            "deployment.environment":      env,   # Elastic APM / older OTel semconv
            "deployment.environment.name": env,   # OTel semconv 1.24+
            "service.instance.id":         str(uuid.uuid4()),
            "host.name":                   socket.gethostname(),
            "process.pid":                 os.getpid(),
            "os.name":                     platform.system(),
            "telemetry.sdk.name":          "edot-autopilot",
            "telemetry.sdk.language":      "python",
        }
        if extra_resource_attrs:
            base_attrs.update(extra_resource_attrs)
        resource = Resource.create(base_attrs)

        # ── Traces ────────────────────────────────────────────────────────
        tracer_kwargs = {"resource": resource}
        if sampler is not None:
            tracer_kwargs["sampler"] = sampler
        self._trace_provider = TracerProvider(**tracer_kwargs)
        self._trace_provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers),
            max_export_batch_size=64,
            schedule_delay_millis=1_000,
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
                export_interval_millis=30_000,   # 30s — prevents rate-limit 401s when
                export_timeout_millis=10_000,    # many services run in the same process
            )],
        )
        metrics.set_meter_provider(self._meter_provider)
        self.meter = self._meter_provider.get_meter("io.edot-autopilot", "1.0.0")

    def flush(self):
        """Force-flush all three providers before process exit."""
        self._trace_provider.force_flush()
        self._log_provider.force_flush()
        self._meter_provider.force_flush()
