# Tier D — PowerShell with OTEL Sidecar
#
# PowerShell has no OpenTelemetry SDK.
# But Invoke-RestMethod works from PS 3.0+, which means any Windows machine since 2012.
# The sidecar translates our JSON to OTLP spans for Elastic APM.
#
# Usage: .\demo.ps1
#        Set $env:OTEL_SIDECAR_URL = "http://localhost:9411" if non-default port

param(
    [string]$SidecarUrl = ($env:OTEL_SIDECAR_URL ?? "http://127.0.0.1:9411")
)

# ── Helper: fire-and-forget event ────────────────────────────────────────────
function Send-OtelEvent {
    param(
        [string]$Name,
        [hashtable]$Attributes = @{}
    )
    try {
        Invoke-RestMethod `
            -Uri $SidecarUrl `
            -Method Post `
            -ContentType "application/json" `
            -TimeoutSec 1 `
            -Body (@{ action = "event"; name = $Name; attributes = $Attributes } | ConvertTo-Json -Depth 5) `
            | Out-Null
    } catch {
        # Never let telemetry fail the script
    }
}

# ── Helper: start a long-running span ────────────────────────────────────────
function Start-OtelSpan {
    param(
        [string]$Name,
        [hashtable]$Attributes = @{}
    )
    try {
        $resp = Invoke-RestMethod `
            -Uri $SidecarUrl `
            -Method Post `
            -ContentType "application/json" `
            -TimeoutSec 1 `
            -Body (@{ action = "start_span"; name = $Name; attributes = $Attributes } | ConvertTo-Json -Depth 5)
        return $resp.span_id
    } catch {
        return ""
    }
}

# ── Helper: end a span ────────────────────────────────────────────────────────
function Stop-OtelSpan {
    param(
        [string]$SpanId,
        [hashtable]$Attributes = @{},
        [string]$Error = ""
    )
    if (-not $SpanId) { return }
    $body = @{ action = "end_span"; span_id = $SpanId; attributes = $Attributes }
    if ($Error) { $body["error"] = $Error }
    try {
        Invoke-RestMethod `
            -Uri $SidecarUrl `
            -Method Post `
            -ContentType "application/json" `
            -TimeoutSec 1 `
            -Body ($body | ConvertTo-Json -Depth 5) `
            | Out-Null
    } catch {}
}

# ─────────────────────────────────────────────────────────────────────────────
# Simulated Windows ETL script — runs as a scheduled task
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "Starting ETL batch (PowerShell Tier D demo)..."

$batchSpan = Start-OtelSpan -Name "etl.windows.batch" -Attributes @{
    "batch.source"   = "MSSQL-ERP"
    "batch.schedule" = "02:00 UTC"
    "os"             = "windows"
}

$rowCount = Get-Random -Minimum 10000 -Maximum 60000
Start-Sleep -Milliseconds 300

Send-OtelEvent -Name "etl.extract.complete" -Attributes @{
    "extract.rows"   = $rowCount
    "extract.source" = "MSSQL-legacy"
}

Start-Sleep -Milliseconds 200

$errors = Get-Random -Minimum 0 -Maximum 50
Send-OtelEvent -Name "etl.transform.complete" -Attributes @{
    "transform.rows_in"  = $rowCount
    "transform.rows_out" = ($rowCount - $errors)
    "transform.errors"   = $errors
}

Stop-OtelSpan -SpanId $batchSpan -Attributes @{
    "batch.total_rows" = $rowCount
    "batch.errors"     = $errors
    "batch.status"     = "success"
}

Write-Host "ETL complete. $rowCount rows, $errors errors."

# ─────────────────────────────────────────────────────────────────────────────
# AD user provisioning — another common PowerShell automation
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "Simulating AD user provisioning..."

$provSpan = Start-OtelSpan -Name "ad.user.provision" -Attributes @{
    "ad.domain"    = "corp.example.com"
    "ad.operation" = "bulk_create"
}

Start-Sleep -Milliseconds 150
$usersCreated = Get-Random -Minimum 1 -Maximum 50

Stop-OtelSpan -SpanId $provSpan -Attributes @{
    "ad.users_created"  = $usersCreated
    "ad.groups_updated" = 3
    "ad.status"         = "ok"
}

Write-Host "Provisioned $usersCreated users. Check Kibana APM → powershell-tier-d"
