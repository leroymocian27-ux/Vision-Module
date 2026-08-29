param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Python = "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "GPU Python not found: $Python"
}

if (-not $env:POST_FALL_V2_BINARY_ONNX_PROVIDERS) {
    $env:POST_FALL_V2_BINARY_ONNX_PROVIDERS = "CUDAExecutionProvider,CPUExecutionProvider"
}

Push-Location $ProjectRoot
try {
    $providerCheck = @'
import os
import sys
import onnxruntime as ort

providers = ort.get_available_providers()
requested = os.getenv("POST_FALL_V2_BINARY_ONNX_PROVIDERS", "CUDAExecutionProvider,CPUExecutionProvider")
requires_cuda = "CUDAExecutionProvider" in [part.strip() for part in requested.split(",") if part.strip()]
print("ONNX Runtime providers:", providers)
print("POST_FALL_V2_BINARY_ONNX_PROVIDERS:", requested)
print("CUDAExecutionProvider available:", "CUDAExecutionProvider" in providers)
if requires_cuda and "CUDAExecutionProvider" not in providers:
    print("WARNING: CUDAExecutionProvider was requested, but this Python environment cannot provide it.", file=sys.stderr)
    print("WARNING: Binary classification would run on CPU and may make realtime video lag badly.", file=sys.stderr)
    sys.exit(2)
'@
    $providerCheckPath = Join-Path ([System.IO.Path]::GetTempPath()) ("camera-service-provider-check-{0}.py" -f ([guid]::NewGuid().ToString("N")))
    try {
        Set-Content -LiteralPath $providerCheckPath -Value $providerCheck -Encoding ASCII
        & $Python $providerCheckPath
        if ($LASTEXITCODE -ne 0) {
            throw "ONNX Runtime provider check failed."
        }
    } finally {
        Remove-Item -LiteralPath $providerCheckPath -Force -ErrorAction SilentlyContinue
    }
    & $Python -m uvicorn app.main:app --host $HostName --port $Port
} finally {
    Pop-Location
}
