param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath,
    [Parameter(Mandatory = $true)]
    [string]$Label,
    [int]$Port = 8770,
    [int]$DurationSeconds = 12,
    [string]$CameraId = "camera_01",
    [string]$SourceUrl = "mock://colorbars",
    [switch]$SkipBinary,
    [string]$OutputDir = "artifacts/environment_audit"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$OutputRoot = Join-Path $ProjectRoot $OutputDir
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$safeLabel = ($Label -replace '[^A-Za-z0-9_.-]', '_')
$stdout = Join-Path $OutputRoot "$safeLabel.stdout.log"
$stderr = Join-Path $OutputRoot "$safeLabel.stderr.log"
$summaryPath = Join-Path $OutputRoot "$safeLabel.summary.json"
$samplesPath = Join-Path $OutputRoot "$safeLabel.samples.json"
$nvidiaBeforePath = Join-Path $OutputRoot "$safeLabel.nvidia_before.txt"
$nvidiaAfterPath = Join-Path $OutputRoot "$safeLabel.nvidia_after.txt"

function Invoke-JsonPost($Uri, $Body) {
    Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body ($Body | ConvertTo-Json)
}

function Wait-Health($BaseUrl) {
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri "$BaseUrl/healthz" | Out-Null
            return
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }
    throw "service did not become healthy: $BaseUrl"
}

function Read-GpuSnapshot {
    try {
        $text = & nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits 2>$null
        $parts = ($text | Select-Object -First 1).Split(",").Trim()
        return @{
            utilization_gpu_percent = [double]$parts[0]
            memory_used_mib = [double]$parts[1]
        }
    } catch {
        return $null
    }
}

function Get-ProcessTreeIds([int]$RootPid) {
    $ids = New-Object System.Collections.Generic.List[int]
    $pending = New-Object System.Collections.Generic.Queue[int]
    $pending.Enqueue($RootPid)
    while ($pending.Count -gt 0) {
        $processId = $pending.Dequeue()
        if ($ids.Contains($processId)) {
            continue
        }
        $ids.Add($processId)
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$processId" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            $pending.Enqueue([int]$child.ProcessId)
        }
    }
    return @($ids)
}

function Get-ProcessTreeCpuSeconds([int]$RootPid) {
    $total = 0.0
    foreach ($processId in Get-ProcessTreeIds $RootPid) {
        try {
            $cpu = (Get-Process -Id $processId -ErrorAction Stop).CPU
            if ($null -ne $cpu) {
                $total += [double]$cpu
            }
        } catch {
        }
    }
    return $total
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

function Get-NumericValues($Items, [string]$PropertyName) {
    $values = @()
    foreach ($item in $Items) {
        $number = Convert-ToNullableDouble $item.$PropertyName
        if ($null -ne $number) {
            $values += $number
        }
    }
    return @($values)
}

function Measure-NumericValues($Values) {
    $items = @($Values | Where-Object { $null -ne $_ })
    if ($items.Count -eq 0) {
        return @{
            avg = $null
            min = $null
            max = $null
        }
    }
    $sum = 0.0
    foreach ($item in $items) {
        $sum += [double]$item
    }
    return @{
        avg = [Math]::Round($sum / $items.Count, 3)
        min = [Math]::Round(($items | Measure-Object -Minimum).Minimum, 3)
        max = [Math]::Round(($items | Measure-Object -Maximum).Maximum, 3)
    }
}

function Get-GpuNumericValues($Items, [string]$PropertyName) {
    $values = @()
    foreach ($item in $Items) {
        if ($null -eq $item.gpu) {
            continue
        }
        $number = Convert-ToNullableDouble $item.gpu.$PropertyName
        if ($null -ne $number) {
            $values += $number
        }
    }
    return @($values)
}

function Count-Above($Values, [double]$Threshold) {
    return @($Values | Where-Object { [double]$_ -gt $Threshold }).Count
}

function Measure-PropertyTrend($Items, [string]$PropertyName) {
    $points = @()
    $firstAt = $null
    foreach ($item in $Items) {
        $value = Convert-ToNullableDouble $item.$PropertyName
        if ($null -eq $value) {
            continue
        }
        try {
            $at = [datetime]$item.at
        } catch {
            continue
        }
        if ($null -eq $firstAt) {
            $firstAt = $at
        }
        $points += [PSCustomObject]@{
            t = [double](($at - $firstAt).TotalSeconds)
            v = [double]$value
        }
    }
    if ($points.Count -eq 0) {
        return @{
            first = $null
            last = $null
            delta = $null
            slope_per_second = $null
        }
    }
    if ($points.Count -eq 1) {
        return @{
            first = [Math]::Round($points[0].v, 3)
            last = [Math]::Round($points[0].v, 3)
            delta = 0.0
            slope_per_second = $null
        }
    }
    $sumT = 0.0
    $sumV = 0.0
    $sumTV = 0.0
    $sumT2 = 0.0
    foreach ($point in $points) {
        $sumT += $point.t
        $sumV += $point.v
        $sumTV += $point.t * $point.v
        $sumT2 += $point.t * $point.t
    }
    $n = [double]$points.Count
    $denominator = ($n * $sumT2) - ($sumT * $sumT)
    $slope = $null
    if ([Math]::Abs($denominator) -gt 0.000001) {
        $slope = (($n * $sumTV) - ($sumT * $sumV)) / $denominator
    }
    $first = [double]$points[0].v
    $last = [double]$points[-1].v
    return @{
        first = [Math]::Round($first, 3)
        last = [Math]::Round($last, 3)
        delta = [Math]::Round($last - $first, 3)
        slope_per_second = if ($null -eq $slope) { $null } else { [Math]::Round($slope, 3) }
    }
}

Push-Location $ProjectRoot
$process = $null
try {
    & nvidia-smi | Set-Content -LiteralPath $nvidiaBeforePath -Encoding UTF8
    $process = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

    $baseUrl = "http://127.0.0.1:$Port"
    Wait-Health $baseUrl

    $beforeStream = Invoke-RestMethod -Uri "$baseUrl/runtime-control/status?camera_id=$CameraId"
    Invoke-JsonPost "$baseUrl/stream/start" @{
        camera_id = $CameraId
        rtsp_url = $SourceUrl
        main_rtsp_url = $SourceUrl
        analysis_rtsp_url = $SourceUrl
    } | Out-Null
    Start-Sleep -Seconds 1
    $afterStream = Invoke-RestMethod -Uri "$baseUrl/runtime-control/status?camera_id=$CameraId"
    if (-not $SkipBinary) {
        Invoke-JsonPost "$baseUrl/runtime-control/binary" @{
            camera_id = $CameraId
            enabled = $true
        } | Out-Null
    }
    Start-Sleep -Seconds 2

    $samples = @()
    $cpuStart = Get-ProcessTreeCpuSeconds $process.Id
    $wallStart = Get-Date
    $deadline = $wallStart.AddSeconds($DurationSeconds)
    while ((Get-Date) -lt $deadline) {
        $control = Invoke-RestMethod -Uri "$baseUrl/runtime-control/status?camera_id=$CameraId"
        $status = Invoke-RestMethod -Uri "$baseUrl/status?camera_id=$CameraId"
        $runtime = $control.runtime
        $camera = @($status.cameras | Where-Object { $_.camera_id -eq $CameraId } | Select-Object -First 1)
        $samples += [PSCustomObject]@{
            at = (Get-Date).ToString("o")
            frames_sampled = $runtime.frames_sampled
            frames_processed = $runtime.frames_processed
            frames_dropped = $runtime.frames_dropped
            queue_depth = $runtime.queue_depth
            binary_provider = $runtime.binary_provider
            binary_provider_degraded = $runtime.binary_provider_degraded
            binary_inference_latency_ms = $runtime.binary_inference_latency_ms
            binary_inference_latency_avg_ms = $runtime.binary_inference_latency_avg_ms
            binary_queue_delay_ms = $runtime.binary_queue_delay_ms
            binary_frame_age_ms = $runtime.frame_age_ms
            camera_frame_age_ms = $camera.frame_age_ms
            capture_fps = $camera.capture_fps
            capture_ipc_dropped_frames = $camera.capture_ipc_dropped_frames
            gpu = Read-GpuSnapshot
        }
        Start-Sleep -Seconds 1
    }
    $cpuEnd = Get-ProcessTreeCpuSeconds $process.Id
    $wallEnd = Get-Date
    $elapsedSeconds = [Math]::Max(0.001, ($wallEnd - $wallStart).TotalSeconds)
    $cpuPercentTotal = (($cpuEnd - $cpuStart) / $elapsedSeconds / [Environment]::ProcessorCount) * 100.0
    $last = $samples[-1]
    $first = $samples[0]
    $sampleElapsedSeconds = [Math]::Max(0.001, (([datetime]$last.at) - ([datetime]$first.at)).TotalSeconds)
    $binaryFps = (($last.frames_processed - $first.frames_processed) / $sampleElapsedSeconds)
    $binaryAgeStats = Measure-NumericValues (Get-NumericValues $samples "binary_frame_age_ms")
    $binaryAgeTrend = Measure-PropertyTrend $samples "binary_frame_age_ms"
    $cameraAgeValues = Get-NumericValues $samples "camera_frame_age_ms"
    $cameraAgeStats = Measure-NumericValues $cameraAgeValues
    $cameraAgeTrend = Measure-PropertyTrend $samples "camera_frame_age_ms"
    $captureFpsStats = Measure-NumericValues (Get-NumericValues $samples "capture_fps")
    $queueDepthStats = Measure-NumericValues (Get-NumericValues $samples "queue_depth")
    $gpuUtilStats = Measure-NumericValues (Get-GpuNumericValues $samples "utilization_gpu_percent")
    $gpuMemoryStats = Measure-NumericValues (Get-GpuNumericValues $samples "memory_used_mib")
    & nvidia-smi | Set-Content -LiteralPath $nvidiaAfterPath -Encoding UTF8
    $afterBinary = Invoke-RestMethod -Uri "$baseUrl/runtime-control/status?camera_id=$CameraId"

    $summary = [PSCustomObject]@{
        label = $Label
        python_path = $PythonPath
        process_id = $process.Id
        duration_seconds = [Math]::Round($elapsedSeconds, 3)
        cpu_percent_total_machine = [Math]::Round($cpuPercentTotal, 3)
        before_stream_binary_loaded = $beforeStream.runtime.binary_model_loaded
        after_stream_binary_enabled = $afterStream.binary_enabled
        after_stream_binary_loaded = $afterStream.runtime.binary_model_loaded
        after_binary_enabled = $afterBinary.binary_enabled
        after_binary_loaded = $afterBinary.runtime.binary_model_loaded
        binary_provider = $last.binary_provider
        binary_provider_degraded = $last.binary_provider_degraded
        binary_fps = [Math]::Round($binaryFps, 3)
        frames_sampled = $last.frames_sampled
        frames_processed = $last.frames_processed
        frames_dropped = $last.frames_dropped
        binary_inference_latency_avg_ms = $last.binary_inference_latency_avg_ms
        binary_frame_age_ms = $last.binary_frame_age_ms
        binary_frame_age_avg_ms = $binaryAgeStats.avg
        binary_frame_age_max_ms = $binaryAgeStats.max
        binary_frame_age_first_ms = $binaryAgeTrend.first
        binary_frame_age_last_ms = $binaryAgeTrend.last
        binary_frame_age_delta_ms = $binaryAgeTrend.delta
        binary_frame_age_trend_ms_per_s = $binaryAgeTrend.slope_per_second
        camera_frame_age_ms = $last.camera_frame_age_ms
        camera_frame_age_avg_ms = $cameraAgeStats.avg
        camera_frame_age_max_ms = $cameraAgeStats.max
        camera_frame_age_first_ms = $cameraAgeTrend.first
        camera_frame_age_last_ms = $cameraAgeTrend.last
        camera_frame_age_delta_ms = $cameraAgeTrend.delta
        camera_frame_age_trend_ms_per_s = $cameraAgeTrend.slope_per_second
        camera_frame_age_over_300ms_count = Count-Above $cameraAgeValues 300
        camera_frame_age_over_1000ms_count = Count-Above $cameraAgeValues 1000
        capture_fps = $last.capture_fps
        capture_fps_avg = $captureFpsStats.avg
        capture_fps_min = $captureFpsStats.min
        capture_ipc_dropped_frames = $last.capture_ipc_dropped_frames
        queue_depth_max = $queueDepthStats.max
        gpu_utilization_avg_percent = $gpuUtilStats.avg
        gpu_utilization_max_percent = $gpuUtilStats.max
        gpu_memory_avg_mib = $gpuMemoryStats.avg
        gpu_memory_max_mib = $gpuMemoryStats.max
        webrtc_target_fps = (Invoke-RestMethod -Uri "$baseUrl/status?camera_id=$CameraId").streaming.webrtc_target_fps
        sample_count = $samples.Count
    }
    $samples | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $samplesPath -Encoding UTF8
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    $summary | ConvertTo-Json -Depth 8
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        Start-Sleep -Milliseconds 500
    }
    Pop-Location
}
