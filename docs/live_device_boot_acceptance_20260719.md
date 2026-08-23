# Live Device Boot Acceptance

Date: 2026-07-19  
Result: `LIVE_BOOT_BLOCKED`  
Scope: real-device discovery and safe RTSP preflight only

## Objective

Discover the current LAN camera, verify the `.251` main system, validate an
RTSP source, then start the real `8000` realtime chain only if the source can
be opened safely. Event pipeline, DeliveryOutbox, VLM/Ollama and real POST
remain disabled throughout this run.

## Network Discovery

The active WLAN adapter was on a `/24` private subnet. The scan was restricted
to host suffixes `.248` through `.255`; no wider network discovery occurred.

| Target | Safe result |
| --- | --- |
| Main system `xxx.xxx.xxx.251` | ICMP did not respond, but TCP `8000` was open and `GET /healthz` returned HTTP 200. |
| Candidate `xxx.xxx.xxx.253` | ICMP responded; project RTSP port `10554` was open. |
| Other candidates `.248`, `.249`, `.250`, `.254`, `.255` | No tested camera/service port was open. |

The port set was limited to `80`, `554`, `8000`, `8080`, `8554`, `8899` and the
project's configured camera port `10554`. Existing device cache and ARP data
were read only; they were used as hints, not as proof of a valid camera stream.

## RTSP Validation

The project template identified `10554` as the camera RTSP port and supplied a
username setting, but no configured password was present. `ffprobe` was
available and attempted the approved substream path first, then the main path.
Both probes failed to open. No full RTSP URL, username, password, token or
ffprobe error text is recorded in this document.

| Stream | Opened | Result |
| --- | --- | --- |
| Substream | no | `ffprobe_open_failed` |
| Main stream | no | `ffprobe_open_failed` |

This is an authentication/access prerequisite failure, not a fall-detection
result. The system did not guess credentials or retry alternative passwords.

## 8000 Boundary

`8000` was already healthy. It was not stopped, restarted or reconfigured
because no authorized real RTSP source passed validation. The existing process
therefore remains outside this real-device acceptance result.

```yaml
event_pipeline_enabled: false
event_delivery_enabled: false
event_vlm_enabled: false
main_system_alert_enabled: false
real_post_sent: false
ollama_called: false
actual_env_modified: false
```

The requested 10-15 minute real-device observation, `/demo/` real video,
WebRTC/WS real-source verification, FPS/latency/resource capture and error
statistics are `NOT_RUN`; running them against mock video would not satisfy
this acceptance.

## Blocker And Required Input

Provide one of the following through an approved operational channel:

1. Authorized RTSP credential/access configuration for camera suffix `.253`,
   including the approved stream path; or
2. An authorized real replay source with equivalent access information.

Do not place the secret in `.env`, source code, screenshots, terminal history
or this report. Once access is available, repeat only the RTSP probe, then
obtain/confirm approval before switching `8000` from its current approved
source to the real-device launch profile.

## Next State

```yaml
LIVE_BOOT: BLOCKED_BY_RTSP_CREDENTIAL_OR_AUTHORIZED_REPLAY
P2: WAITING_FOR_APPROVAL_RESTART_8000
P3_P5: WAITING_FOR_AUTHORIZED_REAL_RTSP_OR_REPLAY
P6: WAITING_FOR_STAGING_CONTRACT_AND_APPROVAL
```

No event sidecar, real POST, VLM/Ollama, Kafka, Redis or Celery was enabled or
tested during this run.
