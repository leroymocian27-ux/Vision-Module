param(
    [string]$Version = "fall-monitor-stable-v1.0-rc",
    [string]$OutputRoot = "artifacts\releases",
    [switch]$IncludeModels
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $releaseName = "${Version}_${timestamp}"
    $releaseRoot = Join-Path $OutputRoot $releaseName
    $releaseRoot = [System.IO.Path]::GetFullPath($releaseRoot)

    New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

    $dirs = @(
        "app",
        "frontend_demo",
        "identity_service",
        "robot_assist_service",
        "configs",
        "docs"
    )

    foreach ($dir in $dirs) {
        if (Test-Path $dir) {
            Copy-Item -Path $dir -Destination $releaseRoot -Recurse -Force
        }
    }

    $scriptDest = Join-Path $releaseRoot "scripts"
    New-Item -ItemType Directory -Force -Path $scriptDest | Out-Null
    $stableScripts = @(
        "validate_config.py",
        "run_stable_smoke.py",
        "process_cleanup_check.py",
        "run_startup_shutdown_gate.py",
        "run_camera_stream_gate.py",
        "start_safe_demo.ps1",
        "start_production_candidate.ps1",
        "stop_service.ps1",
        "status.ps1",
        "run_smoke.ps1",
        "build_release_bundle.ps1"
    )
    foreach ($script in $stableScripts) {
        $source = Join-Path "scripts" $script
        if (Test-Path $source) {
            Copy-Item -Path $source -Destination $scriptDest -Force
        }
    }

    foreach ($file in @("requirements.txt", "VERSION", "README.md")) {
        if (Test-Path $file) {
            Copy-Item -Path $file -Destination $releaseRoot -Force
        }
    }

    $runtimeDirs = @("logs", "runtime", "evidence", "artifacts")
    foreach ($dir in $runtimeDirs) {
        New-Item -ItemType Directory -Force -Path (Join-Path $releaseRoot $dir) | Out-Null
    }

    $manifestDir = Join-Path $releaseRoot "models"
    New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null
    $validationJson = "artifacts\stabilization\validate_safe_demo.json"
    if (Test-Path $validationJson) {
        $validation = Get-Content $validationJson -Raw | ConvertFrom-Json
        $validation.models | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $manifestDir "model_manifest.json")

        if ($IncludeModels) {
            foreach ($model in $validation.models) {
                if ($model.exists -and (Test-Path $model.path)) {
                    $destPath = Join-Path $releaseRoot $model.path
                    $destDir = Split-Path $destPath -Parent
                    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
                    Copy-Item -Path $model.path -Destination $destPath -Force
                }
            }
        }
    } else {
        @() | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $manifestDir "model_manifest.json")
    }

    pip freeze | Set-Content -Encoding UTF8 (Join-Path $releaseRoot "requirements.lock")

    $acceptanceSource = "artifacts\stable_smoke\20260720T021030Z"
    if (Test-Path $acceptanceSource) {
        $acceptanceDest = Join-Path $releaseRoot "artifacts\stable_smoke\20260720T021030Z"
        New-Item -ItemType Directory -Force -Path $acceptanceDest | Out-Null
        foreach ($file in @("summary.json", "summary.md", "status.json", "uvicorn.log", "latest-frame.jpg", "integration_latest.json")) {
            $source = Join-Path $acceptanceSource $file
            if (Test-Path $source) {
                Copy-Item -Path $source -Destination $acceptanceDest -Force
            }
        }
    }

    $s2EvidenceRelative = $null
    $s2Root = "artifacts\stabilization\S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY"
    if (Test-Path $s2Root) {
        $latestS2 = Get-ChildItem -Path $s2Root -Directory |
            Where-Object { Test-Path (Join-Path $_.FullName "summary.json") } |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($null -ne $latestS2) {
            $s2EvidenceRelative = "artifacts/stabilization/S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY/$($latestS2.Name)/summary.json"
            $s2Dest = Join-Path $releaseRoot "artifacts\stabilization\S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY\$($latestS2.Name)"
            New-Item -ItemType Directory -Force -Path (Split-Path $s2Dest -Parent) | Out-Null
            Copy-Item -Path $latestS2.FullName -Destination $s2Dest -Recurse -Force
        }
    }

    $s3EvidenceRelative = $null
    $s3Root = "artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE"
    if (Test-Path $s3Root) {
        $latestS3 = Get-ChildItem -Path $s3Root -Directory |
            Where-Object { Test-Path (Join-Path $_.FullName "summary.json") } |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($null -ne $latestS3) {
            $s3EvidenceRelative = "artifacts/stabilization/S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE/$($latestS3.Name)/summary.json"
            $s3Dest = Join-Path $releaseRoot "artifacts\stabilization\S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE\$($latestS3.Name)"
            New-Item -ItemType Directory -Force -Path (Split-Path $s3Dest -Parent) | Out-Null
            Copy-Item -Path $latestS3.FullName -Destination $s3Dest -Recurse -Force
        }
    }

    $manifest = [ordered]@{
        version = $Version
        created_at = (Get-Date).ToString("o")
        release_root = $releaseRoot
        include_models = [bool]$IncludeModels
        profile = "configs/safe_demo.env"
        smoke_evidence = "artifacts/stable_smoke/20260720T021030Z/summary.json"
        s2_startup_shutdown_evidence = $s2EvidenceRelative
        s3_camera_stream_evidence = $s3EvidenceRelative
        model_manifest = "models/model_manifest.json"
        safety_defaults = [ordered]@{
            real_delivery = "disabled"
            qwen_vlm = "disabled"
            robot_assist = "disabled"
            go2_control = "disabled"
        }
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $releaseRoot "release_manifest.json")

    Write-Host "Release bundle created:"
    Write-Host $releaseRoot
} finally {
    Pop-Location
}
