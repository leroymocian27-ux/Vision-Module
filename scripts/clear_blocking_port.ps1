param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$AllowAnyProcess,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

function Test-AddressMatch {
    param([string]$LocalAddress, [string]$RequestedHost)

    if ($RequestedHost -eq "0.0.0.0" -or $RequestedHost -eq "::") {
        return $true
    }
    if ($LocalAddress -eq $RequestedHost) {
        return $true
    }
    if ($LocalAddress -eq "0.0.0.0" -or $LocalAddress -eq "::") {
        return $true
    }
    return $false
}

$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Where-Object { Test-AddressMatch -LocalAddress $_.LocalAddress -RequestedHost $HostName }

if (-not $connections) {
    Write-Host "No listening process blocks $HostName`:$Port."
    exit 0
}

$processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
$blocked = @()

foreach ($processId in $processIds) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    $commandLine = if ($cim) { [string]$cim.CommandLine } else { "" }
    $processName = if ($process) { [string]$process.ProcessName } else { "unknown" }
    $path = if ($process -and $process.Path) { [string]$process.Path } else { "" }
    $safeToStop = $AllowAnyProcess -or
        $commandLine.Contains("uvicorn app.main:app") -or
        $commandLine.Contains($ProjectRoot) -or
        ($processName -eq "python" -and $commandLine.Contains("uvicorn"))

    Write-Host "Found PID $processId on $HostName`:$Port"
    Write-Host "  Process: $processName"
    if ($path) {
        Write-Host "  Path: $path"
    }
    if ($commandLine) {
        Write-Host "  CommandLine: $commandLine"
    }

    if (-not $safeToStop) {
        $blocked += $processId
        Write-Warning "Skipped PID $processId because it does not look like this service. Re-run with -AllowAnyProcess to stop it."
        continue
    }

    if ($DryRun) {
        Write-Host "  DryRun: would stop PID $processId."
        continue
    }

    Stop-Process -Id $processId -Force
    Write-Host "  Stopped PID $processId."
}

if ($DryRun) {
    Write-Host "DryRun complete. Re-run without -DryRun to clear $HostName`:$Port."
    exit 0
}

Start-Sleep -Milliseconds 300
$remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Where-Object { Test-AddressMatch -LocalAddress $_.LocalAddress -RequestedHost $HostName }

if ($remaining) {
    $remainingPids = ($remaining | Select-Object -ExpandProperty OwningProcess -Unique) -join ","
    throw "Port $HostName`:$Port is still blocked by PID(s): $remainingPids"
}

if ($blocked.Count -gt 0) {
    throw "Port $HostName`:$Port still has skipped non-service PID(s): $($blocked -join ',')"
}

Write-Host "Port $HostName`:$Port is clear."
