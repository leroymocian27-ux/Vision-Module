param(
  [string]$PidFile = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $PidFile) {
  $PidFile = Join-Path $Root "runtime\vision_service.pid"
}

if (-not (Test-Path $PidFile)) {
  Write-Host "No PID file found: $PidFile"
  exit 0
}

$PidText = (Get-Content -Path $PidFile -Raw).Trim()
if (-not $PidText) {
  Remove-Item -Path $PidFile -Force
  Write-Host "Empty PID file removed."
  exit 0
}

$Process = Get-Process -Id ([int]$PidText) -ErrorAction SilentlyContinue
if ($null -eq $Process) {
  Remove-Item -Path $PidFile -Force
  Write-Host "Process already stopped. PID file removed."
  exit 0
}

Write-Host "Stopping Vision Service PID=$PidText"
Stop-Process -Id ([int]$PidText) -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$StillRunning = Get-Process -Id ([int]$PidText) -ErrorAction SilentlyContinue
if ($null -ne $StillRunning) {
  Write-Host "Force stopping Vision Service PID=$PidText"
  Stop-Process -Id ([int]$PidText) -Force
}

Remove-Item -Path $PidFile -Force
Write-Host "Vision Service stopped."

