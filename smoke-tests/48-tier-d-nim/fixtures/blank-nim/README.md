# blank-nim — FIX 4.4 Protocol Message Parser (Nim)

## What this program does

`fix_parser.nim` is a Nim 2.0 binary (compiled with `-d:release`) that
implements a high-throughput FIX 4.4 protocol message parser for financial
market data:

1. **parseFIXMessage** — parses raw FIX 4.4 messages (SOH `\x01` or `|`
   delimited key=value pairs), validates required tags (35 MsgType, 11
   ClOrdID), and returns a structured `OrderRecord` with symbol, side,
   quantity, price, and sequence number
2. **routeToHandler** — routes successfully parsed messages to the appropriate
   handler based on message type:
   - `D` NewOrderSingle → order entry handler
   - `F` OrderCancelRequest → cancel handler
   - `G` OrderCancelReplaceRequest → amend handler
   - `8` ExecutionReport → fill/status handler
3. **Error handling** — malformed messages (missing required tags) are counted
   as parse errors and logged to stderr

The program reads FIX messages from stdin (one per line), processes them
at sub-millisecond latency (target < 10 µs), and prints a summary on exit.

## Why it has no observability

This is a **Tier D** legacy application. Nim has no OpenTelemetry SDK (no
`opentelemetry-nim` package exists in Nimble).

There are no HTTP calls, no sidecar references, no trace/span IDs — just
`echo` / `writeLine` output to stdout/stderr.

The EDOT Autopilot agent must:
1. Copy `otel-sidecar.py` into the project
2. Modify `fix_parser.nim` to add `httpclient.post` calls (via Nim's standard
   `httpclient` module) targeting the sidecar so that each parsed message
   emits a span
3. Create `.otel/slos.json` and `.otel/golden-paths.md`
