# ================================================================
# FILE:       train_forecast_model.jl
# DESCRIPTION: Demand forecasting LSTM training pipeline (Julia)
#              Loads historical sales parquet files, builds an
#              LSTM time-series model with Flux.jl, trains for
#              N epochs, evaluates MAPE on validation set,
#              exports final model as ONNX artifact.
#
# RUNTIME:    Julia 1.10
# PACKAGES:   Flux, ONNX, DataFrames, Parquet, Statistics, CUDA
# SCHEDULE:   Weekly retraining via cron (Sunday 02:00)
# ================================================================

using Flux
using Statistics
using Random
using Printf

# ---- Configuration -------------------------------------------
const CONFIG = Dict(
    :run_id        => string(rand(UInt32), base=16)[1:8],
    :model         => "LSTM-Demand-v3",
    :dataset       => "sales_history_2020_2025",
    :train_rows    => 2_100_000,
    :val_rows      =>   420_000,
    :epochs        => 8,
    :batch_size    => 1024,
    :hidden_units  => 256,
    :seq_length    => 52,   # weeks
    :learning_rate => 1e-3,
    :artifact_dir  => "models",
)

# ================================================================
# load_parquet — load sales history from parquet files
# ================================================================
function load_parquet(dataset_name::String; split::Symbol=:train)
    # In production: Parquet.read(joinpath("data", dataset_name, "$split.parquet"))
    # Simulated: return random tensors with correct shape
    rows = split == :train ? CONFIG[:train_rows] : CONFIG[:val_rows]
    seq  = CONFIG[:seq_length]
    # Features: [week_of_year, lag_1w, lag_4w, lag_52w, store_id, sku_id, ...]
    X = randn(Float32, 8, seq, rows ÷ seq)   # (features, seq_len, batch)
    y = randn(Float32, 1, rows ÷ seq)         # (output, batch)
    @printf "  Loaded %s/%s: %d sequences\n" dataset_name String(split) size(X, 3)
    return X, y
end

# ================================================================
# build_lstm_model — construct Flux LSTM architecture
# ================================================================
function build_lstm_model(; input_size=8, hidden=256, output=1)
    Chain(
        LSTM(input_size => hidden),
        LSTM(hidden => hidden ÷ 2),
        Dense(hidden ÷ 2 => output),
    )
end

# ================================================================
# mape_loss — Mean Absolute Percentage Error (validation metric)
# ================================================================
function mape_loss(y_hat::AbstractArray, y_true::AbstractArray)
    100.0f0 * mean(abs.((y_hat .- y_true) ./ (abs.(y_true) .+ 1f-8)))
end

# ================================================================
# train_epoch! — run one training epoch, return avg loss
# ================================================================
function train_epoch!(model, X_train, y_train, opt_state, batch_size)
    n_batches  = size(X_train, 3) ÷ batch_size
    total_loss = 0.0f0

    for b in 1:n_batches
        idx = ((b-1)*batch_size + 1) : (b*batch_size)
        Xb  = X_train[:, :, idx]
        yb  = y_train[:, idx]

        loss, grads = Flux.withgradient(model) do m
            # Reset LSTM hidden state per batch
            Flux.reset!(m)
            ŷ = m(Xb)
            Flux.mse(ŷ, yb)
        end

        Flux.update!(opt_state, model, grads[1])
        total_loss += loss
    end

    return total_loss / n_batches
end

# ================================================================
# evaluate_model — compute MAPE on validation set
# ================================================================
function evaluate_model(model, X_val, y_val)
    Flux.reset!(model)
    ŷ = model(X_val)
    return mape_loss(ŷ, y_val)
end

# ================================================================
# MAIN
# ================================================================
function main()
    run_id = CONFIG[:run_id]
    @printf "\n=== Julia LSTM Demand Forecast Training ===\n"
    @printf "Run:    %s\n" run_id
    @printf "Model:  %s\n" CONFIG[:model]
    @printf "Data:   %s\n" CONFIG[:dataset]
    @printf "Epochs: %d   LR: %.4f   Batch: %d\n\n" CONFIG[:epochs] CONFIG[:learning_rate] CONFIG[:batch_size]

    # ---- Step 1: Load dataset ----
    X_train, y_train = load_parquet(CONFIG[:dataset], split=:train)
    X_val,   y_val   = load_parquet(CONFIG[:dataset], split=:val)

    # ---- Step 2: Build model ----
    model     = build_lstm_model(hidden=CONFIG[:hidden_units])
    opt_state = Flux.setup(Adam(CONFIG[:learning_rate]), model)
    @printf "Model parameters: %d\n\n" sum(length, Flux.params(model))

    best_mape = Inf
    best_epoch = 0

    # ---- Step 3: Training loop ----
    for epoch in 1:CONFIG[:epochs]
        t0 = time()

        train_loss = train_epoch!(model, X_train, y_train, opt_state, CONFIG[:batch_size])
        val_mape   = evaluate_model(model, X_val, y_val)

        elapsed_ms = (time() - t0) * 1000

        if val_mape < best_mape
            best_mape  = val_mape
            best_epoch = epoch
        end

        @printf "  Epoch %d/%d  loss=%.4f  val_mape=%.2f%%  elapsed=%.0fms\n" epoch CONFIG[:epochs] train_loss val_mape elapsed_ms
    end

    @printf "\nBest val_mape: %.2f%% (epoch %d)\n" best_mape best_epoch

    # ---- Step 4: Export ONNX ----
    artifact_path = joinpath(CONFIG[:artifact_dir],
        @sprintf "%s_%s.onnx" CONFIG[:model] run_id)
    mkpath(CONFIG[:artifact_dir])
    # In production: ONNX.write(artifact_path, model, dummy_input)
    @printf "Model exported: %s\n" artifact_path

    @printf "\n=== Training complete. Best MAPE=%.2f%% ===\n" best_mape
end

main()
