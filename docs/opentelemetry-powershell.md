# OpenTelemetry for PowerShell — Complete Guide

> How to instrument PowerShell scripts — Active Directory automation, SQL Server maintenance, Windows infrastructure jobs — so they appear as real spans in Elastic APM.

## The problem

PowerShell scripts automate the most critical Windows infrastructure in the enterprise:

- **Active Directory management**: user provisioning, group membership synchronization, account expiry enforcement
- **SQL Server operations**: index rebuilds, statistics updates, backup jobs, AG failover scripts
- **Azure and Microsoft 365**: tenant provisioning, license assignment, Intune policy deployment
- **Windows Server maintenance**: Windows Update orchestration, certificate renewal, IIS recycling
- **ETL and reporting**: pulling data from on-prem SQL Server into data warehouses, generating Excel reports via COM objects
- **SCCM / Endpoint Manager**: package deployment, compliance reporting, inventory collection

Every one of these is completely invisible to APM tools. PowerShell has no OpenTelemetry SDK. There is no PowerShell agent. There is a .NET runtime underneath, but the PowerShell process itself cannot be instrumented with the .NET EDOT SDK without rebuilding it as a managed application.

When a critical AD sync script fails silently or a SQL index rebuild runs 10x longer than expected, the team finds out from a business impact — locked-out users, slow queries, failed reports — not from an alert.

## The solution: Telemetry Sidecar

The EDOT Autopilot telemetry sidecar runs as a local HTTP server on port 9411. Your PowerShell scripts use `Invoke-RestMethod` — available in all PowerShell versions from 3.0 onward (Windows 8 / Server 2012 and later) — to send events to the sidecar. The sidecar translates those events into OTLP spans and forwards them to Elastic.

Architecture:

```
[PowerShell Script / Scheduled Task]
    |
    | Invoke-RestMethod http://127.0.0.1:9411
    |
    v
[otel-sidecar.py :9411]   (Python, same host)
    |
    | OTLP/HTTP
    v
[Elastic Cloud APM]
```

The entire call is wrapped in a `try/catch` that swallows all errors. Telemetry must never cause a script to fail.

## Step-by-step setup

### Step 1: Install Python and the sidecar on the Windows host

Python 3.8+ is required. Install from python.org or via winget:

```powershell
winget install Python.Python.3.12
```

Then install the sidecar dependencies:

```powershell
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

Clone the repo:

```powershell
git clone https://github.com/gmoskovicz/edot-autopilot C:\opt\edot-autopilot
```

### Step 2: Configure environment variables

Set system environment variables (or add them to the sidecar's Windows service configuration):

```powershell
[System.Environment]::SetEnvironmentVariable("OTEL_SERVICE_NAME", "windows-ops-scripts", "Machine")
[System.Environment]::SetEnvironmentVariable("ELASTIC_OTLP_ENDPOINT", "https://<deployment>.apm.<region>.cloud.es.io", "Machine")
[System.Environment]::SetEnvironmentVariable("ELASTIC_API_KEY", "<your-key>", "Machine")
[System.Environment]::SetEnvironmentVariable("OTEL_DEPLOYMENT_ENVIRONMENT", "production", "Machine")
```

### Step 3: Install the sidecar as a Windows service

Use NSSM (Non-Sucking Service Manager) or the built-in SC command:

```powershell
# Using NSSM (recommended)
nssm install OtelSidecar "C:\Python312\python.exe" "C:\opt\edot-autopilot\otel-sidecar\otel-sidecar.py"
nssm set OtelSidecar AppEnvironmentExtra "OTEL_SERVICE_NAME=windows-ops-scripts"
nssm set OtelSidecar Start SERVICE_AUTO_START
nssm start OtelSidecar
```

### Step 4: Add the helper function to your scripts

Paste the `Send-OtelEvent` function at the top of each script. No other dependencies needed.

### Step 5: Verify in Kibana APM

After running a script, navigate to Kibana → Observability → APM → Services within 60 seconds.

## Code example

### The core helper function

```powershell
function Send-OtelEvent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [hashtable]$Attr = @{}
    )
    try {
        Invoke-RestMethod `
            -Uri         http://127.0.0.1:9411 `
            -Method      Post `
            -ContentType 'application/json' `
            -TimeoutSec  1 `
            -Body        (@{action = 'event'; name = $Name; attributes = $Attr} | ConvertTo-Json -Compress)
    } catch {
        # Never propagate telemetry errors into the script
    }
}
```

### Active Directory user provisioning

```powershell
#Requires -Modules ActiveDirectory

. .\Telemetry.ps1  # or paste Send-OtelEvent inline

function Provision-ADUser {
    param(
        [string]$Username,
        [string]$Department,
        [string]$Manager,
        [string]$License
    )

    $startTime = Get-Date

    try {
        # Create AD user
        New-ADUser -Name $Username -Department $Department -Manager $Manager -Enabled $true
        Add-ADGroupMember -Identity "All-Staff" -Members $Username

        $duration = [int](New-TimeSpan -Start $startTime -End (Get-Date)).TotalMilliseconds

        Send-OtelEvent "ad.user.provisioned" @{
            "user.name"          = $Username
            "user.department"    = $Department
            "user.manager"       = $Manager
            "user.license"       = $License
            "duration_ms"        = $duration
        }

    } catch {
        Send-OtelEvent "ad.user.provisioning.failed" @{
            "user.name"   = $Username
            "error.message" = $_.Exception.Message
            "error.type"    = $_.Exception.GetType().Name
        }
        throw
    }
}
```

### SQL Server index maintenance

```powershell
function Invoke-IndexMaintenance {
    param(
        [string]$ServerInstance,
        [string]$Database,
        [int]$FragmentationThreshold = 30
    )

    Send-OtelEvent "sqlserver.index_maintenance.started" @{
        "db.server"   = $ServerInstance
        "db.name"     = $Database
        "threshold_pct" = $FragmentationThreshold
    }

    $startTime = Get-Date
    $rebuilt    = 0
    $reorganized = 0

    $indexes = Get-FragmentedIndexes -Server $ServerInstance -Database $Database -Threshold $FragmentationThreshold

    foreach ($index in $indexes) {
        if ($index.AvgFragmentation -ge $FragmentationThreshold) {
            Rebuild-Index -Server $ServerInstance -Database $Database -Index $index
            $rebuilt++
        } else {
            Reorganize-Index -Server $ServerInstance -Database $Database -Index $index
            $reorganized++
        }
    }

    $duration = [int](New-TimeSpan -Start $startTime -End (Get-Date)).TotalSeconds

    Send-OtelEvent "sqlserver.index_maintenance.complete" @{
        "db.server"          = $ServerInstance
        "db.name"            = $Database
        "indexes.rebuilt"    = $rebuilt
        "indexes.reorganized" = $reorganized
        "indexes.total"      = $indexes.Count
        "duration_s"         = $duration
    }
}
```

### ETL batch job with multi-step spans

```powershell
function Send-OtelSpanStart {
    param([string]$Name, [hashtable]$Attr = @{})
    try {
        $response = Invoke-RestMethod `
            -Uri         http://127.0.0.1:9411 `
            -Method      Post `
            -ContentType 'application/json' `
            -TimeoutSec  1 `
            -Body        (@{action = 'start_span'; name = $Name; attributes = $Attr} | ConvertTo-Json -Compress)
        return $response.span_id
    } catch { return $null }
}

function Send-OtelSpanEnd {
    param([string]$SpanId, [string]$Error = $null, [hashtable]$Attr = @{})
    if (-not $SpanId) { return }
    try {
        $body = @{action = 'end_span'; span_id = $SpanId; attributes = $Attr}
        if ($Error) { $body['error'] = $Error }
        Invoke-RestMethod `
            -Uri         http://127.0.0.1:9411 `
            -Method      Post `
            -ContentType 'application/json' `
            -TimeoutSec  1 `
            -Body        ($body | ConvertTo-Json -Compress)
    } catch {}
}

# Usage — ETL with per-phase duration tracking
$spanId = Send-OtelSpanStart "etl.batch" @{
    "source"        = "legacy-erp"
    "target"        = "data-warehouse"
    "pipeline.date" = (Get-Date -Format "yyyy-MM-dd")
}

try {
    $rows = Import-FromLegacyERP
    $transformed = Transform-Records $rows
    Export-ToDataWarehouse $transformed

    Send-OtelSpanEnd $spanId $null @{
        "rows.extracted"   = $rows.Count
        "rows.loaded"      = $transformed.Count
        "rows.rejected"    = ($rows.Count - $transformed.Count)
        "status"           = "ok"
    }
} catch {
    Send-OtelSpanEnd $spanId $_.Exception.Message @{
        "status" = "failed"
    }
    throw
}
```

### Scheduled Task instrumentation (running from Task Scheduler)

When running PowerShell scripts from Windows Task Scheduler, ensure the sidecar service is started before the tasks run, and include telemetry in the body of each script:

```powershell
# C:\Scripts\nightly-report.ps1
# Runs at 02:00 daily via Task Scheduler

. "C:\Scripts\Telemetry.ps1"

Send-OtelEvent "report.generation.started" @{
    "report.name" = "Monthly Revenue Summary"
    "run.date"    = (Get-Date -Format "yyyy-MM-dd")
}

$startTime = Get-Date

try {
    $data = Get-ReportData
    Export-ToExcel $data "\\fileserver\reports\revenue-$(Get-Date -Format 'yyyyMM').xlsx"

    Send-OtelEvent "report.generation.complete" @{
        "report.name"    = "Monthly Revenue Summary"
        "rows.exported"  = $data.Count
        "duration_s"     = [int](New-TimeSpan -Start $startTime -End (Get-Date)).TotalSeconds
        "output.path"    = "\\fileserver\reports"
    }
} catch {
    Send-OtelEvent "report.generation.failed" @{
        "report.name"   = "Monthly Revenue Summary"
        "error.message" = $_.Exception.Message
    }
    exit 1
}
```

## What you'll see in Elastic

After deployment:

- **Named service** in Kibana APM (e.g., `windows-ops-scripts`) with all your PowerShell operations listed.
- **Operation history**: Every AD provisioning, every SQL maintenance window, every scheduled report is recorded as a span.
- **Duration trends**: See immediately when your SQL index rebuild starts taking 3x longer than usual — before users notice slow queries.
- **Failure tracking**: Failed scripts appear in the Errors tab with the exception message and type attached.
- **Custom dashboards**: Build Kibana dashboards showing AD provisioning rates by department, index fragmentation over time, and report generation success rates.

Example ES|QL query to find slow ETL runs:

```esql
FROM traces-apm*
| WHERE service.name == "windows-ops-scripts"
  AND span.name == "etl.batch"
| EVAL duration_min = span.duration.us / 60000000
| WHERE duration_min > 60
| KEEP @timestamp, attributes.pipeline\.date, duration_min, attributes.rows\.loaded
| SORT duration_min DESC
```

## Related

- [Telemetry Sidecar Pattern — full documentation](./telemetry-sidecar-pattern.md)
- [OpenTelemetry for Legacy Runtimes — overview](./opentelemetry-legacy-runtimes.md)
- [OpenTelemetry for Bash scripts](./opentelemetry-bash-shell-scripts.md)
- [OpenTelemetry for .NET Framework 4.x](./opentelemetry-dotnet-framework-4x.md)
- [Business Span Enrichment](./business-span-enrichment.md)

---

> Found this useful? [Star the repo](https://github.com/gmoskovicz/edot-autopilot) — it helps other PowerShell developers find this solution.
