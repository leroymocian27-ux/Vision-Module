param(
    [Parameter(Mandatory = $true)]
    [string]$SourceUrl,
    [string]$CameraId = "camera_01",
    [int]$DurationSeconds = 300,
    [string]$LabelPrefix = "real_rtsp",
    [string]$OutputDir = "artifacts/environment_audit",
    [string]$GpuPythonPath = "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe",
    [string]$VenvPythonPath = "",
    [int]$GpuPort = 8780,
    [int]$VenvPort = 8781,
    [int]$VideoOnlyPort = 8782,
    [double]$MinCpuDropPercent = 50.0,
    [double]$MinBinaryFps = 2.4,
    [double]$MaxBinaryFps = 3.4,
    [double]$MaxFrameAgeAvgMs = 300.0,
    [double]$MaxFrameAgeTrendMsPerSecond = 5.0,
    [int]$MinTrendSampleCount = 10,
    [double]$MaxQueueDepth = 1.0,
    [switch]$SkipCpuBaseline,
    [switch]$SkipVideoOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$RuntimeBenchmark = Join-Path $ProjectRoot "scripts\benchmark_runtime.ps1"
$OutputRoot = Join-Path $ProjectRoot $OutputDir
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

if (-not $VenvPythonPath) {
    $VenvPythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $RuntimeBenchmark)) {
    throw "benchmark_runtime.ps1 not found: $RuntimeBenchmark"
}
if (-not (Test-Path -LiteralPath $GpuPythonPath)) {
    throw "GPU Python not found: $GpuPythonPath"
}
if (-not $SkipCpuBaseline -and -not (Test-Path -LiteralPath $VenvPythonPath)) {
    throw ".venv Python not found: $VenvPythonPath"
}

function Get-SafeLabel([string]$Label) {
    return ($Label -replace '[^A-Za-z0-9_.-]', '_')
}

function Get-SummaryPath([string]$Label) {
    $safeLabel = Get-SafeLabel $Label
    return Join-Path $OutputRoot "$safeLabel.summary.json"
}

function Invoke-OneBenchmark(
    [string]$Scenario,
    [string]$PythonPath,
    [string]$Label,
    [int]$Port,
    [switch]$SkipBinary
) {
    Write-Host ""
    Write-Host "=== $Scenario ==="
    $params = @{
        PythonPath = $PythonPath
        Label = $Label
        Port = $Port
        DurationSeconds = $DurationSeconds
        CameraId = $CameraId
        SourceUrl = $SourceUrl
        OutputDir = $OutputDir
    }
    if ($SkipBinary) {
        $params.SkipBinary = $true
    }
    $benchmarkOutput = & $RuntimeBenchmark @params
    if ($LASTEXITCODE -ne 0) {
        throw "benchmark failed: $Scenario"
    }
    $summaryPath = Get-SummaryPath $Label
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        throw "summary not found after benchmark: $summaryPath"
    }
    return Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
}

function Format-Metric($Value, [string]$Suffix = "") {
    if ($null -eq $Value) {
        return "n/a"
    }
    return "$Value$Suffix"
}

function Convert-ToNullableDouble($Value) {
    if ($null -eq $Value) {
        return $null
    }
    try {
        return [double]$Value
    } catch {
        return $null
    }
}

function Add-ComparisonRow($Rows, [string]$Metric, $VideoOnly, $Cpu, $Gpu, [string]$Property, [string]$Suffix = "") {
    $Rows.Add([PSCustomObject]@{
        metric = $Metric
        video_only_gpu = if ($null -eq $VideoOnly) { "n/a" } else { Format-Metric $VideoOnly.$Property $Suffix }
        venv_cpu = if ($null -eq $Cpu) { "n/a" } else { Format-Metric $Cpu.$Property $Suffix }
        conda_gpu = if ($null -eq $Gpu) { "n/a" } else { Format-Metric $Gpu.$Property $Suffix }
    })
}

function New-AcceptanceCheck([string]$Name, [string]$Status, [string]$Expected, [string]$Actual) {
    return [PSCustomObject]@{
        name = $Name
        status = $Status
        expected = $Expected
        actual = $Actual
    }
}

function Get-NullableDouble($Object, [string]$PropertyName) {
    if ($null -eq $Object) {
        return $null
    }
    return Convert-ToNullableDouble $Object.$PropertyName
}

function Test-WithinRange($Value, [double]$Min, [double]$Max) {
    if ($null -eq $Value) {
        return $null
    }
    return ([double]$Value -ge $Min -and [double]$Value -le $Max)
}

function Build-AcceptanceChecks($VideoOnly, $Cpu, $Gpu, $CpuDropPercent) {
    $checks = New-Object System.Collections.Generic.List[object]

    if ($null -eq $Gpu) {
        $checks.Add((New-AcceptanceCheck "GPU binary scenario completed" "FAIL" "Conda GPU binary benchmark summary exists" "missing"))
        return $checks.ToArray()
    }

    $binaryEnabled = [bool]$Gpu.after_binary_enabled
    $binaryLoaded = [bool]$Gpu.after_binary_loaded
    $checks.Add((New-AcceptanceCheck `
        "Binary manually enabled after stream" `
        $(if ($binaryEnabled -and $binaryLoaded) { "PASS" } else { "FAIL" }) `
        "after_binary_enabled=true and after_binary_loaded=true" `
        "after_binary_enabled=$($Gpu.after_binary_enabled), after_binary_loaded=$($Gpu.after_binary_loaded)"))

    $providerOk = ($Gpu.binary_provider -eq "CUDAExecutionProvider" -and -not [bool]$Gpu.binary_provider_degraded)
    $checks.Add((New-AcceptanceCheck `
        "EfficientNet active provider" `
        $(if ($providerOk) { "PASS" } else { "FAIL" }) `
        "CUDAExecutionProvider without degraded fallback" `
        "provider=$($Gpu.binary_provider), degraded=$($Gpu.binary_provider_degraded)"))

    $binaryFps = Get-NullableDouble $Gpu "binary_fps"
    $binaryFpsOk = Test-WithinRange $binaryFps $MinBinaryFps $MaxBinaryFps
    $checks.Add((New-AcceptanceCheck `
        "Binary sampling rate" `
        $(if ($null -eq $binaryFpsOk) { "UNKNOWN" } elseif ($binaryFpsOk) { "PASS" } else { "FAIL" }) `
        "$MinBinaryFps <= binary_fps <= $MaxBinaryFps, preserving POST_FALL_V2_SAMPLE_FPS=3" `
        "binary_fps=$binaryFps"))

    $queueDepth = Get-NullableDouble $Gpu "queue_depth_max"
    $queueOk = if ($null -eq $queueDepth) { $null } else { [double]$queueDepth -le $MaxQueueDepth }
    $checks.Add((New-AcceptanceCheck `
        "Binary latest-frame queue" `
        $(if ($null -eq $queueOk) { "UNKNOWN" } elseif ($queueOk) { "PASS" } else { "FAIL" }) `
        "queue_depth_max <= $MaxQueueDepth" `
        "queue_depth_max=$queueDepth"))

    $cameraAgeAvg = Get-NullableDouble $Gpu "camera_frame_age_avg_ms"
    $cameraAgeTrend = Get-NullableDouble $Gpu "camera_frame_age_trend_ms_per_s"
    $gpuSampleCount = Get-NullableDouble $Gpu "sample_count"
    $hasEnoughTrendSamples = ($null -ne $gpuSampleCount -and [double]$gpuSampleCount -ge $MinTrendSampleCount)
    $cameraAgeOk = if ($null -eq $cameraAgeAvg -or $null -eq $cameraAgeTrend -or -not $hasEnoughTrendSamples) {
        $null
    } else {
        ([double]$cameraAgeAvg -le $MaxFrameAgeAvgMs -and [double]$cameraAgeTrend -le $MaxFrameAgeTrendMsPerSecond)
    }
    $checks.Add((New-AcceptanceCheck `
        "Camera frame age stability" `
        $(if ($null -eq $cameraAgeOk) { "UNKNOWN" } elseif ($cameraAgeOk) { "PASS" } else { "FAIL" }) `
        "sample_count >= $MinTrendSampleCount, camera_frame_age_avg_ms <= $MaxFrameAgeAvgMs, trend <= $MaxFrameAgeTrendMsPerSecond ms/s" `
        "sample_count=$gpuSampleCount, avg=$cameraAgeAvg ms, trend=$cameraAgeTrend ms/s"))

    $binaryAgeTrend = Get-NullableDouble $Gpu "binary_frame_age_trend_ms_per_s"
    $binaryAgeOk = if ($null -eq $binaryAgeTrend -or -not $hasEnoughTrendSamples) { $null } else { [double]$binaryAgeTrend -le $MaxFrameAgeTrendMsPerSecond }
    $checks.Add((New-AcceptanceCheck `
        "Binary input frame age stability" `
        $(if ($null -eq $binaryAgeOk) { "UNKNOWN" } elseif ($binaryAgeOk) { "PASS" } else { "FAIL" }) `
        "sample_count >= $MinTrendSampleCount and binary_frame_age_trend_ms_per_s <= $MaxFrameAgeTrendMsPerSecond" `
        "sample_count=$gpuSampleCount, trend=$binaryAgeTrend ms/s"))

    if ($null -eq $Cpu) {
        $checks.Add((New-AcceptanceCheck `
            "CPU pressure reduction" `
            "UNKNOWN" `
            "requires .venv CPU baseline and Conda GPU binary scenario" `
            ".venv CPU baseline was skipped or unavailable"))
    } else {
        $cpuDropOk = ($null -ne $CpuDropPercent -and [double]$CpuDropPercent -ge $MinCpuDropPercent)
        $checks.Add((New-AcceptanceCheck `
            "CPU pressure reduction" `
            $(if ($cpuDropOk) { "PASS" } else { "FAIL" }) `
            "CPU drop from .venv CPU binary to Conda GPU binary >= $MinCpuDropPercent%" `
            "drop=$CpuDropPercent%, cpu_baseline=$($Cpu.cpu_percent_total_machine)%, gpu=$($Gpu.cpu_percent_total_machine)%"))
    }

    if ($null -eq $VideoOnly) {
        $checks.Add((New-AcceptanceCheck `
            "Video-only baseline" `
            "UNKNOWN" `
            "GPU video-only benchmark should exist for same RTSP source" `
            "video-only scenario was skipped or unavailable"))
    } else {
        $checks.Add((New-AcceptanceCheck `
            "Video-only baseline" `
            "PASS" `
            "GPU video-only benchmark summary exists" `
            "capture_fps_avg=$($VideoOnly.capture_fps_avg), camera_frame_age_avg_ms=$($VideoOnly.camera_frame_age_avg_ms)"))
    }

    return $checks.ToArray()
}

function Get-OverallAcceptanceStatus($Checks) {
    $items = @($Checks)
    if (($items | Where-Object { $_.status -eq "FAIL" }).Count -gt 0) {
        return "FAIL"
    }
    if (($items | Where-Object { $_.status -eq "UNKNOWN" }).Count -gt 0) {
        return "UNKNOWN"
    }
    return "PASS"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$prefix = "$(Get-SafeLabel $LabelPrefix)_$timestamp"
$videoOnlySummary = $null
$cpuSummary = $null
$gpuSummary = $null

Push-Location $ProjectRoot
try {
    if (-not $SkipVideoOnly) {
        $videoOnlySummary = Invoke-OneBenchmark `
            -Scenario "GPU runtime, video only" `
            -PythonPath $GpuPythonPath `
            -Label "${prefix}_gpu_video_only" `
            -Port $VideoOnlyPort `
            -SkipBinary
    }

    if (-not $SkipCpuBaseline) {
        $cpuSummary = Invoke-OneBenchmark `
            -Scenario ".venv CPU binary baseline" `
            -PythonPath $VenvPythonPath `
            -Label "${prefix}_venv_cpu_binary" `
            -Port $VenvPort
    }

    $gpuSummary = Invoke-OneBenchmark `
        -Scenario "Conda GPU binary" `
        -PythonPath $GpuPythonPath `
        -Label "${prefix}_conda_gpu_binary" `
        -Port $GpuPort
} finally {
    Pop-Location
}

$rows = New-Object System.Collections.Generic.List[object]
Add-ComparisonRow $rows "CPU total" $videoOnlySummary $cpuSummary $gpuSummary "cpu_percent_total_machine" "%"
Add-ComparisonRow $rows "GPU utilization avg" $videoOnlySummary $cpuSummary $gpuSummary "gpu_utilization_avg_percent" "%"
Add-ComparisonRow $rows "GPU memory max" $videoOnlySummary $cpuSummary $gpuSummary "gpu_memory_max_mib" " MiB"
Add-ComparisonRow $rows "Binary provider" $videoOnlySummary $cpuSummary $gpuSummary "binary_provider"
Add-ComparisonRow $rows "Binary provider degraded" $videoOnlySummary $cpuSummary $gpuSummary "binary_provider_degraded"
Add-ComparisonRow $rows "Binary FPS" $videoOnlySummary $cpuSummary $gpuSummary "binary_fps"
Add-ComparisonRow $rows "Inference latency avg" $videoOnlySummary $cpuSummary $gpuSummary "binary_inference_latency_avg_ms" " ms"
Add-ComparisonRow $rows "Binary frame age avg" $videoOnlySummary $cpuSummary $gpuSummary "binary_frame_age_avg_ms" " ms"
Add-ComparisonRow $rows "Binary frame age max" $videoOnlySummary $cpuSummary $gpuSummary "binary_frame_age_max_ms" " ms"
Add-ComparisonRow $rows "Binary frame age delta" $videoOnlySummary $cpuSummary $gpuSummary "binary_frame_age_delta_ms" " ms"
Add-ComparisonRow $rows "Binary frame age trend" $videoOnlySummary $cpuSummary $gpuSummary "binary_frame_age_trend_ms_per_s" " ms/s"
Add-ComparisonRow $rows "Camera frame age avg" $videoOnlySummary $cpuSummary $gpuSummary "camera_frame_age_avg_ms" " ms"
Add-ComparisonRow $rows "Camera frame age max" $videoOnlySummary $cpuSummary $gpuSummary "camera_frame_age_max_ms" " ms"
Add-ComparisonRow $rows "Camera frame age delta" $videoOnlySummary $cpuSummary $gpuSummary "camera_frame_age_delta_ms" " ms"
Add-ComparisonRow $rows "Camera frame age trend" $videoOnlySummary $cpuSummary $gpuSummary "camera_frame_age_trend_ms_per_s" " ms/s"
Add-ComparisonRow $rows "Camera age >300ms samples" $videoOnlySummary $cpuSummary $gpuSummary "camera_frame_age_over_300ms_count"
Add-ComparisonRow $rows "Capture FPS avg" $videoOnlySummary $cpuSummary $gpuSummary "capture_fps_avg"
Add-ComparisonRow $rows "Capture FPS min" $videoOnlySummary $cpuSummary $gpuSummary "capture_fps_min"
Add-ComparisonRow $rows "IPC dropped" $videoOnlySummary $cpuSummary $gpuSummary "capture_ipc_dropped_frames"
Add-ComparisonRow $rows "Queue depth max" $videoOnlySummary $cpuSummary $gpuSummary "queue_depth_max"
Add-ComparisonRow $rows "WebRTC target FPS" $videoOnlySummary $cpuSummary $gpuSummary "webrtc_target_fps"

$cpuDropPercent = $null
if ($null -ne $cpuSummary -and $null -ne $gpuSummary -and $cpuSummary.cpu_percent_total_machine -gt 0) {
    $cpuDropPercent = [Math]::Round((($cpuSummary.cpu_percent_total_machine - $gpuSummary.cpu_percent_total_machine) / $cpuSummary.cpu_percent_total_machine) * 100.0, 3)
}
$acceptanceChecks = Build-AcceptanceChecks $videoOnlySummary $cpuSummary $gpuSummary $cpuDropPercent
$acceptanceStatus = Get-OverallAcceptanceStatus $acceptanceChecks

$comparison = [PSCustomObject]@{
    label_prefix = $LabelPrefix
    created_at = (Get-Date).ToString("o")
    camera_id = $CameraId
    duration_seconds = $DurationSeconds
    source_url_redacted = "<redacted>"
    gpu_python_path = $GpuPythonPath
    venv_python_path = if ($SkipCpuBaseline) { $null } else { $VenvPythonPath }
    video_only_gpu = $videoOnlySummary
    venv_cpu_binary = $cpuSummary
    conda_gpu_binary = $gpuSummary
    cpu_drop_percent_from_venv_to_gpu = $cpuDropPercent
    acceptance_status = $acceptanceStatus
    acceptance_thresholds = [PSCustomObject]@{
        min_cpu_drop_percent = $MinCpuDropPercent
        min_binary_fps = $MinBinaryFps
        max_binary_fps = $MaxBinaryFps
        max_frame_age_avg_ms = $MaxFrameAgeAvgMs
        max_frame_age_trend_ms_per_second = $MaxFrameAgeTrendMsPerSecond
        min_trend_sample_count = $MinTrendSampleCount
        max_queue_depth = $MaxQueueDepth
    }
    acceptance_checks = $acceptanceChecks
    rows = $rows
}

$comparisonPath = Join-Path $OutputRoot "$prefix.comparison.json"
$markdownPath = Join-Path $OutputRoot "$prefix.comparison.md"
$comparison | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $comparisonPath -Encoding UTF8

$markdown = New-Object System.Collections.Generic.List[string]
$markdown.Add("# Real RTSP Runtime Comparison")
$markdown.Add("")
$markdown.Add("- Created: $($comparison.created_at)")
$markdown.Add('- Camera: `' + $CameraId + '`')
$markdown.Add('- Duration per scenario: `' + $DurationSeconds + '` seconds')
$markdown.Add('- Source URL: `<redacted>`')
$markdown.Add('- GPU Python: `' + $GpuPythonPath + '`')
if (-not $SkipCpuBaseline) {
    $markdown.Add('- .venv Python: `' + $VenvPythonPath + '`')
}
$markdown.Add("")
$markdown.Add("| Metric | GPU video only | .venv CPU binary | Conda GPU binary |")
$markdown.Add("| --- | ---: | ---: | ---: |")
foreach ($row in $rows) {
    $markdown.Add("| $($row.metric) | $($row.video_only_gpu) | $($row.venv_cpu) | $($row.conda_gpu) |")
}
if ($null -ne $cpuDropPercent) {
    $markdown.Add("")
    $markdown.Add('CPU drop from `.venv` CPU binary to Conda GPU binary: `' + $cpuDropPercent + '%`.')
}
$markdown.Add("")
$markdown.Add("## Acceptance")
$markdown.Add("")
$markdown.Add("- Overall: ``$acceptanceStatus``")
$markdown.Add("")
$markdown.Add("| Check | Status | Expected | Actual |")
$markdown.Add("| --- | --- | --- | --- |")
foreach ($check in $acceptanceChecks) {
    $markdown.Add("| $($check.name) | $($check.status) | $($check.expected) | $($check.actual) |")
}
$markdown.Add("")
$markdown.Add("Acceptance notes:")
$markdown.Add("")
$markdown.Add('- `binary_provider` should be `CUDAExecutionProvider` in the Conda GPU binary scenario.')
$markdown.Add('- `binary_fps` should remain close to `POST_FALL_V2_SAMPLE_FPS=3`.')
$markdown.Add('- `camera_frame_age_avg_ms`, `camera_frame_age_max_ms`, `camera_frame_age_delta_ms`, and `camera_frame_age_trend_ms_per_s` should not show a growing backlog.')
$markdown.Add('- Keep the generated per-scenario `.samples.json` files for frame-age trend inspection.')
$markdown | Set-Content -LiteralPath $markdownPath -Encoding UTF8

Write-Host ""
Write-Host "Comparison JSON: $comparisonPath"
Write-Host "Comparison Markdown: $markdownPath"
$comparison | ConvertTo-Json -Depth 10
