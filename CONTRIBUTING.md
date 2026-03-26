# Contributing to EDOT Autopilot

## Welcome

EDOT Autopilot exists to make observability accessible for every codebase — including the ones that every other tool ignores. The most valuable contributions are **Tier D language caller snippets**: the small code fragments that let a COBOL program, a Perl script, or a Fortran job emit telemetry to the otel-sidecar via a simple HTTP POST.

If you maintain a legacy runtime and have figured out how to make an HTTP call from it, you can add support for that language in about 30 minutes. No deep OTel knowledge required.

Other high-value contributions:
- Smoke tests that exercise an existing snippet against a real sidecar
- Tier B instrumentation wrappers for unsupported frameworks in supported languages
- Tier C monkey-patches for widely-used libraries with no OTel plugin
- Bug fixes and documentation improvements

---

## How to Add a New Tier D Language Caller Snippet

### Overview

A Tier D snippet is a short block of code — in the target language — that calls the otel-sidecar's HTTP API. The sidecar translates the call into an OTLP span and forwards it to Elastic. The legacy process never needs to know about OTel.

### Step-by-step

**1. Fork and clone**

```bash
git clone https://github.com/<your-username>/edot-autopilot.git
cd edot-autopilot
```

**2. Create the directory for your language**

```bash
mkdir -p smoke-tests/tier-d-<language>
```

For example: `smoke-tests/tier-d-mumps`, `smoke-tests/tier-d-rexx`, `smoke-tests/tier-d-tcl`.

Use lowercase, hyphen-separated names. Match the language name as it is commonly known.

**3. Write the caller snippet**

Create `smoke-tests/tier-d-<language>/caller.<ext>` with the language's idiomatic HTTP POST.

The snippet must:
- POST to `http://127.0.0.1:9411` (the sidecar's default address)
- Send a JSON body: `{"action": "event", "name": "<span-name>", "attributes": {...}}`
- Not block or crash the calling process if the sidecar is unavailable
- Use only the standard library or universally available packages for that runtime

Example structure (Tcl):

```tcl
# otel_event -- emit a telemetry event to the local OTel sidecar
# Usage: otel_event <span_name> <attributes_dict>
proc otel_event {name attrs} {
    package require http
    package require json::write
    catch {
        set body [json::write object \
            action  [json::write string event] \
            name    [json::write string $name] \
            attributes [json::write object {*}[dict map {k v} $attrs {
                list $k [json::write string $v]
            }]]]
        set tok [http::geturl http://127.0.0.1:9411 \
            -method POST \
            -type   application/json \
            -query  $body \
            -timeout 1000]
        http::cleanup $tok
    }
}

# Example usage — place near the business operation, not at the top of the file
otel_event "batch.report.complete" {report_id RPT-001 rows_processed 50000 duration_s 12}
```

**4. Write a README for your snippet**

Create `smoke-tests/tier-d-<language>/README.md` explaining:
- Which runtime versions were tested
- Which HTTP package the snippet depends on (if any)
- Any known limitations (e.g., "requires curl on PATH", "tested on AIX 7.2 only")
- How to place the snippet in a real program

**5. Add a smoke test**

Create `smoke-tests/tier-d-<language>/smoke-test.sh` (or equivalent) that:
1. Starts the otel-sidecar locally (see "How to test" below)
2. Invokes the caller snippet with a test event
3. Verifies the sidecar received it (via its stdout or a follow-up curl)

Minimal example:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Start sidecar in background
export OTEL_SERVICE_NAME=tier-d-tcl-smoke-test
export ELASTIC_OTLP_ENDPOINT=http://localhost:4318   # use a local collector for CI
export ELASTIC_API_KEY=test
python3 ../../otel-sidecar.py &
SIDECAR_PID=$!
sleep 1

# Send test event using the snippet under test
tclsh caller.tcl

# Verify sidecar received it (check process is still alive = no crash)
kill $SIDECAR_PID
echo "PASS: sidecar received event without error"
```

**6. Submit a pull request**

Push your branch and open a PR. Use the template below.

---

## PR Title and Checklist

**Title format:** `Add Tier D support for [Language]`

Examples:
- `Add Tier D support for MUMPS`
- `Add Tier D support for Tcl`
- `Add Tier D support for Erlang`

**PR checklist** (include this in your PR description):

```
## Checklist

- [ ] Caller snippet written at `smoke-tests/tier-d-<lang>/caller.<ext>`
- [ ] README added at `smoke-tests/tier-d-<lang>/README.md` with runtime version, dependencies, limitations
- [ ] Smoke test added at `smoke-tests/tier-d-<lang>/smoke-test.sh` (or equivalent)
- [ ] Snippet does not crash or block if the sidecar is unavailable
- [ ] Snippet uses only stdlib or universally available packages
- [ ] CLAUDE.md Tier D section references the new language (if adding to the language list)
```

---

## How to Test Locally

### 1. Install the sidecar dependencies

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

### 2. Start the sidecar

You can point it at a real Elastic deployment or at a local collector. For local testing without Elastic, use a simple netcat listener to confirm the sidecar is receiving calls:

```bash
# Option A — real Elastic endpoint
export OTEL_SERVICE_NAME=my-tier-d-test
export ELASTIC_OTLP_ENDPOINT=https://<deployment>.apm.<region>.cloud.es.io
export ELASTIC_API_KEY=<your-key>
python3 otel-sidecar.py

# Option B — local collector (no Elastic account needed)
docker run -p 4318:4318 otel/opentelemetry-collector-contrib:latest &
export OTEL_SERVICE_NAME=my-tier-d-test
export ELASTIC_OTLP_ENDPOINT=http://localhost:4318
export ELASTIC_API_KEY=ignored
python3 otel-sidecar.py
```

### 3. Send a test event with curl

```bash
curl -s -X POST http://127.0.0.1:9411 \
  -H "Content-Type: application/json" \
  -d '{"action":"event","name":"test.event","attributes":{"test.key":"hello"}}'
```

Expected response: `{"ok": true}`

### 4. Verify in Elastic (if using a real endpoint)

In Kibana, go to **Observability → APM → Services**. The service named by `OTEL_SERVICE_NAME` should appear within 60 seconds. Open it and confirm the `test.event` span is present with `test.key = hello`.

### 5. Verify without Elastic (local collector)

Check the collector's stdout for the exported span. You should see the span name and attributes in the log output.

---

## How to Add a Tier B or Tier C Instrumentation

### Tier B — Unsupported framework, supported language

1. Identify the framework's entry point (how requests enter the application)
2. Write a wrapper function using the OTel SDK that creates a SERVER span, sets semantic convention attributes, and captures exceptions
3. Add the wrapper to `smoke-tests/` under a descriptive directory name (e.g., `smoke-tests/tier-b-django-1x/`)
4. Include a README explaining which framework version it targets and how to apply the wrapper

See the Python and Java examples in `CLAUDE.md` (Phase 2, Tier B) as reference implementations.

### Tier C — Supported language, unsupported library

1. Identify the library's public interface (the method or function to wrap)
2. Write a monkey-patch that replaces the method at import time with an instrumented version
3. The patch must be transparent — the caller sees no behavioral change
4. Add to `smoke-tests/tier-c-<library-name>/`
5. Include attributes that have business meaning for that library (payment amounts, email recipient counts, etc.)

See the Stripe example in `CLAUDE.md` (Phase 2, Tier C) as a reference.

---

## Languages We Need

The following languages have no snippet yet. If you work with any of these, a contribution would be genuinely useful:

| Language | Notes |
|---|---|
| MUMPS / Caché | Used in healthcare systems (Epic, VistA). `%Net.HttpRequest` may be available. |
| REXX | IBM mainframe and OS/2 scripts. `rxsocket` or shell-out to curl. |
| Erlang (legacy) | OTel SDK exists for modern Elixir but not old Erlang/OTP versions. `httpc` is stdlib. |
| Haskell | No complete OTel SDK. `http-client` or `wreq` available. |
| OCaml | No OTel SDK. `cohttp` or `curl` bindings available. |
| PHP 5 (legacy) | PHP 8 has OTel support but PHP 5 does not. `curl_exec` is available. |
| PL/I | Used in IBM mainframe financial systems. Shell-out to curl or `CEEGTST` socket API. |
| Natural (Software AG) | Used in mainframe banking and insurance. `HTTP-GET`/`HTTP-POST` built-in available. |

Already covered (smoke tests exist, no new snippet needed):
RPG/AS400 · Fortran · Tcl · Lua · COBOL · Bash · Perl · PowerShell · Classic ASP · VBA/Excel · MATLAB · R · AWK · Delphi · ColdFusion · Julia · Nim · Ada · SAP ABAP

---

## How to Add a Gen-AI Provider (Test 89)

Test `89-tier-c-genai-llm` instruments LLM API calls from OpenAI, Anthropic, and
AWS Bedrock. To add a new provider (Gemini, Mistral, Ollama, etc.):

1. Open `smoke-tests/89-tier-c-genai-llm/app.py`
2. Add a new entry to the `PROVIDERS` list:

```python
{"name": "gemini",  "model": "gemini-1.5-pro",   "system": "vertex_ai"},
{"name": "mistral", "model": "mistral-large",     "system": "mistral_ai"},
{"name": "ollama",  "model": "llama3.1",          "system": "ollama"},
```

The `system` value must match the official OTel `gen_ai.system` value from the
[semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/). For
providers not yet in the semconv, use a lowercase hyphenated string (e.g. `mistral_ai`).

3. Update the smoke test count assertion in `smoke.py` if needed.
4. Add an entry to `README.md` in the test's own directory.

No real API key is needed — the mock call simulates latency and token counts.

---

## How to Add a Kubernetes Smoke Test

Kubernetes instrumentation tests verify that the OTel Operator injection pattern
produces correct spans without modifying application source.

1. Create `smoke-tests/<N>-k8s-<scenario>/` with `smoke.py` and a fixture
2. The fixture should be a minimal Kubernetes manifest (`deployment.yaml`) with the
   `instrumentation.opentelemetry.io/inject-python: "true"` annotation
3. `smoke.py` validates that the annotation is present and that the generated
   manifest references the correct OTel images
4. For full integration: spin up a local kind cluster, apply the manifest, generate
   traffic, and assert spans appear in a local OTel Collector

Use the existing `tests/integration/` pattern (Docker Compose + file exporter) as a
reference for the collector setup.

---

## Code of Conduct

Contributors are expected to be respectful to one another. This is a technical project maintained by practitioners; assume good faith, keep feedback constructive, and focus on the work.

---

## Questions

Open a GitHub Discussion or file an issue with the `question` label.
