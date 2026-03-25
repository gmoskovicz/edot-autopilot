# blank-julia — LSTM Demand Forecasting Training (Julia)

## What this script does

`train_forecast_model.jl` is a Julia 1.10 script that trains an LSTM
time-series model for demand forecasting:

1. **load_parquet** — loads historical sales data (2020–2025, 2.1M training
   rows and 420K validation rows) from Parquet files using `DataFrames.jl`
   and `Parquet.jl`
2. **build_lstm_model** — constructs a two-layer LSTM model with Flux.jl:
   input (8 features) → LSTM(256) → LSTM(128) → Dense(1), followed by
   Adam optimizer setup
3. **train_epoch!** — runs one training epoch over mini-batches (batch size
   1024), calling `Flux.withgradient` for backprop and `Flux.update!` for
   parameter updates; resets LSTM hidden state per batch
4. **evaluate_model** — computes MAPE (Mean Absolute Percentage Error) on the
   validation set after each epoch
5. **ONNX.write** — exports the best model as an ONNX artifact to
   `models/LSTM-Demand-v3_<run_id>.onnx`

Training configuration: 8 epochs, learning rate 1e-3, sequence length 52
weeks, 256 hidden units.

## Why it has no observability

This is a **Tier D** legacy application. Julia has no supported OpenTelemetry
SDK (no `opentelemetry-julia` package exists in the General registry).

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`@printf` output to stdout.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `train_forecast_model.jl` to add `HTTP.post` calls (via the `HTTP.jl`
   package) targeting the sidecar so that each training step emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
