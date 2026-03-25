#!/usr/bin/env python3
"""
================================================================
FILE:        dcgm_collector.py
DESCRIPTION: NVIDIA DCGM Exporter + OTel Collector integration
             Polls DCGM metrics via pydcgm library, exposes them
             as Prometheus metrics (:9400/metrics), and also
             forwards them to the OTel Collector via OTLP/HTTP.

REAL PIPELINE:
  DCGM Exporter (:9400/metrics)
      | Prometheus scrape
  OTel Collector (prometheus receiver)
      | OTLP/HTTP
  Elastic APM + Metrics

DCGM FIELDS COLLECTED (from default-counters.csv):
  DCGM_FI_DEV_GPU_UTIL          - GPU utilization (%)
  DCGM_FI_DEV_MEM_COPY_UTIL     - Memory bandwidth utilization (%)
  DCGM_FI_DEV_FB_USED           - Framebuffer used (MiB)
  DCGM_FI_DEV_FB_FREE           - Framebuffer free (MiB)
  DCGM_FI_DEV_GPU_TEMP          - GPU temperature (°C)
  DCGM_FI_DEV_POWER_USAGE       - Board power draw (W)
  DCGM_FI_DEV_SM_CLOCK          - SM clock (MHz)
  DCGM_FI_DEV_MEM_CLOCK         - Memory clock (MHz)
  DCGM_FI_PROF_PIPE_TENSOR_ACTIVE  - Tensor core utilization (0-1)
  DCGM_FI_PROF_DRAM_ACTIVE         - DRAM active fraction (0-1)
  DCGM_FI_PROF_PCIE_TX_BYTES       - PCIe TX bytes/sec
  DCGM_FI_PROF_PCIE_RX_BYTES       - PCIe RX bytes/sec
  DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL - NVLink aggregate bandwidth (GB/s)
  DCGM_FI_DEV_XID_ERRORS         - NVIDIA Xid error events

References:
  https://github.com/NVIDIA/dcgm-exporter
  https://opentelemetry.io/docs/specs/semconv/hardware/gpu/
  https://docs.nvidia.com/datacenter/dcgm/latest/dcgm-api/dcgm-api-field-ids.html

RUNTIME:     Python 3.11, pydcgm, prometheus_client
SCHEDULE:    Continuous daemon, --collection-interval=1s
================================================================
"""

import os
import sys
import time
import logging
import argparse
from dataclasses import dataclass
from typing import List, Optional

# In production: import pydcgm; requires DCGM library on NVIDIA driver node
# import pydcgm
# import dcgm_fields

logger = logging.getLogger("dcgm-collector")

# ---- Configuration ------------------------------------------
COLLECTION_INTERVAL = int(os.getenv("DCGM_COLLECTION_INTERVAL", "1"))
METRICS_PORT        = int(os.getenv("DCGM_METRICS_PORT", "9400"))
OTLP_ENDPOINT       = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
SERVICE_NAME        = os.getenv("OTEL_SERVICE_NAME", "dcgm-exporter")
LOG_LEVEL           = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@dataclass
class GPUMetrics:
    """Snapshot of DCGM metrics for one GPU."""
    gpu_index:        int
    gpu_uuid:         str
    gpu_name:         str
    # Core metrics
    gpu_util_pct:     float    # DCGM_FI_DEV_GPU_UTIL
    mem_util_pct:     float    # DCGM_FI_DEV_MEM_COPY_UTIL
    fb_used_mib:      float    # DCGM_FI_DEV_FB_USED
    fb_free_mib:      float    # DCGM_FI_DEV_FB_FREE
    temp_celsius:     int      # DCGM_FI_DEV_GPU_TEMP
    power_watts:      float    # DCGM_FI_DEV_POWER_USAGE
    sm_clock_mhz:     int      # DCGM_FI_DEV_SM_CLOCK
    mem_clock_mhz:    int      # DCGM_FI_DEV_MEM_CLOCK
    # Profiling counters
    tensor_active:    float    # DCGM_FI_PROF_PIPE_TENSOR_ACTIVE
    dram_active:      float    # DCGM_FI_PROF_DRAM_ACTIVE
    pcie_tx_bytes:    int      # DCGM_FI_PROF_PCIE_TX_BYTES
    pcie_rx_bytes:    int      # DCGM_FI_PROF_PCIE_RX_BYTES
    nvlink_bw_gbps:   float    # DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL
    xid_errors:       int      # DCGM_FI_DEV_XID_ERRORS


class DCGMCollector:
    """Wraps pydcgm handle and collects metrics per GPU."""

    def __init__(self, gpu_ids: Optional[List[int]] = None):
        self.gpu_ids = gpu_ids or []
        self._handle = None
        self._field_group = None
        self._init_dcgm()

    def _init_dcgm(self):
        """Initialize DCGM handle and field watches."""
        logger.info("Initializing DCGM handle")
        # In production:
        #   self._handle = pydcgm.DcgmHandle(None)  # embedded mode
        #   self._group   = pydcgm.DcgmGroup(self._handle, groupName="all_gpus",
        #                                     groupType=dcgm_structs.DCGM_GROUP_ALL_GPUS)
        #   field_ids = [dcgm_fields.DCGM_FI_DEV_GPU_UTIL, ...]
        #   self._field_group = pydcgm.DcgmFieldGroup(self._handle, "dcgm_fields", field_ids)
        #   self._group.samples.WatchFields(self._field_group, updateFreq=1_000_000,
        #                                   maxKeepAge=60.0, maxKeepSamples=10)
        logger.info("DCGM handle initialized (stub — no GPU hardware required)")

    def collect(self) -> List[GPUMetrics]:
        """Poll DCGM and return metric snapshots for all GPUs."""
        # In production: self._group.samples.GetAllSinceLastCall(self._field_group)
        # Stub returns empty list — agent will add real implementation
        return []

    def close(self):
        if self._handle:
            # self._handle.Cleanup()
            pass


class PrometheusExporter:
    """Expose collected metrics as Prometheus text format on :9400/metrics."""

    def __init__(self, port: int = 9400):
        self.port = port
        # In production: from prometheus_client import start_http_server, Gauge
        # start_http_server(port)
        logger.info(f"Prometheus metrics endpoint: :{port}/metrics")

    def update(self, snapshots: List[GPUMetrics]):
        for snap in snapshots:
            labels = {
                "gpu": str(snap.gpu_index),
                "uuid": snap.gpu_uuid,
                "modelName": snap.gpu_name,
            }
            # In production: update Gauge/Counter objects with snap values
            logger.debug(
                f"gpu={snap.gpu_index} util={snap.gpu_util_pct:.1f}% "
                f"temp={snap.temp_celsius}C power={snap.power_watts:.0f}W "
                f"xid={snap.xid_errors}"
            )


def run_collection_loop(collector: DCGMCollector,
                        exporter: PrometheusExporter,
                        interval: int = 1):
    """Main polling loop — runs every `interval` seconds."""
    logger.info(f"Starting DCGM collection loop (interval={interval}s)")
    cycle = 0
    while True:
        cycle += 1
        t0 = time.time()

        try:
            snapshots = collector.collect()
            exporter.update(snapshots)

            if snapshots:
                avg_util = sum(s.gpu_util_pct for s in snapshots) / len(snapshots)
                total_pw = sum(s.power_watts  for s in snapshots)
                xid_any  = any(s.xid_errors > 0 for s in snapshots)
                level    = logging.WARNING if xid_any else logging.INFO
                logger.log(level,
                    f"cycle={cycle} gpus={len(snapshots)} "
                    f"avg_util={avg_util:.1f}% total_power={total_pw:.0f}W "
                    f"xid_errors={'YES' if xid_any else 'no'}"
                )
        except Exception as exc:
            logger.error(f"Collection error cycle={cycle}: {exc}")

        elapsed = time.time() - t0
        sleep_s = max(0, interval - elapsed)
        time.sleep(sleep_s)


def main():
    parser = argparse.ArgumentParser(description="DCGM Exporter + OTel forwarder")
    parser.add_argument("--collection-interval", type=int,
                        default=COLLECTION_INTERVAL,
                        help="Metrics collection interval in seconds")
    parser.add_argument("--metrics-port", type=int,
                        default=METRICS_PORT,
                        help="Prometheus metrics port")
    parser.add_argument("--gpu-ids", type=str, default="",
                        help="Comma-separated GPU indices (empty = all)")
    args = parser.parse_args()

    gpu_ids = [int(x) for x in args.gpu_ids.split(",") if x.strip()] \
              if args.gpu_ids else []

    logger.info(f"DCGM Collector starting | service={SERVICE_NAME}")
    logger.info(f"Interval={args.collection_interval}s  Port={args.metrics_port}")
    if gpu_ids:
        logger.info(f"GPU filter: {gpu_ids}")
    else:
        logger.info("Monitoring all GPUs")

    collector = DCGMCollector(gpu_ids=gpu_ids)
    exporter  = PrometheusExporter(port=args.metrics_port)

    try:
        run_collection_loop(collector, exporter, args.collection_interval)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        collector.close()


if __name__ == "__main__":
    main()
