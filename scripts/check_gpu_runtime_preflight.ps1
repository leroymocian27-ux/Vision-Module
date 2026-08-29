param(
    [string]$GpuPythonPath = "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe",
    [string]$VenvPythonPath = "",
    [string]$OutputDir = "artifacts/environment_audit",
    [int]$Port = 8798,
    [switch]$SkipTempService
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$OutputRoot = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $ProjectRoot $OutputDir }
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

if (-not $VenvPythonPath) {
    $VenvPythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$reportPath = Join-Path $OutputRoot "gpu_runtime_preflight_$timestamp.json"
$safeDemoPath = Join-Path $OutputRoot "gpu_runtime_preflight_${timestamp}_safe_demo.json"
$diagnosisPath = Join-Path $OutputRoot "gpu_runtime_preflight_${timestamp}_diagnosis.json"
$stdoutPath = Join-Path $OutputRoot "gpu_runtime_preflight_${timestamp}_service.stdout.log"
$stderrPath = Join-Path $OutputRoot "gpu_runtime_preflight_${timestamp}_service.stderr.log"

function New-Check([string]$Name, [string]$Status, [string]$Summary, $Details = $null) {
    return [PSCustomObject]@{
        name = $Name
        status = $Status
        summary = $Summary
        details = $Details
    }
}

function Add-Check($Checks, [string]$Name, [string]$Status, [string]$Summary, $Details = $null) {
    $Checks.Add((New-Check $Name $Status $Summary $Details)) | Out-Null
    $mark = if ($Status -eq "PASS") { "PASS" } elseif ($Status -eq "SKIP") { "SKIP" } else { "FAIL" }
    Write-Host "[$mark] $Name - $Summary"
}

function Invoke-PythonJson([string]$PythonPath, [string]$Code) {
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        return [PSCustomObject]@{
            ok = $false
            error = "python_missing"
            python_path = $PythonPath
        }
    }
    $raw = & $PythonPath -c $Code
    if ($LASTEXITCODE -ne 0) {
        return [PSCustomObject]@{
            ok = $false
            error = "python_exit_$LASTEXITCODE"
            raw = $raw
            python_path = $PythonPath
        }
    }
    try {
        $parsed = ($raw | Select-Object -Last 1) | ConvertFrom-Json
        return [PSCustomObject]@{
            ok = $true
            body = $parsed
            raw = $raw
            python_path = $PythonPath
        }
    } catch {
        return [PSCustomObject]@{
            ok = $false
            error = "json_parse_failed: $($_.Exception.Message)"
            raw = $raw
            python_path = $PythonPath
        }
    }
}

function Wait-Health([string]$BaseUrl, [int]$TimeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri "$BaseUrl/healthz" -TimeoutSec 1 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

$providerCode = @'
import json
import sys

result = {
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "ort_version": None,
    "providers": [],
    "cuda_execution_provider": False,
    "torch_preload_error": None,
    "error": None,
}
try:
    try:
        import torch  # noqa: F401
    except Exception as exc:
        result["torch_preload_error"] = repr(exc)
    import onnxruntime as ort
    result["ort_version"] = ort.__version__
    result["providers"] = list(ort.get_available_providers())
    result["cuda_execution_provider"] = "CUDAExecutionProvider" in result["providers"]
except Exception as exc:
    result["error"] = repr(exc)
print(json.dumps(result, ensure_ascii=False))
'@

$dummyCode = @'
import hashlib
import json
import time
from pathlib import Path

import numpy as np

preload_error = None
try:
    import torch  # noqa: F401
except Exception as exc:
    preload_error = repr(exc)

import onnxruntime as ort

root = Path.cwd()
env = {}
for line in (root / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    key, value = stripped.split("=", 1)
    env[key.strip()] = value.strip().strip('"').strip("'")

model_path = root / env.get(
    "POST_FALL_V2_BINARY_MODEL_PATH",
    "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx",
)
expected_sha = env.get("POST_FALL_V2_BINARY_MODEL_SHA256", "").lower()
providers = [
    item.strip()
    for item in env.get("POST_FALL_V2_BINARY_ONNX_PROVIDERS", "CUDAExecutionProvider,CPUExecutionProvider").split(",")
    if item.strip()
]

result = {
    "model_path": str(model_path),
    "model_exists": model_path.is_file(),
    "sha256_ok": None,
    "requested_providers": providers,
    "available_providers": list(ort.get_available_providers()),
    "active_providers": [],
    "input": None,
    "latency_ms": None,
    "torch_preload_error": preload_error,
    "error": None,
}

try:
    if not model_path.is_file():
        raise FileNotFoundError(str(model_path))
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    result["sha256"] = digest
    result["sha256_ok"] = (not expected_sha) or digest.lower() == expected_sha
    if expected_sha and digest.lower() != expected_sha:
        raise RuntimeError(f"model sha256 mismatch: expected {expected_sha}, got {digest}")
    session = ort.InferenceSession(str(model_path), providers=providers)
    result["active_providers"] = list(session.get_providers())
    input_meta = session.get_inputs()[0]
    shape = [1 if not isinstance(dim, int) or dim <= 0 else dim for dim in input_meta.shape]
    result["input"] = {
        "name": input_meta.name,
        "shape": list(input_meta.shape),
        "resolved_shape": shape,
        "type": input_meta.type,
    }
    dummy = np.zeros(shape, dtype=np.float32)
    for _ in range(3):
        session.run(None, {input_meta.name: dummy})
    elapsed = []
    for _ in range(10):
        started = time.perf_counter()
        session.run(None, {input_meta.name: dummy})
        elapsed.append((time.perf_counter() - started) * 1000.0)
    result["latency_ms"] = {
        "count": len(elapsed),
        "avg": round(sum(elapsed) / len(elapsed), 3),
        "min": round(min(elapsed), 3),
        "max": round(max(elapsed), 3),
    }
except Exception as exc:
    result["error"] = repr(exc)

print(json.dumps(result, ensure_ascii=False))
'@

$appImportCode = @'
import json

result = {"app_import_ok": False, "error": None}
try:
    import app.main  # noqa: F401
    result["app_import_ok"] = True
except Exception as exc:
    result["error"] = repr(exc)
print(json.dumps(result, ensure_ascii=False))
'@

$checks = New-Object System.Collections.Generic.List[object]
$process = $null

Push-Location $ProjectRoot
try {
    Write-Host "GPU runtime preflight"
    Write-Host "project_root=$ProjectRoot"
    Write-Host "report_path=$reportPath"

    $gpuProvider = Invoke-PythonJson $GpuPythonPath $providerCode
    $gpuProviderOk = $gpuProvider.ok -and [bool]$gpuProvider.body.cuda_execution_provider
    Add-Check $checks "gpu_env_provider" $(if ($gpuProviderOk) { "PASS" } else { "FAIL" }) `
        $(if ($gpuProviderOk) { "GPU env exposes CUDAExecutionProvider" } else { "GPU env does not expose CUDAExecutionProvider" }) `
        $gpuProvider

    $venvProvider = Invoke-PythonJson $VenvPythonPath $providerCode
    $venvProviderOk = $venvProvider.ok
    Add-Check $checks "venv_provider_baseline" $(if ($venvProviderOk) { "PASS" } else { "FAIL" }) `
        $(if ($venvProviderOk) { ".venv provider baseline captured" } else { ".venv provider baseline failed" }) `
        $venvProvider

    $dummy = Invoke-PythonJson $GpuPythonPath $dummyCode
    $dummyOk = $dummy.ok -and $dummy.body.sha256_ok -and @($dummy.body.active_providers)[0] -eq "CUDAExecutionProvider" -and -not $dummy.body.error
    Add-Check $checks "efficientnet_cuda_dummy_inference" $(if ($dummyOk) { "PASS" } else { "FAIL" }) `
        $(if ($dummyOk) { "EfficientNet ONNX dummy inference uses CUDAExecutionProvider" } else { "EfficientNet ONNX dummy inference did not prove CUDA provider" }) `
        $dummy

    $appImport = Invoke-PythonJson $GpuPythonPath $appImportCode
    $appImportOk = $appImport.ok -and [bool]$appImport.body.app_import_ok
    Add-Check $checks "app_main_import" $(if ($appImportOk) { "PASS" } else { "FAIL" }) `
        $(if ($appImportOk) { "GPU env can import app.main" } else { "GPU env cannot import app.main" }) `
        $appImport

    $safeDemoOutput = & $GpuPythonPath scripts\validate_config.py --profile safe_demo --json-out $safeDemoPath
    $safeDemoOk = $LASTEXITCODE -eq 0
    Add-Check $checks "safe_demo_config" $(if ($safeDemoOk) { "PASS" } else { "FAIL" }) `
        $(if ($safeDemoOk) { "safe_demo config validation passed" } else { "safe_demo config validation failed" }) `
        ([PSCustomObject]@{ json_path = $safeDemoPath; output = $safeDemoOutput })

    $diagnosis = $null
    if ($SkipTempService) {
        Add-Check $checks "temporary_service_manual_control" "SKIP" "temporary service check skipped"
    } else {
        $baseUrl = "http://127.0.0.1:$Port"
        $process = Start-Process `
            -FilePath $GpuPythonPath `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
            -WorkingDirectory $ProjectRoot `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -PassThru `
            -WindowStyle Hidden

        $healthy = Wait-Health $baseUrl 30
        if ($healthy) {
            & (Join-Path $ProjectRoot "scripts\diagnose_gpu_runtime.ps1") -BaseUrl $baseUrl -JsonOut $diagnosisPath | Out-Host
            if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $diagnosisPath)) {
                $diagnosis = Get-Content -LiteralPath $diagnosisPath -Raw | ConvertFrom-Json
            }
        }
        $manualOk = $healthy `
            -and $diagnosis `
            -and $diagnosis.runtime_control.ok `
            -and -not [bool]$diagnosis.runtime_control.body.binary_enabled `
            -and -not [bool]$diagnosis.runtime_control.body.qwen_enabled `
            -and -not [bool]$diagnosis.runtime_control.body.runtime.running `
            -and -not [bool]$diagnosis.runtime_control.body.runtime.binary_model_loaded `
            -and [double]$diagnosis.runtime_control.body.runtime.binary_sample_fps -eq 3.0 `
            -and [double]$diagnosis.status.body.streaming.webrtc_target_fps -eq 15.0
        Add-Check $checks "temporary_service_manual_control" $(if ($manualOk) { "PASS" } else { "FAIL" }) `
            $(if ($manualOk) { "temporary service is ready but does not auto-enable binary/Qwen" } else { "temporary service manual-control preflight failed" }) `
            ([PSCustomObject]@{
                healthy = $healthy
                diagnosis_path = $diagnosisPath
                stdout_path = $stdoutPath
                stderr_path = $stderrPath
                diagnosis = $diagnosis
            })
    }

    $failed = @($checks | Where-Object { $_.status -eq "FAIL" })
    $overall = if ($failed.Count -eq 0) { "PASS" } else { "FAIL" }
    $report = [PSCustomObject]@{
        generated_at = (Get-Date).ToString("o")
        project_root = $ProjectRoot
        gpu_python_path = $GpuPythonPath
        venv_python_path = $VenvPythonPath
        output_dir = $OutputRoot
        status = $overall
        checks = @($checks.ToArray())
    }
    $report | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Host ""
    Write-Host "preflight_status=$overall"
    Write-Host "preflight_report=$reportPath"
    if ($overall -ne "PASS") {
        exit 1
    }
    exit 0
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit(5000) | Out-Null
    }
    Pop-Location
}
