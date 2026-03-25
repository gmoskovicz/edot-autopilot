#Requires -Modules ActiveDirectory, ExchangeOnlineManagement
<#
.SYNOPSIS
    New-HireProvisioning.ps1 — Automates new-employee onboarding in Azure AD / on-prem AD.

.DESCRIPTION
    Reads a CSV of new hires, creates Active Directory accounts, assigns security
    groups, and provisions Microsoft 365 mailboxes via Exchange Online.

    Run by HR IT-Ops every Monday morning after the weekly new-hire report is
    exported from Workday.

.PARAMETER CsvPath
    Path to the new-hires CSV exported from Workday.
    Default: .\new-hires.csv

.PARAMETER DryRun
    If set, logs what would be done without making any changes.

.EXAMPLE
    .\New-HireProvisioning.ps1 -CsvPath .\new-hires-2026-03.csv
#>

param(
    [string]$CsvPath    = ".\new-hires.csv",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configuration ─────────────────────────────────────────────────────────────

$DomainDN       = "DC=company,DC=corp"
$DefaultOU      = "OU=NewHires,OU=Users,$DomainDN"
$ExchangePlan   = "E3"
$DefaultGroups  = @("all-employees", "vpn-access")

$DeptGroupMap = @{
    "Engineering" = @("eng-all", "github-org", "vpn-access")
    "Sales"       = @("sales-all", "crm-access", "salesforce")
    "Finance"     = @("finance-all", "netsuite-ro", "vpn-access")
    "HR"          = @("hr-all", "workday-access")
    "IT"          = @("it-all", "vpn-access", "azure-portal")
}

# ── Helpers ───────────────────────────────────────────────────────────────────

function Get-SamAccountName {
    param([string]$FullName)
    $parts = $FullName.Trim() -split "\s+"
    return ($parts[0][0] + "." + $parts[-1]).ToLower()
}

function Write-Log {
    param([string]$Level, [string]$Message, [hashtable]$Fields = @{})
    $ts     = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssZ")
    $fields = ($Fields.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join " "
    Write-Host "[$ts] [$Level] $Message $fields"
}

# ── Core provisioning function ────────────────────────────────────────────────

function Invoke-NewHireProvisioning {
    param([PSCustomObject]$Hire)

    $sam  = Get-SamAccountName -FullName $Hire.FullName
    $upn  = "$sam@company.corp"
    $ou   = "OU=$($Hire.Department),OU=Users,$DomainDN"

    Write-Log "INFO" "Starting provisioning" @{
        samaccount = $sam
        upn        = $upn
        department = $Hire.Department
        title      = $Hire.Title
    }

    # ── Step 1: Create AD account ──────────────────────────────────────────────
    $adParams = @{
        Name              = $Hire.FullName
        SamAccountName    = $sam
        UserPrincipalName = $upn
        Path              = $ou
        Department        = $Hire.Department
        Title             = $Hire.Title
        Manager           = $Hire.Manager
        AccountPassword   = (ConvertTo-SecureString "TempP@ss2026!" -AsPlainText -Force)
        Enabled           = $true
        ChangePasswordAtLogon = $true
    }

    if (-not $DryRun) {
        New-ADUser @adParams
        $adUser = Get-ADUser -Identity $sam -Properties ObjectGUID
        Write-Log "INFO" "AD user created" @{
            samaccount   = $sam
            object_guid  = $adUser.ObjectGUID
            department   = $Hire.Department
        }
    } else {
        Write-Log "INFO" "[DRY-RUN] Would create AD user" @{ samaccount = $sam }
    }

    # ── Step 2: Assign security groups ────────────────────────────────────────
    $groups = $DefaultGroups + ($DeptGroupMap[$Hire.Department] ?? @())
    foreach ($group in ($groups | Sort-Object -Unique)) {
        if (-not $DryRun) {
            Add-ADGroupMember -Identity $group -Members $sam
            Write-Log "INFO" "Added to group" @{
                samaccount = $sam
                group      = $group
                department = $Hire.Department
            }
        } else {
            Write-Log "INFO" "[DRY-RUN] Would add to group" @{ samaccount = $sam; group = $group }
        }
    }

    # ── Step 3: Provision M365 mailbox ────────────────────────────────────────
    if (-not $DryRun) {
        Enable-RemoteMailbox -Identity $upn -RemoteRoutingAddress "$sam@company.mail.onmicrosoft.com"
        Set-MailboxPlan -Identity $upn -MaxReceiveSize 100MB
        Write-Log "INFO" "M365 mailbox provisioned" @{
            upn          = $upn
            exchange_plan = $ExchangePlan
            department   = $Hire.Department
        }
    } else {
        Write-Log "INFO" "[DRY-RUN] Would provision mailbox" @{ upn = $upn }
    }

    Write-Log "INFO" "Provisioning complete" @{
        samaccount     = $sam
        upn            = $upn
        groups_assigned = ($groups | Sort-Object -Unique).Count
    }

    return [PSCustomObject]@{
        SamAccountName = $sam
        UPN            = $upn
        GroupsAssigned = ($groups | Sort-Object -Unique).Count
    }
}

# ── Main ──────────────────────────────────────────────────────────────────────

Write-Log "INFO" "New-HireProvisioning starting" @{ csv = $CsvPath; dry_run = $DryRun }

if (-not (Test-Path $CsvPath)) {
    Write-Log "ERROR" "CSV file not found" @{ path = $CsvPath }
    exit 1
}

$hires     = Import-Csv -Path $CsvPath
$succeeded = 0
$failed    = 0

foreach ($hire in $hires) {
    try {
        $result = Invoke-NewHireProvisioning -Hire $hire
        $succeeded++
        Write-Log "INFO" "Hire provisioned successfully" @{
            name = $hire.FullName
            upn  = $result.UPN
            groups = $result.GroupsAssigned
        }
    }
    catch {
        $failed++
        Write-Log "ERROR" "Provisioning failed" @{
            name  = $hire.FullName
            error = $_.Exception.Message
        }
    }
}

Write-Log "INFO" "New-HireProvisioning complete" @{
    total     = $hires.Count
    succeeded = $succeeded
    failed    = $failed
}

if ($failed -gt 0) {
    exit 1
}
