# Camera State Contract

Date: 2026-07-20

Public camera states:

| State | Definition | Entry condition | Exit condition | Auto reconnect | Health impact | Fall result trust |
| --- | --- | --- | --- | --- | --- | --- |
| `disabled` | No runtime source is active or camera is not enabled. | No `CameraRuntime` exists. | Source starts. | No | Not healthy for video chain | Results unavailable |
| `initializing` | Runtime object exists but worker has not reached connect loop. | Source accepted before first worker status. | Worker enters connecting or stopped. | No | Warming up | Results unavailable |
| `connecting` | Capture is trying to open or produce first frame. | Worker stream state is connecting. | First valid frame, reconnect, or failure. | Depends on source | Degraded | Results unavailable |
| `connected` | Capture opened but no valid frame has arrived yet. | Connected flag true and no frame. | Fresh frame or error. | Depends on source | Degraded | Results unavailable |
| `streaming` | Fresh frames are being produced. | Frame age <= delayed threshold. | Delayed/stale/stop/reconnect. | Not needed | Healthy | Results may be interpreted |
| `delayed` | Frames exist but are older than delayed threshold. | delayed threshold < frame age <= stale threshold. | Fresh frame or stale. | No | Degraded | Results should be treated cautiously |
| `stale` | Last frame is too old. | frame age > stale threshold. | Fresh frame or reconnect/stop. | Yes for capture watchdog when configured | Degraded | Not safe as no-fall evidence |
| `reconnecting` | Capture is waiting before reopening. | Worker stream state is reconnecting. | Connecting or stopped. | Yes | Degraded | Results unavailable |
| `authentication_failed` | Source rejected credentials. | Error text indicates auth failure. | User provides valid source. | No high-speed retry | Blocked for source | Results unavailable |
| `unreachable` | Source cannot be opened or network is unreachable. | Open/connect failure without auth/decode signal. | Reconnect succeeds or user stops. | Bounded retry | Degraded | Results unavailable |
| `decode_error` | Capture opened but frame decode failed. | Decode/protocol error. | Reconnect succeeds or user stops. | Bounded retry | Degraded | Results unavailable |
| `stopped` | User or service stopped capture. | Worker stopped or source removed. | Source starts. | No | Not healthy for video chain | Results unavailable |

Compatibility rule: existing internal states may remain, but `/status` and related APIs must expose a compatible public state through `stream_state`.
