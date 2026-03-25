#!/usr/bin/env python3
"""
Smoke test: Tier D — Julia ML/scientific computing (sidecar simulation).

Simulates a Julia training job submitting observability via the HTTP sidecar.
Business scenario: demand forecasting model training — load historical sales data,
train LSTM time-series model, evaluate on validation set, export ONNX artifact.

Run:
    cd smoke-tests && python3 47-tier-d-julia/smoke.py
"""

import os, sys, time, random, uuid
from pathlib import Path

env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k, v)

sys.path.insert(0, str(Path(__file__).parent.parent))
from o11y_bootstrap import O11yBootstrap
from opentelemetry.trace import SpanKind

SVC = "smoke-tier-d-julia"
o11y   = O11yBootstrap(SVC, os.environ["ELASTIC_OTLP_ENDPOINT"], os.environ["ELASTIC_API_KEY"],
                       os.environ.get("OTEL_DEPLOYMENT_ENVIRONMENT", "smoke-test"))
tracer, logger, meter = o11y.tracer, o11y.logger, o11y.meter

epochs_trained      = meter.create_counter("julia.epochs_trained")
train_loss          = meter.create_histogram("julia.train_loss")
val_mape            = meter.create_histogram("julia.val_mape_pct")
epoch_duration      = meter.create_histogram("julia.epoch_duration_ms", unit="ms")

TRAINING_CONFIG = {
    "run_id":       str(uuid.uuid4())[:8],
    "model":        "LSTM-Demand-v3",
    "dataset":      "sales_history_2020_2025",
    "train_rows":   2_100_000,
    "val_rows":     420_000,
    "epochs":       8,
    "batch_size":   1024,
    "hidden_units": 256,
    "seq_length":   52,
    "learning_rate": 0.001,
}

print(f"\n[{SVC}] Simulating Julia LSTM demand forecasting training run {TRAINING_CONFIG['run_id']}...")

with tracer.start_as_current_span("Julia.train_demand_forecast", kind=SpanKind.INTERNAL,
        attributes={"julia.script": "train_forecast_model.jl",
                    "ml.model":     TRAINING_CONFIG["model"],
                    "ml.dataset":   TRAINING_CONFIG["dataset"],
                    "ml.run_id":    TRAINING_CONFIG["run_id"],
                    "ml.epochs":    TRAINING_CONFIG["epochs"],
                    "ml.batch_size": TRAINING_CONFIG["batch_size"],
                    "ml.learning_rate": TRAINING_CONFIG["learning_rate"]}) as job_span:

    with tracer.start_as_current_span("Julia.load_dataset", kind=SpanKind.INTERNAL,
            attributes={"julia.function": "load_parquet", "ml.train_rows": TRAINING_CONFIG["train_rows"],
                        "ml.val_rows": TRAINING_CONFIG["val_rows"]}):
        time.sleep(random.uniform(0.06, 0.15))
        logger.info("dataset loaded", extra={"ml.dataset": TRAINING_CONFIG["dataset"],
                                              "ml.train_rows": TRAINING_CONFIG["train_rows"],
                                              "ml.val_rows": TRAINING_CONFIG["val_rows"]})

    with tracer.start_as_current_span("Julia.build_model", kind=SpanKind.INTERNAL,
            attributes={"julia.function": "build_lstm_model", "ml.hidden_units": TRAINING_CONFIG["hidden_units"],
                        "ml.seq_length": TRAINING_CONFIG["seq_length"]}):
        time.sleep(0.02)

    best_val_mape = 100.0
    for epoch in range(1, TRAINING_CONFIG["epochs"] + 1):
        t_ep = time.time()
        with tracer.start_as_current_span(f"Julia.train_epoch_{epoch}", kind=SpanKind.INTERNAL,
                attributes={"julia.function": "train_epoch!", "ml.epoch": epoch,
                            "ml.batches": TRAINING_CONFIG["train_rows"] // TRAINING_CONFIG["batch_size"]}) as es:
            time.sleep(random.uniform(0.04, 0.12))
            loss      = 0.35 * (0.7 ** epoch) + random.uniform(-0.01, 0.01)
            val_err   = 12.0 * (0.82 ** epoch) + random.uniform(-0.5, 0.5)
            best_val_mape = min(best_val_mape, val_err)

            ep_dur = (time.time() - t_ep) * 1000
            es.set_attribute("ml.train_loss",  round(loss, 4))
            es.set_attribute("ml.val_mape_pct", round(val_err, 2))
            es.set_attribute("ml.epoch",        epoch)

            epochs_trained.add(1, attributes={"ml.model": TRAINING_CONFIG["model"]})
            train_loss.record(loss, attributes={"ml.epoch": str(epoch)})
            val_mape.record(val_err, attributes={"ml.epoch": str(epoch)})
            epoch_duration.record(ep_dur, attributes={"ml.model": TRAINING_CONFIG["model"]})

            logger.info("epoch complete",
                        extra={"ml.run_id": TRAINING_CONFIG["run_id"], "ml.epoch": epoch,
                               "ml.train_loss": round(loss, 4), "ml.val_mape_pct": round(val_err, 2)})
            print(f"  📊 Epoch {epoch}/{TRAINING_CONFIG['epochs']}  loss={loss:.4f}  val_mape={val_err:.2f}%")

    with tracer.start_as_current_span("Julia.export_onnx", kind=SpanKind.INTERNAL,
            attributes={"julia.function": "ONNX.write",
                        "ml.artifact": f"models/{TRAINING_CONFIG['model']}_{TRAINING_CONFIG['run_id']}.onnx"}):
        time.sleep(random.uniform(0.02, 0.05))

    job_span.set_attribute("ml.best_val_mape_pct", round(best_val_mape, 2))
    job_span.set_attribute("ml.epochs_completed",  TRAINING_CONFIG["epochs"])
    logger.info("training run complete",
                extra={"ml.run_id": TRAINING_CONFIG["run_id"], "ml.model": TRAINING_CONFIG["model"],
                       "ml.best_val_mape_pct": round(best_val_mape, 2),
                       "ml.epochs_completed": TRAINING_CONFIG["epochs"]})

print(f"  ✅ Run {TRAINING_CONFIG['run_id']}  best_val_mape={best_val_mape:.2f}%  model exported")

o11y.flush()
print(f"[{SVC}] Done → Kibana APM → {SVC}")
