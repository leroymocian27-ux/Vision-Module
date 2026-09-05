param(
    [string]$Model = "qwen3.5:4b",
    [string]$ExpectedGpuName = "NVIDIA GeForce RTX 5060",
    [string]$OllamaExe = "E:\Ollama\app\ollama.exe",
    [string]$OllamaLibRoot = "E:\Ollama\app\lib\ollama",
    [string]$CudaLibrary = "cuda_v12",
    [string]$ModelsDir = "E:\Ollama\models",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 11434,
    [switch]$SkipWarmup
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$LogsDir = Join-Path $ProjectRoot "logs"
$CheckScript = Join-Path $ProjectRoot "tools\check_ollama_cuda.ps1"
$OllamaAppRoot = Split-Path -Parent $OllamaExe
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StdoutLog = Join-Path $LogsDir "ollama_cuda_stdout_$RunStamp.log"
$StderrLog = Join-Path $LogsDir "ollama_cuda_stderr_$RunStamp.log"
$WarmupJson = Join-Path $LogsDir "ollama_cuda_warmup_$RunStamp.json"

function Fail-Start {
    param([string]$Reason)
    Write-Host "======================================="
    Write-Host "Ollama CUDA Startup FAILED"
    Write-Host "======================================="
    Write-Host ""
    Write-Host "Expected:"
    Write-Host "NVIDIA CUDA on $ExpectedGpuName"
    Write-Host ""
    Write-Host "Reason:"
    Write-Host $Reason
    Write-Host ""
    Write-Host "Qwen service will NOT be started."
    Write-Host "======================================="
    exit 1
}

function Stop-LocalOllamaProcesses {
    param([string]$AppRoot)
    $normalizedRoot = [System.IO.Path]::GetFullPath($AppRoot).TrimEnd('\')
    $processes = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -in @("ollama", "ollama app", "llama-server")
    }
    foreach ($process in $processes) {
        $path = $null
        try {
            $path = $process.Path
        } catch {
            $path = $null
        }
        if (-not $path) {
            continue
        }
        $normalizedPath = [System.IO.Path]::GetFullPath($path)
        if ($normalizedPath.StartsWith($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "Stopping existing Ollama process: PID=$($process.Id) Name=$($process.ProcessName) Path=$normalizedPath"
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-ForOllama {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing -Method Head -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function New-WarmupPayload {
    param(
        [string]$ModelName,
        [string[]]$ImagePaths
    )
    $images = @()
    foreach ($imagePath in $ImagePaths) {
        if (-not (Test-Path -LiteralPath $imagePath)) {
            Fail-Start "Warmup image not found: $imagePath"
        }
        $images += [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($imagePath))
    }
    $content = @{
        schema_version = "pfv2_post_fall_input.compact_v2"
        prompt_version = "compact_v2"
        task = "Review three time-ordered keyframes and decide whether this is a real fall. Return JSON only."
        keyframes = @(
            @{ offset_ms = -1000; role = "pre_fall" },
            @{ offset_ms = -500; role = "pre_fall" },
            @{ offset_ms = 0; role = "trigger" }
        )
        keyframe_status = "complete"
        missing_offsets_ms = @()
        review_mode = "initial_review"
        constraints = @(
            "Return a JSON object only.",
            "Do not output paths, URLs, RTSP addresses, credentials, or identities.",
            "Use only visible image evidence."
        )
        profile = "compact_v2"
    } | ConvertTo-Json -Depth 8 -Compress

    return @{
        model = $ModelName
        stream = $false
        think = $false
        keep_alive = -1
        options = @{
            num_ctx = 2048
            num_predict = 96
            temperature = 0
        }
        messages = @(
            @{
                role = "system"
                content = "Review an eldercare fall candidate using only visible image evidence. Return JSON only."
            },
            @{
                role = "user"
                content = $content
                images = $images
            }
        )
    }
}

function Get-SecondsFromNs {
    param($Value)
    if ($null -eq $Value) {
        return $null
    }
    try {
        return [math]::Round(([double]$Value) / 1000000000.0, 3)
    } catch {
        return $null
    }
}

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

if (-not (Test-Path -LiteralPath $OllamaExe)) {
    Fail-Start "Ollama executable not found: $OllamaExe"
}
if (-not (Test-Path -LiteralPath $CheckScript)) {
    Fail-Start "CUDA check script not found: $CheckScript"
}

$cudaBackendDir = Join-Path $OllamaLibRoot $CudaLibrary
$cudaDll = Join-Path $cudaBackendDir "ggml-cuda.dll"
if (-not (Test-Path -LiteralPath $cudaBackendDir)) {
    Fail-Start "Requested CUDA backend directory not found: $cudaBackendDir"
}
if (-not (Test-Path -LiteralPath $cudaDll)) {
    Fail-Start "Requested CUDA backend DLL not found: $cudaDll"
}

$availableBackends = Get-ChildItem -LiteralPath $OllamaLibRoot -Directory -ErrorAction Stop | Select-Object -ExpandProperty Name
Write-Host "Available Ollama backends: $($availableBackends -join ', ')"
Write-Host "Selected CUDA backend: $CudaLibrary"

$nvidiaList = (& nvidia-smi -L 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    Fail-Start "nvidia-smi -L failed: $nvidiaList"
}
if ($nvidiaList -notmatch [regex]::Escape($ExpectedGpuName)) {
    Fail-Start "Expected GPU was not found by nvidia-smi -L. Output: $nvidiaList"
}
if ($nvidiaList -notmatch 'UUID:\s*(GPU-[^)]+)') {
    Fail-Start "Could not parse NVIDIA GPU UUID from nvidia-smi -L. Output: $nvidiaList"
}
$gpuUuid = $Matches[1]
Write-Host "Selected GPU UUID: $gpuUuid"

$portOwners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($ownerPid in $portOwners) {
    $owner = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    if ($null -eq $owner) {
        continue
    }
    $ownerPath = $null
    try {
        $ownerPath = $owner.Path
    } catch {
        $ownerPath = $null
    }
    if ($owner.ProcessName -notin @("ollama", "ollama app") -or -not $ownerPath -or -not ([System.IO.Path]::GetFullPath($ownerPath).StartsWith([System.IO.Path]::GetFullPath($OllamaAppRoot), [System.StringComparison]::OrdinalIgnoreCase))) {
        Fail-Start "Port $Port is already owned by a non-controlled process: PID=$ownerPid Name=$($owner.ProcessName) Path=$ownerPath"
    }
}

Stop-LocalOllamaProcesses -AppRoot $OllamaAppRoot
Start-Sleep -Seconds 2

$env:OLLAMA_HOST = "$HostName`:$Port"
$env:OLLAMA_LLM_LIBRARY = $CudaLibrary
$env:OLLAMA_VULKAN = "0"
$env:GGML_VK_VISIBLE_DEVICES = "-1"
$env:CUDA_VISIBLE_DEVICES = $gpuUuid
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_MODELS = $ModelsDir

$startTime = [DateTimeOffset]::Now.AddSeconds(-1)
Write-Host "Starting controlled Ollama serve with process-scoped CUDA environment..."
Write-Host "OLLAMA_LLM_LIBRARY=$env:OLLAMA_LLM_LIBRARY"
Write-Host "OLLAMA_VULKAN=$env:OLLAMA_VULKAN"
Write-Host "GGML_VK_VISIBLE_DEVICES=$env:GGML_VK_VISIBLE_DEVICES"
Write-Host "CUDA_VISIBLE_DEVICES=$env:CUDA_VISIBLE_DEVICES"

$process = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WorkingDirectory $OllamaAppRoot -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog -PassThru
$baseUrl = "http://$HostName`:$Port"
if (-not (Wait-ForOllama -BaseUrl $baseUrl -TimeoutSeconds 45)) {
    Fail-Start "Ollama did not listen on $baseUrl within 45 seconds. PID=$($process.Id). stderr=$StderrLog"
}

Write-Host "Ollama is listening on $baseUrl"

$warmupResult = $null
if (-not $SkipWarmup) {
    $workspaceRoot = Split-Path -Parent $ProjectRoot
    $warmupDir = Join-Path $workspaceRoot "event\qwen\confirm\pfv2-go2_front_camera-7932c5da5cf3"
    $warmupImages = @(
        (Join-Path $warmupDir "01_-1000ms_pre_fall.jpg"),
        (Join-Path $warmupDir "02_-0500ms_pre_fall.jpg"),
        (Join-Path $warmupDir "03_+0000ms_trigger.jpg")
    )
    $payload = New-WarmupPayload -ModelName $Model -ImagePaths $warmupImages
    Write-Host "Running real 3-image Qwen warmup request..."
    $requestStarted = Get-Date
    try {
        $warmupResult = Invoke-RestMethod -Uri "$baseUrl/api/chat" -Method Post -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec 180
    } catch {
        Fail-Start "3-image Qwen warmup request failed: $($_.Exception.Message)"
    }
    $requestMs = [math]::Round(((Get-Date) - $requestStarted).TotalMilliseconds, 3)
    $warmupResult | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $WarmupJson -Encoding ASCII
    Write-Host "Warmup request wall time ms: $requestMs"
    Write-Host "Warmup prompt_eval seconds: $(Get-SecondsFromNs $warmupResult.prompt_eval_duration)"
    Write-Host "Warmup eval seconds: $(Get-SecondsFromNs $warmupResult.eval_duration)"
    Write-Host "Warmup total seconds: $(Get-SecondsFromNs $warmupResult.total_duration)"
    Write-Host "Warmup response saved: $WarmupJson"
}

Write-Host "Running hard CUDA verification from latest Ollama logs..."
& $CheckScript -Model $Model -ExpectedGpuName $ExpectedGpuName -OllamaExe $OllamaExe -LogPath $StderrLog -Since $startTime.ToString("o")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "======================================="
Write-Host "Ollama CUDA Startup READY"
Write-Host "======================================="
Write-Host "GPU: $ExpectedGpuName"
Write-Host "GPU UUID: $gpuUuid"
Write-Host "Backend: CUDA ($CudaLibrary)"
Write-Host "Vulkan: DISABLED"
Write-Host "Port: $baseUrl"
if ($warmupResult) {
    Write-Host "Real 3-image prompt_eval seconds: $(Get-SecondsFromNs $warmupResult.prompt_eval_duration)"
    Write-Host "Real 3-image eval seconds: $(Get-SecondsFromNs $warmupResult.eval_duration)"
    Write-Host "Real 3-image total seconds: $(Get-SecondsFromNs $warmupResult.total_duration)"
}
Write-Host "======================================="
exit 0
