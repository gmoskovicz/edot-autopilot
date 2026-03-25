---
name: Add OpenTelemetry support for [Language]
about: Request or contribute a new Tier D language caller snippet
title: "Add Tier D support for [Language]"
labels: ["tier-d", "new-language", "good first issue"]
assignees: ''
---

## Language

**Name and version:**
(e.g., MUMPS / Cache 2018, Tcl 8.5, Fortran 77, REXX on z/OS 2.4)

---

## Runtime Environment

**Operating system and architecture:**
(e.g., AIX 7.2 on POWER9, Windows Server 2003 on x86, IBM i 7.4, z/OS 2.4)

**Interpreter, compiler, or VM:**
(e.g., GnuCOBOL 3.1, SWI-Prolog 9.0, OpenVMS Alpha, iSeries PASE)

**Is Python or Node.js available on the same host?**
(The otel-sidecar requires Python 3.8+ or Node.js 16+. If neither is available, note that here and we can discuss alternatives.)

---

## Available HTTP Client

**What HTTP client is available in this runtime?**

Examples:
- Standard library module (e.g., Tcl's `http` package, Perl's `LWP::UserAgent`)
- External binary (e.g., `curl` or `wget` via subprocess / `SYSTEM` call)
- C library binding (e.g., `libcurl` via FFI)
- Socket API (raw TCP, if nothing else is available)
- None known

If you are not sure, describe how you would make any outbound network call from this runtime and we can help figure out the right approach.

---

## Example Business Operation

**Paste a snippet of real (or representative) code for a critical business operation in this language.**

This is what the caller snippet will be placed next to. It helps us write an example that is idiomatic and realistic rather than a toy "hello world".

```
<paste your code here>
```

**What does this operation do in business terms?**
(e.g., "processes a payroll batch", "generates an invoice", "updates inventory")

---

## Existing Code Samples

**Do you have any existing code that makes HTTP calls or subprocess calls from this runtime?**

If yes, paste it here. Even a rough example helps — we can adapt it into the snippet format.

```
<paste here if available>
```

---

## Additional Context

Any other details that would help — known limitations of the runtime's networking stack, security restrictions on outbound calls, encoding issues (EBCDIC, etc.), or links to relevant documentation.
