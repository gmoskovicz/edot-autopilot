#!/usr/bin/env python3
"""
Smoke test: Tier D — Fortran HPC job (sidecar simulation).

Simulates a Fortran scientific computing job submitting observability via the
HTTP sidecar. Business scenario: climate simulation — run atmospheric model
iterations for a 72-hour forecast window, compute temperature/pressure fields,
write NetCDF output.

Run:
    cd smoke-tests && python3 44-tier-d-fortran/smoke.py
"""

import os, sys, time, random
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind

SVC = "smoke-tier-d-fortran"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

timesteps_computed = meter.create_counter("fortran.timesteps_computed")
mpi_messages       = meter.create_counter("fortran.mpi_messages")
model_walltime     = meter.create_histogram("fortran.model_walltime_ms", unit="ms")
flops_rate         = meter.create_histogram("fortran.gflops")

SIMULATION_CONFIG = {
    "model":        "WRF-4.5",
    "domain":       "CONUS-3km",
    "grid_points":  1_500_000,
    "mpi_ranks":    64,
    "timestep_sec": 18,
    "forecast_h":   72,
}

PHYSICS_MODULES = [
    {"name": "microphysics",     "scheme": "Thompson",    "cost_factor": 1.4},
    {"name": "boundary_layer",   "scheme": "YSU",         "cost_factor": 0.8},
    {"name": "surface_layer",    "scheme": "MM5",         "cost_factor": 0.5},
    {"name": "radiation_sw",     "scheme": "RRTMG",       "cost_factor": 1.8},
    {"name": "radiation_lw",     "scheme": "RRTMG",       "cost_factor": 1.6},
    {"name": "cumulus",          "scheme": "Kain-Fritsch", "cost_factor": 1.2},
]

total_timesteps = int(SIMULATION_CONFIG["forecast_h"] * 3600 / SIMULATION_CONFIG["timestep_sec"])

print(f"\n[{SVC}] Simulating Fortran WRF atmospheric model run ({total_timesteps} timesteps)...")

with tracer.start_as_current_span("FORTRAN.wrf_model_run", kind=SpanKind.INTERNAL,
        attributes={"fortran.program": "wrf.exe", "hpc.model": SIMULATION_CONFIG["model"],
                    "hpc.domain": SIMULATION_CONFIG["domain"],
                    "hpc.mpi_ranks": SIMULATION_CONFIG["mpi_ranks"],
                    "hpc.grid_points": SIMULATION_CONFIG["grid_points"],
                    "hpc.forecast_hours": SIMULATION_CONFIG["forecast_h"],
                    "hpc.total_timesteps": total_timesteps}) as job_span:
    t_job = time.time()

    with tracer.start_as_current_span("FORTRAN.init_domain", kind=SpanKind.INTERNAL,
            attributes={"fortran.subroutine": "domain_init",
                        "hpc.grid_points": SIMULATION_CONFIG["grid_points"]}):
        time.sleep(random.uniform(0.03, 0.08))
        logger.info("domain initialized",
                    extra={"hpc.model": SIMULATION_CONFIG["model"],
                           "hpc.domain": SIMULATION_CONFIG["domain"],
                           "hpc.grid_points": SIMULATION_CONFIG["grid_points"]})

    with tracer.start_as_current_span("FORTRAN.read_ic_files", kind=SpanKind.INTERNAL,
            attributes={"fortran.subroutine": "read_wrfinput",
                        "hpc.ic_file": "wrfinput_d01", "hpc.io_format": "NetCDF"}):
        time.sleep(random.uniform(0.04, 0.10))

    # Simulate 6-hour forecast chunks (faster than all 14400 timesteps)
    for chunk_h in range(0, SIMULATION_CONFIG["forecast_h"], 6):
        chunk_steps = int(6 * 3600 / SIMULATION_CONFIG["timestep_sec"])
        with tracer.start_as_current_span("FORTRAN.time_integration_chunk", kind=SpanKind.INTERNAL,
                attributes={"fortran.subroutine": "integrate", "hpc.forecast_hour_start": chunk_h,
                            "hpc.chunk_timesteps": chunk_steps}) as cs:
            t_chunk = time.time()
            time.sleep(random.uniform(0.02, 0.06))

            for module in PHYSICS_MODULES[:3]:  # sample subset
                with tracer.start_as_current_span(f"FORTRAN.{module['name']}", kind=SpanKind.INTERNAL,
                        attributes={"fortran.module": module["name"], "fortran.scheme": module["scheme"]}):
                    time.sleep(random.uniform(0.003, 0.008) * module["cost_factor"])

            with tracer.start_as_current_span("FORTRAN.mpi_halo_exchange", kind=SpanKind.INTERNAL,
                    attributes={"mpi.operation": "MPI_Sendrecv", "mpi.ranks": SIMULATION_CONFIG["mpi_ranks"]}):
                time.sleep(random.uniform(0.005, 0.015))
                mpi_messages.add(SIMULATION_CONFIG["mpi_ranks"] * 6,
                                 attributes={"mpi.operation": "halo_exchange"})

            gflops = random.uniform(12, 28) * SIMULATION_CONFIG["mpi_ranks"] / 64
            chunk_dur = (time.time() - t_chunk) * 1000
            cs.set_attribute("hpc.gflops", round(gflops, 2))
            timesteps_computed.add(chunk_steps, attributes={"hpc.chunk_start_h": chunk_h})
            flops_rate.record(gflops, attributes={"fortran.subroutine": "integrate"})

    with tracer.start_as_current_span("FORTRAN.write_history_files", kind=SpanKind.INTERNAL,
            attributes={"fortran.subroutine": "write_history", "hpc.io_format": "NetCDF4",
                        "hpc.output_files": SIMULATION_CONFIG["forecast_h"] // 3}):
        time.sleep(random.uniform(0.04, 0.10))

    total_dur = (time.time() - t_job) * 1000
    job_span.set_attribute("hpc.walltime_ms", round(total_dur, 2))
    job_span.set_attribute("hpc.timesteps_completed", total_timesteps)
    model_walltime.record(total_dur, attributes={"hpc.model": SIMULATION_CONFIG["model"]})

    logger.info("WRF model run complete",
                extra={"hpc.model": SIMULATION_CONFIG["model"], "hpc.domain": SIMULATION_CONFIG["domain"],
                       "hpc.forecast_hours": SIMULATION_CONFIG["forecast_h"],
                       "hpc.timesteps_completed": total_timesteps,
                       "hpc.walltime_ms": round(total_dur, 2)})

    print(f"  ✅ {SIMULATION_CONFIG['model']}  domain={SIMULATION_CONFIG['domain']}  "
          f"forecast={SIMULATION_CONFIG['forecast_h']}h  timesteps={total_timesteps:,}  "
          f"walltime={total_dur:.0f}ms (sim)")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
