param(
  [int]$Port = 8000,
  [string]$HostName = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Profile = Join-Path $Root "configs\safe_demo.env"
$Python = "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe"
$RuntimeDir = Join-Path $Root "runtime"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir | Out-Null

& $Python (Join-Path $Root "scripts\validate_config.py") --profile $Profile | Out-Host
if ($LASTEXITCODE -ne 0) {
  throw "Config validation failed for $Profile"
}

$env:VISION_SERVICE_ENV_FILE = $Profile
$env:VISION_SERVICE_REQUIRE_CUDA = "true"
$env:VISION_SERVICE_CUDA_PYTHON_PATH = $Python
$env:POST_FALL_V2_BINARY_ONNX_PROVIDERS = "CUDAExecutionProvider,CPUExecutionProvider"
$env:TEMPORAL_ONNX_PROVIDERS = "CUDAExecutionProvider,CPUExecutionProvider"
$StdoutLogPath = Join-Path $LogDir "vision_safe_demo.out.log"
$StderrLogPath = Join-Path $LogDir "vision_safe_demo.err.log"
$PidPath = Join-Path $RuntimeDir "vision_service.pid"
$Args = @("-m", "uvicorn", "app.main:app", "--host", $HostName, "--port", "$Port")

$Process = Start-Process -FilePath $Python `
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
Write-Host "Demo: http://127.0.0.1:$Port/demo"
