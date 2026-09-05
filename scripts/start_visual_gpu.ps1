param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$SkipOllamaCudaPreflight
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Python = "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "GPU Python not found: $Python"
}

$env:PYTHONPATH = $ProjectRoot
$env:VISION_SERVICE_REQUIRE_CUDA = "true"
$env:VISION_SERVICE_CUDA_PYTHON_PATH = $Python
$env:POST_FALL_V2_BINARY_ONNX_PROVIDERS = "CUDAExecutionProvider,CPUExecutionProvider"
$env:TEMPORAL_ONNX_PROVIDERS = "CUDAExecutionProvider,CPUExecutionProvider"
$env:YOLO_DEVICE = "cuda:0"
$env:YOLO_FALL_DEVICE = "cuda:0"
$env:YOLO_POSE_DEVICE = "cuda:0"
$env:YOLO11_POSE_DEVICE = "cuda:0"

Push-Location $ProjectRoot
try {
    function Get-DotEnvValue {
        param(
            [string]$Path,
            [string]$Name,
            [string]$Default = ""
        )
        if (-not (Test-Path -LiteralPath $Path)) {
            return $Default
        }
        $line = Get-Content -LiteralPath $Path | Where-Object {
            $_ -match "^\s*$([regex]::Escape($Name))\s*="
        } | Select-Object -Last 1
        if (-not $line) {
            return $Default
        }
        return (($line -split "=", 2)[1]).Trim().Trim('"').Trim("'")
    }

    $envPath = Join-Path $ProjectRoot ".env"
    $qwenEnabled = (Get-DotEnvValue -Path $envPath -Name "POST_FALL_V2_QWEN_ENABLED" -Default "false").ToLowerInvariant()
    $qwenProvider = (Get-DotEnvValue -Path $envPath -Name "POST_FALL_V2_QWEN_PROVIDER" -Default "").ToLowerInvariant()
    if (-not $SkipOllamaCudaPreflight -and $qwenEnabled -in @("1", "true", "yes", "on") -and $qwenProvider -eq "qwen_keyframe") {
        $ollamaCudaStart = Join-Path $ProjectRoot "tools\start_ollama_cuda.ps1"
        if (-not (Test-Path -LiteralPath $ollamaCudaStart)) {
            throw "Qwen CUDA backend unavailable. Expected NVIDIA CUDA but startup script is missing: $ollamaCudaStart"
        }
        & $ollamaCudaStart
        if ($LASTEXITCODE -ne 0) {
            throw "Qwen CUDA backend unavailable. Expected NVIDIA CUDA but CUDA verification failed. Vulkan fallback is disabled."
        }
    }

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
