param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$CameraId = "camera_01",
    [string]$GpuPythonPath = "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe",
    [string]$VenvPythonPath = "",
    [string]$JsonOut = "",
    [switch]$FailOnCpuBinaryProvider
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

if (-not $VenvPythonPath) {
    $VenvPythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host "=== $Title ==="
}

function Format-Value($Value) {
    if ($null -eq $Value) {
        return "n/a"
    }
    return [string]$Value
}

function Write-KeyValue([string]$Key, $Value) {
    Write-Host ("{0}: {1}" -f $Key, (Format-Value $Value))
}

function Invoke-ProviderCheck([string]$Label, [string]$PythonPath) {
    Write-Section "$Label Python / ONNX Runtime"
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        Write-Host "missing: $PythonPath"
        return [PSCustomObject]@{
            label = $Label
            python_path = $PythonPath
            exists = $false
            error = "missing_python"
        }
    }

    $code = @'
import json
import sys

result = {
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "ort_version": None,
    "providers": [],
    "cuda_execution_provider": False,
    "error": None,
}
try:
    import onnxruntime as ort
    result["ort_version"] = ort.__version__
    result["providers"] = list(ort.get_available_providers())
    result["cuda_execution_provider"] = "CUDAExecutionProvider" in result["providers"]
except Exception as exc:
    result["error"] = repr(exc)
print(json.dumps(result, ensure_ascii=False))
'@

    $scriptPath = Join-Path ([System.IO.Path]::GetTempPath()) ("camera-service-provider-check-{0}.py" -f ([guid]::NewGuid().ToString("N")))
    $previousPythonPath = $env:PYTHONPATH
    try {
        Set-Content -LiteralPath $scriptPath -Value $code -Encoding UTF8
        $env:PYTHONPATH = if ($previousPythonPath) { "$ProjectRoot;$previousPythonPath" } else { $ProjectRoot }
        $raw = & $PythonPath $scriptPath
    } finally {
        $env:PYTHONPATH = $previousPythonPath
        Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
    }
    try {
        $parsed = ($raw | Select-Object -Last 1) | ConvertFrom-Json
    } catch {
        $parsed = [PSCustomObject]@{
            python_executable = $PythonPath
            python_version = $null
            ort_version = $null
            providers = @()
            cuda_execution_provider = $false
            error = "provider_check_parse_failed: $raw"
        }
    }

    Write-KeyValue "python_executable" $parsed.python_executable
    Write-KeyValue "python_version" $parsed.python_version
    Write-KeyValue "ort_version" $parsed.ort_version
    Write-KeyValue "providers" (($parsed.providers | ForEach-Object { [string]$_ }) -join ",")
    if ($parsed.error) {
        Write-KeyValue "error" $parsed.error
    }

    return [PSCustomObject]@{
        label = $Label
        python_path = $PythonPath
        exists = $true
        python_executable = $parsed.python_executable
        python_version = $parsed.python_version
        ort_version = $parsed.ort_version
        providers = @($parsed.providers)
        cuda_execution_provider = [bool]$parsed.cuda_execution_provider
        error = $parsed.error
    }
}

function Invoke-JsonGet([string]$Uri) {
    try {
        return [PSCustomObject]@{
            ok = $true
            uri = $Uri
            body = Invoke-RestMethod -Uri $Uri -TimeoutSec 5
            error = $null
        }
    } catch {
        Write-Host "unreachable: $Uri"
        Write-Host "error: $($_.Exception.Message)"
        return [PSCustomObject]@{
            ok = $false
            uri = $Uri
            body = $null
            error = $_.Exception.Message
        }
    }
}

function Get-NvidiaSummary {
    Write-Section "NVIDIA"
    try {
        $gpuLine = & nvidia-smi --query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0 -and $gpuLine) {
            Write-Host $gpuLine
            $parts = (($gpuLine | Select-Object -First 1) -split ",").Trim()
            return [PSCustomObject]@{
                available = $true
                raw = $gpuLine
                name = $parts[0]
                driver_version = $parts[1]
                utilization_gpu_percent = [double]$parts[2]
                memory_used_mib = [double]$parts[3]
                memory_total_mib = [double]$parts[4]
                error = $null
            }
        }
        Write-Host "nvidia-smi did not return GPU summary"
        return [PSCustomObject]@{
            available = $false
            raw = $gpuLine
            error = "nvidia_smi_empty"
        }
    } catch {
        Write-Host "nvidia-smi unavailable: $($_.Exception.Message)"
        return [PSCustomObject]@{
            available = $false
            raw = $null
            error = $_.Exception.Message
        }
    }
}

function Get-GpuComputeProcesses {
    Write-Section "GPU Compute Processes"
    try {
        $rows = & nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits 2>$null
        $items = @()
        if ($rows) {
            foreach ($row in $rows) {
                Write-Host $row
                $parts = ($row -split ",").Trim()
                $memory = if ($parts[2] -match "^\d+(\.\d+)?$") { [double]$parts[2] } else { $null }
                $items += [PSCustomObject]@{
                    pid = [int]$parts[0]
                    process_name = $parts[1]
                    used_memory_mib = $memory
                    raw = $row
                }
            }
        } else {
            Write-Host "no compute process reported"
        }
        return @($items)
    } catch {
        Write-Host "compute process query unavailable: $($_.Exception.Message)"
        return @([PSCustomObject]@{
            error = $_.Exception.Message
        })
    }
}

function Save-DiagnosisReport($Report, [string]$Path) {
    if (-not $Path) {
        return
    }
    $resolved = if ([System.IO.Path]::IsPathRooted($Path)) {
        $Path
    } else {
        Join-Path $ProjectRoot $Path
    }
    $parent = Split-Path -Parent $resolved
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $Report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $resolved -Encoding UTF8
    Write-Section "Saved"
    Write-Host "json_out=$resolved"
}

Push-Location $ProjectRoot
try {
    $gpuProvider = Invoke-ProviderCheck "GPU env" $GpuPythonPath
    $venvProvider = Invoke-ProviderCheck ".venv rollback" $VenvPythonPath
    $nvidia = Get-NvidiaSummary
    $computeProcesses = @(Get-GpuComputeProcesses)

    Write-Section "Service Health"
    $healthResponse = Invoke-JsonGet "$BaseUrl/healthz"
    if ($healthResponse.ok) {
        $healthResponse.body | ConvertTo-Json -Depth 8
    }

    Write-Section "Runtime Control"
    $controlResponse = Invoke-JsonGet "$BaseUrl/runtime-control/status?camera_id=$CameraId"
    $control = $controlResponse.body
    $runtime = $null
    if ($controlResponse.ok) {
        $runtime = $control.runtime
        Write-KeyValue "camera_id" $control.camera_id
        Write-KeyValue "server_ready" $control.server_ready
        Write-KeyValue "stream_connected" $control.stream_connected
        Write-KeyValue "manual_control_enabled" $control.manual_control_enabled
        Write-KeyValue "binary_enabled" $control.binary_enabled
        Write-KeyValue "binary_requested" $control.binary_requested
        Write-KeyValue "qwen_enabled" $control.qwen_enabled
        Write-KeyValue "qwen_requested" $control.qwen_requested
        Write-KeyValue "runtime.running" $runtime.running
        Write-KeyValue "binary_model_loaded" $runtime.binary_model_loaded
        Write-KeyValue "binary_provider" $runtime.binary_provider
        Write-KeyValue "binary_provider_degraded" $runtime.binary_provider_degraded
        Write-KeyValue "binary_provider_warning" $runtime.binary_provider_warning
        Write-KeyValue "binary_sample_fps" $runtime.binary_sample_fps
        Write-KeyValue "queue_depth" $runtime.queue_depth
        Write-KeyValue "frames_sampled" $runtime.frames_sampled
        Write-KeyValue "frames_processed" $runtime.frames_processed
        Write-KeyValue "frames_dropped" $runtime.frames_dropped
        Write-KeyValue "frame_age_ms" $runtime.frame_age_ms
        Write-KeyValue "binary_queue_delay_ms" $runtime.binary_queue_delay_ms
        Write-KeyValue "binary_inference_latency_avg_ms" $runtime.binary_inference_latency_avg_ms
        Write-KeyValue "last_error" $runtime.last_error
    }

    Write-Section "Streaming Status"
    $statusResponse = Invoke-JsonGet "$BaseUrl/status"
    $status = $statusResponse.body
    if ($statusResponse.ok) {
        $camera = $status.camera
        $streaming = $status.streaming
        Write-KeyValue "camera.connected" $camera.connected
        Write-KeyValue "camera.stream_state" $camera.stream_state
        Write-KeyValue "camera.frame_age_ms" $camera.frame_age_ms
        Write-KeyValue "camera.capture_fps" $camera.capture_fps
        Write-KeyValue "camera.capture_ipc_dropped_frames" $camera.capture_ipc_dropped_frames
        Write-KeyValue "streaming.webrtc_target_fps" $streaming.webrtc_target_fps
    }

    Write-Section "Diagnosis"
    $diagnosis = [ordered]@{
        service_status = "unknown"
        binary_provider_status = "unknown"
        binary_sample_fps_status = "unknown"
        queue_status = "unknown"
        hints = @()
    }
    $exitCode = 0

    if (-not $controlResponse.ok) {
        $diagnosis.service_status = "unreachable"
        $diagnosis.hints += "start the GPU service with .\scripts\start_visual_gpu.ps1, then reconnect the page"
        Write-Host "service_status=unreachable"
        Write-Host "hint=start the GPU service with .\scripts\start_visual_gpu.ps1, then reconnect the page"
    } else {
        $diagnosis.service_status = "reachable"

        if ($runtime -and $runtime.binary_provider -eq "CPUExecutionProvider") {
            $diagnosis.binary_provider_status = "CPU_FALLBACK"
            $diagnosis.hints += "this explains severe lag when binary is enabled; start with the GPU Conda Python or fix CUDA provider loading"
            Write-Host "binary_provider_status=CPU_FALLBACK"
            Write-Host "hint=this explains severe lag when binary is enabled; start with the GPU Conda Python or fix CUDA provider loading"
            if ($FailOnCpuBinaryProvider) {
                $exitCode = 2
            }
        } elseif ($runtime -and $runtime.binary_provider -eq "CUDAExecutionProvider") {
            $diagnosis.binary_provider_status = "CUDA_OK"
            Write-Host "binary_provider_status=CUDA_OK"
        } elseif ($runtime -and -not $runtime.binary_model_loaded) {
            $diagnosis.binary_provider_status = "not_loaded"
            $diagnosis.hints += "this is normal before manually enabling binary after the stream is connected"
            Write-Host "binary_provider_status=not_loaded"
            Write-Host "hint=this is normal before manually enabling binary after the stream is connected"
        } else {
            $diagnosis.binary_provider_status = "unknown"
            Write-Host "binary_provider_status=unknown"
        }

        if ($runtime -and $runtime.binary_sample_fps) {
            if ([double]$runtime.binary_sample_fps -gt 0) {
                $diagnosis.binary_sample_fps_status = "configured_positive"
                Write-Host "binary_sample_fps_status=configured_positive"
            } else {
                $diagnosis.binary_sample_fps_status = "unexpected"
                Write-Host "binary_sample_fps_status=unexpected"
            }
        }

        if ($runtime -and $null -ne $runtime.queue_depth -and [double]$runtime.queue_depth -gt 1) {
            $diagnosis.queue_status = "possible_backlog"
            Write-Host "queue_status=possible_backlog"
        } elseif ($runtime) {
            $diagnosis.queue_status = "latest_frame_queue_ok_or_idle"
            Write-Host "queue_status=latest_frame_queue_ok_or_idle"
        }
    }

    $report = [PSCustomObject]@{
        generated_at = (Get-Date).ToString("o")
        project_root = $ProjectRoot
        base_url = $BaseUrl
        camera_id = $CameraId
        gpu_python = $gpuProvider
        venv_python = $venvProvider
        nvidia = $nvidia
        gpu_compute_processes = @($computeProcesses)
        health = [PSCustomObject]@{
            ok = $healthResponse.ok
            uri = $healthResponse.uri
            body = $healthResponse.body
            error = $healthResponse.error
        }
        runtime_control = [PSCustomObject]@{
            ok = $controlResponse.ok
            uri = $controlResponse.uri
            body = $controlResponse.body
            error = $controlResponse.error
        }
        status = [PSCustomObject]@{
            ok = $statusResponse.ok
            uri = $statusResponse.uri
            body = $statusResponse.body
            error = $statusResponse.error
        }
        diagnosis = $diagnosis
    }

    Save-DiagnosisReport $report $JsonOut
    exit $exitCode
} finally {
    Pop-Location
}
