# API_MAPPING

| UI module | Real endpoint/source | Real fields | Refresh mode |
|---|---|---|---|
| Header stream status | `/status?camera_id=...` | `cameras[].stream_state`, `cameras[].frame_age_ms`, `diagnostics.*` | Existing 2s polling |
| Header WebRTC status | Browser `RTCPeerConnection` callbacks | `pc.connectionState` | Event driven |
| Header WebSocket status | `/ws/results?camera_id=...` callbacks | `open`, `close`, `error` states | Event driven |
| Video card | `/status?camera_id=...`, `/runtime-control/status` | `cameras[].connected`, `cameras[].source_protocol`, `cameras[].capture_fps`, `stream_connected` | Existing 2s + 1s polling |
| Binary card | `/runtime-control/status`, `/ws/results` | `binary_enabled`, `runtime.binary_last_label`, `runtime.binary_last_probability`, `runtime.binary_provider`, `runtime.binary_sample_fps` | Existing 1s polling + realtime WS |
| Qwen card | `/runtime-control/status`, `/ws/results` | `qwen_enabled`, `runtime.vlm_active_count`, `runtime.vlm_provider`, `runtime.vlm_model`, `fall_decision.vlm_status` | Existing 1s polling + realtime WS |
| Current event card | `/ws/results`, `/events/latest` | `fall_decision.incident_id`, `fall_decision.event_created`, `fall_decision.fall_state`, normalized event `incident_id` | Realtime WS + existing latest event polling |
| Main-system card | `/status`, `/events/latest` | `fall_event_reporter.enabled`, `fall_event_reporter.main_system_reachable`, event `delivery.delivery_status`, `delivery.delivery_mode` | Existing polling |
| Central video | Existing WebRTC/fallback DOM | `video#video`, `img#frameFallback` | Existing video flow |
| Video overlay labels | Existing frontend state | Binary/Qwen/event fields listed above | Same as source |
| Device link panel | `/status`, `/runtime-control/status`, `/events/status` | masked source URL, reporter status, qwen runtime, event pipeline status | Existing polling |
| Model controls | `/runtime-control/binary`, `/runtime-control/qwen` | API response then refreshed `runtime-control/status` | User action + status refresh |
| Test controls | `/runtime-control/test/start`, `/runtime-control/test/stop`, `/runtime-control/status` | `test.running`, `test.state`, `test.remaining_seconds`, event counters, performance sample | User action + existing 1s polling |
| Performance panel | `/runtime-control/status`, browser video quality | `performance.capture_fps`, `binary_inference_ms_*`, `runtime.vlm_queue_depth`, `getVideoPlaybackQuality()` | Existing 1s sampling/polling |
| Event analysis | `/events/latest`, `/events/{incident_id}` | normalized incident, camera, track, event, fall state, risk, confidence, archive | Existing event polling |
| Qwen result | `/events/latest`, `/events/{incident_id}` | `qwen_advisory.analysis_status`, scene/posture/advice/uncertainty fields | Existing event polling |
| Structured JSON panel | Normalized event model from real event response | incident, event, fall state, risk, confidence, qwen status, delivery status | Existing event polling |
| Alarm delivery | `/events/latest`, `/events/delivery/status`, `/status` | `delivery_status`, `delivery_mode`, `dry_run`, `retry_count`, `delivered_at`, `last_error` | Existing event/status polling |

Fields that are not present in the backend payload are rendered as `--`.
