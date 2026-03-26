# How to create the first release

## Tag v0.1.0

```bash
git tag -a v0.1.0 -m "Initial release — 4-tier OTel coverage, GPU/CUDA, mobile, legacy runtimes"
git push origin v0.1.0
```

Then go to: https://github.com/gmoskovicz/edot-autopilot/releases/new
- Tag: v0.1.0
- Title: v0.1.0 — Business-aware OTel for any language
- Body: copy the "What this is" section from README.md

## Why this matters

A repo with 50+ commits and no release looks unfinished.
A tagged release appears in GitHub's release feed, gets indexed by pkg.go.dev,
npmjs.com search, and shows up in "recently released" filters on GitHub Explore.
