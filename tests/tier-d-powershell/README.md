# Tier D — PowerShell

PowerShell has no OpenTelemetry SDK. But `Invoke-RestMethod` is available from PS 3.0+ (Windows Server 2012 and later). That's enough.

## The key functions

```powershell
# Fire-and-forget event
Send-OtelEvent "etl.batch.complete" @{rows=50000; duration_ms=4200; source="legacy-erp"}

# Multi-step span
$span = Start-OtelSpan "etl.windows.batch" @{source="MSSQL-ERP"}
# ... do the work ...
Stop-OtelSpan $span @{rows_processed=50000; status="ok"}
```

## Run

```powershell
# 1. Start the sidecar (from WSL, Docker Desktop, or a Python environment)
#    See otel-sidecar/README.md

# 2. Run the demo
$env:OTEL_SIDECAR_URL = "http://127.0.0.1:9411"
.\demo.ps1
```

## Real-world use cases

- Scheduled task execution tracking
- Active Directory provisioning scripts
- Windows backup scripts
- SCCM/Intune deployment scripts
- Legacy SSIS wrapper scripts
