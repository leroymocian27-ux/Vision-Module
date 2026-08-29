$ErrorActionPreference = "Stop"

$runtimeRoot = "E:\国赛\go2_video_portable_runtime_2026-08-21"
$ffmpeg = Join-Path $runtimeRoot "tools\ffmpeg\bin\ffmpeg.exe"
$stdout = Join-Path $env:TEMP "go2-mjpeg-rtsp-stdout.log"
$stderr = Join-Path $env:TEMP "go2-mjpeg-rtsp-stderr.log"
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "ffmpeg.exe" -and $_.CommandLine -match "8093/stream\.mjpg"
}

if ($existing) {
    $existing | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress
    exit 0
}

$arguments = @(
    "-hide_banner", "-loglevel", "info", "-fflags", "nobuffer", "-flags", "low_delay",
    "-f", "mpjpeg", "-i", "http://127.0.0.1:8093/stream.mjpg", "-an",
    "-vf", "fps=8,scale=-2:540", "-c:v", "libx264", "-preset", "veryfast",
    "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", "8", "-keyint_min", "8",
    "-sc_threshold", "0", "-b:v", "1200k", "-maxrate", "1500k", "-bufsize", "600k",
    "-rtsp_transport", "tcp", "-f", "rtsp", "rtsp://127.0.0.1:8554/go2_front"
)
$process = Start-Process -FilePath $ffmpeg -ArgumentList $arguments -WorkingDirectory $runtimeRoot `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru

[PSCustomObject]@{ process_id = $process.Id; state = "started" } | ConvertTo-Json -Compress
