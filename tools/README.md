# tools/

## demo.sh — Produce the repo demo GIF

Run this script and screen-record the terminal output. Recommended tools:
- macOS: QuickTime → trim → convert with `ffmpeg -i demo.mov -r 10 demo.gif`
- Linux: `asciinema rec demo.cast` then `agg demo.cast demo.gif`
- All platforms: https://www.terminalizer.com

Upload the resulting GIF as `assets/demo.gif` and add to README.md:
```
![EDOT Autopilot demo](assets/demo.gif)
```

## otel-contracts.py — Telemetry contract validator

Validates that reference app source files satisfy their declared span attribute
contracts. Used in CI (see `.github/workflows/smoke-tests.yml`).

```bash
python tools/otel-contracts.py validate \
  --contracts tools/test_contracts.yaml \
  --root .
```
