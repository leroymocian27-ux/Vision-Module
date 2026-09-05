param(
    [string]$Model = "qwen3.5:4b",
    [string]$ExpectedGpuName = "NVIDIA GeForce RTX 5060",
    [string]$OllamaExe = "E:\Ollama\app\ollama.exe",
    [string]$LogPath = "$env:LOCALAPPDATA\Ollama\server.log",
    [string]$Since = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

function Write-SectionLine {
    param([string]$Text)
    Write-Host $Text
}

function To-Seconds {
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

function Resolve-OllamaLogPath {
    param([string]$RequestedPath)
    if ($RequestedPath -and (Split-Path -Leaf $RequestedPath) -like "ollama_cuda_stderr_*.log" -and (Test-Path -LiteralPath $RequestedPath)) {
        return $RequestedPath
    }
    $candidates = @()
    if ($RequestedPath -and (Test-Path -LiteralPath $RequestedPath)) {
        $candidates += Get-Item -LiteralPath $RequestedPath
    }
    $controlledLogs = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "logs") -Filter "ollama_cuda_stderr_*.log" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($controlledLogs.Count -gt 0) {
        $candidates += $controlledLogs[0]
    }
    if ($candidates.Count -gt 0) {
        return ($candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    }
    return $RequestedPath
}

function Get-LogWindow {
    param(
        [string]$Path,
        [string]$SinceText
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Ollama server log not found: $Path"
    }
    $lines = Get-Content -LiteralPath $Path -ErrorAction Stop
    if ($lines.Count -eq 0) {
        return @()
    }

    if ($SinceText.Trim()) {
        $sinceTime = [DateTimeOffset]::Parse($SinceText)
        $startIndex = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^time=([^\s]+)') {
                try {
                    $lineTime = [DateTimeOffset]::Parse($Matches[1])
                } catch {
                    continue
                }
                if ($lineTime -ge $sinceTime) {
                    $startIndex = $i
                    break
                }
            }
        }
        if ($startIndex -ge 0) {
            return $lines[$startIndex..($lines.Count - 1)]
        }
        return @()
    }

    $lastServerConfig = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match 'msg="server config"') {
            $lastServerConfig = $i
        }
    }
    if ($lastServerConfig -ge 0) {
        return $lines[$lastServerConfig..($lines.Count - 1)]
    }

    $take = [Math]::Min(2000, $lines.Count)
    return $lines[($lines.Count - $take)..($lines.Count - 1)]
}

function Get-LastMatchingLine {
    param(
        [string[]]$Lines,
        [string]$Pattern
    )
    for ($i = $Lines.Count - 1; $i -ge 0; $i--) {
        if ($Lines[$i] -match $Pattern) {
            return $Lines[$i]
        }
    }
    return ""
}

function Fail-Preflight {
    param(
        [string]$Reason,
        [string]$Detected,
        [string]$OllamaPs,
        [string]$NvidiaSmi,
        [string]$BackendLine,
        [string]$OffloadLine,
        [string]$EffectiveLogPath
    )
    Write-SectionLine "======================================="
    Write-SectionLine "Ollama CUDA Preflight FAILED"
    Write-SectionLine "======================================="
    Write-SectionLine ""
    Write-SectionLine "Expected:"
    Write-SectionLine "NVIDIA CUDA on $ExpectedGpuName"
    Write-SectionLine ""
    Write-SectionLine "Detected:"
    Write-SectionLine $Detected
    Write-SectionLine ""
    Write-SectionLine "Reason:"
    Write-SectionLine $Reason
    Write-SectionLine ""
    Write-SectionLine "Model:"
    Write-SectionLine $Model
    Write-SectionLine ""
    Write-SectionLine "Backend log line:"
    Write-SectionLine ($(if ($BackendLine) { $BackendLine } else { "not found" }))
    Write-SectionLine ""
    Write-SectionLine "Layer offload log line:"
    Write-SectionLine ($(if ($OffloadLine) { $OffloadLine } else { "not found" }))
    Write-SectionLine ""
    Write-SectionLine "Log path:"
    Write-SectionLine ($(if ($EffectiveLogPath) { $EffectiveLogPath } else { "not found" }))
    Write-SectionLine ""
    Write-SectionLine "ollama ps:"
    Write-SectionLine ($(if ($OllamaPs) { $OllamaPs.TrimEnd() } else { "not available" }))
    Write-SectionLine ""
    Write-SectionLine "nvidia-smi:"
    Write-SectionLine ($(if ($NvidiaSmi) { $NvidiaSmi.TrimEnd() } else { "not available" }))
    Write-SectionLine ""
    Write-SectionLine "Qwen service will NOT be started."
    Write-SectionLine "======================================="
    exit 1
}

$effectiveLogPath = Resolve-OllamaLogPath -RequestedPath $LogPath

$ollamaPs = ""
try {
    $ollamaPs = (& $OllamaExe ps 2>&1 | Out-String)
} catch {
    $ollamaPs = $_.Exception.Message
}

$nvidiaSmi = ""
try {
    $nvidiaSmi = (& nvidia-smi 2>&1 | Out-String)
} catch {
    $nvidiaSmi = $_.Exception.Message
}

$logLines = @(Get-LogWindow -Path $effectiveLogPath -SinceText $Since)
$logText = ($logLines -join "`n")

$modelLine = ""
foreach ($line in ($ollamaPs -split "`r?`n")) {
    if ($line -match [regex]::Escape($Model)) {
        $modelLine = $line
        break
    }
}
$backendLine = Get-LastMatchingLine -Lines $logLines -Pattern 'msg="inference compute"'
if (-not $backendLine) {
    $backendLine = Get-LastMatchingLine -Lines $logLines -Pattern 'library=CUDA|library=Vulkan|library=CPU'
}
$offloadLine = Get-LastMatchingLine -Lines $logLines -Pattern 'offloaded\s+\d+/\d+\s+layers\s+to\s+GPU'
$timeoutLine = Get-LastMatchingLine -Lines $logLines -Pattern 'GPU discovery watchdog timed out'

$modelLoadedInPs = [bool]$modelLine
$processorGpu = ($modelLine -match '100%\s+GPU')
$expectedGpuVisible = ($nvidiaSmi -match [regex]::Escape($ExpectedGpuName))
$backendIsCuda = ($backendLine -match 'library=CUDA' -and $backendLine -match [regex]::Escape($ExpectedGpuName))
$backendIsForbidden = (
    $backendLine -match 'library=Vulkan|library=CPU' -or
    $logText -match 'library=Vulkan|Vulkan0|Vulkan1|Intel\(R\) RaptorLake|RaptorLake-S|CLIP using Vulkan'
)
$offloadComplete = $false
if ($offloadLine -match 'offloaded\s+(\d+)/(\d+)\s+layers\s+to\s+GPU') {
    $offloadComplete = ([int]$Matches[1] -eq [int]$Matches[2] -and [int]$Matches[2] -ge 34)
}

if (-not $modelLoadedInPs) {
    Fail-Preflight -Reason "Model is not loaded according to ollama ps." -Detected "model_not_loaded" -OllamaPs $ollamaPs -NvidiaSmi $nvidiaSmi -BackendLine $backendLine -OffloadLine $offloadLine -EffectiveLogPath $effectiveLogPath
}
if (-not $processorGpu) {
    Fail-Preflight -Reason "ollama ps does not report 100% GPU for the model." -Detected "not_100_percent_gpu" -OllamaPs $ollamaPs -NvidiaSmi $nvidiaSmi -BackendLine $backendLine -OffloadLine $offloadLine -EffectiveLogPath $effectiveLogPath
}
if (-not $expectedGpuVisible) {
    Fail-Preflight -Reason "Expected NVIDIA GPU is not visible to nvidia-smi." -Detected "expected_gpu_not_visible" -OllamaPs $ollamaPs -NvidiaSmi $nvidiaSmi -BackendLine $backendLine -OffloadLine $offloadLine -EffectiveLogPath $effectiveLogPath
}
if ($backendIsForbidden) {
    Fail-Preflight -Reason "Forbidden backend/device appeared in the latest Ollama log window." -Detected "Vulkan, Intel iGPU, or CPU fallback" -OllamaPs $ollamaPs -NvidiaSmi $nvidiaSmi -BackendLine $backendLine -OffloadLine $offloadLine -EffectiveLogPath $effectiveLogPath
}
if (-not $backendIsCuda) {
    $reason = "Latest Ollama log window does not prove library=CUDA on the expected RTX GPU."
    if ($timeoutLine) {
        $reason = "$reason GPU discovery watchdog timeout was also observed: $timeoutLine"
    }
    Fail-Preflight -Reason $reason -Detected "CUDA backend not verified" -OllamaPs $ollamaPs -NvidiaSmi $nvidiaSmi -BackendLine $backendLine -OffloadLine $offloadLine -EffectiveLogPath $effectiveLogPath
}
if (-not $offloadComplete) {
    Fail-Preflight -Reason "Model layers were not verified as fully offloaded to GPU." -Detected "missing_or_partial_gpu_offload" -OllamaPs $ollamaPs -NvidiaSmi $nvidiaSmi -BackendLine $backendLine -OffloadLine $offloadLine -EffectiveLogPath $effectiveLogPath
}
if ($timeoutLine -and -not $backendIsCuda) {
    Fail-Preflight -Reason "GPU discovery watchdog timed out and CUDA did not become the active backend." -Detected "cuda_discovery_timeout" -OllamaPs $ollamaPs -NvidiaSmi $nvidiaSmi -BackendLine $backendLine -OffloadLine $offloadLine -EffectiveLogPath $effectiveLogPath
}

Write-SectionLine "======================================="
Write-SectionLine "Ollama CUDA Preflight PASS"
Write-SectionLine "======================================="
Write-SectionLine ""
Write-SectionLine "GPU:"
Write-SectionLine $ExpectedGpuName
Write-SectionLine ""
Write-SectionLine "Backend:"
Write-SectionLine "CUDA"
Write-SectionLine ""
Write-SectionLine "Model:"
Write-SectionLine $Model
Write-SectionLine ""
Write-SectionLine "Model memory:"
Write-SectionLine "100% GPU"
Write-SectionLine ""
Write-SectionLine "Layers:"
Write-SectionLine $offloadLine
Write-SectionLine ""
Write-SectionLine "Backend log line:"
Write-SectionLine $backendLine
Write-SectionLine ""
Write-SectionLine "Log path:"
Write-SectionLine $effectiveLogPath
Write-SectionLine ""
Write-SectionLine "Vulkan:"
Write-SectionLine "DISABLED / NOT USED"
Write-SectionLine ""
Write-SectionLine "Intel iGPU:"
Write-SectionLine "NOT USED"
Write-SectionLine ""
Write-SectionLine "ollama ps:"
Write-SectionLine $ollamaPs.TrimEnd()
Write-SectionLine ""
Write-SectionLine "Status:"
Write-SectionLine "READY"
Write-SectionLine "======================================="
exit 0
