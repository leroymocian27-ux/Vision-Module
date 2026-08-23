param(
  [int]$Port = 8000,
  [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$BaseUrl = "http://$HostName`:$Port"

Write-Host "Health:"
try {
  Invoke-RestMethod "$BaseUrl/healthz" -TimeoutSec 3 | ConvertTo-Json -Depth 8
} catch {
  Write-Host "healthz failed: $($_.Exception.Message)"
}

Write-Host "`nStatus:"
try {
  $Status = Invoke-RestMethod "$BaseUrl/status" -TimeoutSec 5
  $Summary = [ordered]@{
    camera = $Status.camera.stream_state
    frame_age_ms = $Status.camera.frame_age_ms
    capture_fps = $Status.camera.capture_fps
    detection_running = $Status.detection.running
    detection_loaded = $Status.detection.loaded
    tracking_objects = $Status.tracking.tracked_objects_count
    pose_enabled = $Status.pose.pose_enabled
    temporal_enabled = $Status.temporal.enabled
    latest_fall_state = $Status.latest_result.fall_state
    latest_risk_level = $Status.latest_result.risk_level
  }
  $Summary | ConvertTo-Json -Depth 8
} catch {
  Write-Host "status failed: $($_.Exception.Message)"
}

