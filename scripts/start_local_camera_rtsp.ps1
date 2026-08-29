param(
    [string]$DeviceName = "HP True Vision FHD Camera",
    [string]$RtspUrl = "rtsp://127.0.0.1:8554/local_camera",
    [int]$Fps = 15,
    [string]$VideoSize = "640x480"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$mediaMtx = Join-Path $repoRoot ".local-tools\mediamtx\mediamtx.exe"
$mediaMtxDir = Split-Path -Parent $mediaMtx

if (-not (Test-Path -LiteralPath $mediaMtx)) {
    throw "MediaMTX not found: $mediaMtx"
}

$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$mediaMtxOut = Join-Path $env:TEMP "local-camera-mediamtx-stdout.log"
$mediaMtxErr = Join-Path $env:TEMP "local-camera-mediamtx-stderr.log"
$ffmpegOut = Join-Path $env:TEMP "local-camera-ffmpeg-stdout.log"
$ffmpegErr = Join-Path $env:TEMP "local-camera-ffmpeg-stderr.log"

$mediaMtxProcess = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "mediamtx.exe" -and $_.ExecutablePath -eq $mediaMtx
} | Select-Object -First 1

if (-not $mediaMtxProcess) {
    $startedMediaMtx = Start-Process -FilePath $mediaMtx -WorkingDirectory $mediaMtxDir `
        -RedirectStandardOutput $mediaMtxOut -RedirectStandardError $mediaMtxErr `
        -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $mediaMtxPid = $startedMediaMtx.Id
} else {
    $mediaMtxPid = $mediaMtxProcess.ProcessId
}

$escapedUrl = [regex]::Escape($RtspUrl)
$existingPublisher = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "ffmpeg.exe" -and $_.CommandLine -match $escapedUrl
} | Select-Object -First 1

if (-not $existingPublisher) {
    Remove-Item -LiteralPath $ffmpegOut, $ffmpegErr -ErrorAction SilentlyContinue
    $argLine = "-hide_banner -loglevel info -f dshow -rtbufsize 128M -framerate $Fps -video_size $VideoSize -i `"video=$DeviceName`" -an -vf `"fps=$Fps,scale=640:-2`" -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -g $Fps -keyint_min $Fps -sc_threshold 0 -b:v 1200k -maxrate 1500k -bufsize 600k -rtsp_transport tcp -f rtsp $RtspUrl"
    $startedPublisher = Start-Process -FilePath $ffmpeg -ArgumentList $argLine -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $ffmpegOut -RedirectStandardError $ffmpegErr `
        -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    $publisherPid = $startedPublisher.Id
} else {
    $publisherPid = $existingPublisher.ProcessId
}

[PSCustomObject]@{
    rtsp_url = $RtspUrl
    device_name = $DeviceName
    mediamtx_pid = $mediaMtxPid
    publisher_pid = $publisherPid
    mediamtx_log = $mediaMtxOut
    ffmpeg_log = $ffmpegErr
} | ConvertTo-Json -Compress
