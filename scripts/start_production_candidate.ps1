param(
  [int]$Port = 8000,
  [string]$HostName = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Profile = Join-Path $Root "configs\production_candidate.env"
$RuntimeDir = Join-Path $Root "runtime"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir | Out-Null

python (Join-Path $Root "scripts\validate_config.py") --profile $Profile | Out-Host
if ($LASTEXITCODE -ne 0) {
  throw "Config validation failed for $Profile"
}

$env:VISION_SERVICE_ENV_FILE = $Profile
$StdoutLogPath = Join-Path $LogDir "vision_production_candidate.out.log"
$StderrLogPath = Join-Path $LogDir "vision_production_candidate.err.log"
$PidPath = Join-Path $RuntimeDir "vision_service.pid"
$Args = @("-m", "uvicorn", "app.main:app", "--host", $HostName, "--port", "$Port")

$Process = Start-Process -FilePath "python" `
  -ArgumentList $Args `
  -WorkingDirectory $Root `
  -RedirectStandardOutput $StdoutLogPath `
  -RedirectStandardError $StderrLogPath `
  -WindowStyle Hidden `
  -PassThru

Set-Content -Path $PidPath -Value $Process.Id -Encoding ASCII
Write-Host "Vision Service started. PID=$($Process.Id)"
Write-Host "Profile: $Profile"
Write-Host "Stdout log: $StdoutLogPath"
Write-Host "Stderr log: $StderrLogPath"
Write-Host "Status: http://127.0.0.1:$Port/status"
