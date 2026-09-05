[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8011,
    [string]$PythonPath = "E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe"
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$RuntimeRoot = Join-Path $ProjectRoot 'tmp_event_visual_qa\formal_demo_execution_20260718'
$PythonPath = (Resolve-Path $PythonPath).Path

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. The formal-demo instance was not started."
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

# These values are process-scoped and restored on exit. They never write .env.
$DemoEnvironment = @{
    'VISION_SERVICE_RUNTIME_PROFILE' = 'formal_demo_synthetic'
    'VISION_SERVICE_REQUIRE_CUDA' = 'true'
    'VISION_SERVICE_CUDA_PYTHON_PATH' = $PythonPath
    'POST_FALL_V2_BINARY_ONNX_PROVIDERS' = 'CUDAExecutionProvider,CPUExecutionProvider'
    'TEMPORAL_ONNX_PROVIDERS' = 'CUDAExecutionProvider,CPUExecutionProvider'
    'MOCK_CAMERA_ENABLED' = 'true'
    'DEFAULT_RTSP_URL' = ''
    'MAIN_STREAM_URL' = ''
    'ANALYSIS_STREAM_URL' = ''
    'DEVICE_DISCOVERY_ENABLED' = 'false'
    'ENABLE_POSE' = 'false'
    'MAIN_SYSTEM_ALERT_ENABLED' = 'false'
    'EVENT_PIPELINE_ENABLED' = 'true'
    'EVENT_RING_BUFFER_ENABLED' = 'true'
    'EVENT_WORKER_ENABLED' = 'true'
    'EVENT_SEMANTIC_ENABLED' = 'true'
    'EVENT_ARCHIVE_ENABLED' = 'true'
    'EVENT_ARCHIVE_DIR' = (Join-Path $RuntimeRoot 'archive')
    'EVENT_KEYFRAME_SERVING_ENABLED' = 'true'
    'EVENT_POST_KEYFRAME_COLLECTION_ENABLED' = 'false'
    'EVENT_OUTBOX_BACKEND' = 'sqlite'
    'EVENT_OUTBOX_SQLITE_PATH' = (Join-Path $RuntimeRoot 'event_outbox.sqlite3')
    'EVENT_DELIVERY_ENABLED' = 'true'
    'EVENT_DELIVERY_MODE' = 'dry_run'
    'EVENT_DELIVERY_BACKEND' = 'sqlite'
    'EVENT_DELIVERY_SQLITE_PATH' = (Join-Path $RuntimeRoot 'delivery_outbox.sqlite3')
    'EVENT_DELIVERY_WORKER_ENABLED' = 'false'
    'EVENT_VLM_ENABLED' = 'false'
    'EVENT_VLM_PROVIDER' = 'dummy'
}

$PreviousEnvironment = @{}
foreach ($Name in $DemoEnvironment.Keys) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
    [Environment]::SetEnvironmentVariable($Name, $DemoEnvironment[$Name], 'Process')
}

$ExitCode = 0
try {
    Write-Host "Starting loopback-only synthetic formal demo on http://127.0.0.1:$Port"
    Write-Host 'No .env file is changed. Delivery is dry-run; VLM and main-system alerts are disabled.'
    & $PythonPath -m uvicorn app.main:app --host 127.0.0.1 --port $Port
    $ExitCode = $LASTEXITCODE
}
finally {
    foreach ($Name in $DemoEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $PreviousEnvironment[$Name], 'Process')
    }
}

exit $ExitCode
