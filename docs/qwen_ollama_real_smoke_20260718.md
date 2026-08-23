# Local Ollama Qwen Advisory-Only Real Smoke

Date: 2026-07-18

## Scope and Boundary

This was a controlled workstation smoke test, not production admission. The
new `scripts/smoke_qwen_ollama_advisory.py` script uses only the fixed local
endpoint `http://127.0.0.1:11434/api/chat`. It constructs synthetic redacted
semantics, uses `stream=false` and `format=json`, and asserts before sending
that the JSON has no incident ID, track ID, camera/person/device ID, image,
keyframe URL, local path, base64, or media reference.

No `.env` file was changed. No service, event worker, DeliveryOutbox, main
system alert, WebRTC, WebSocket, REST server, or VLM runtime feature flag was
enabled. No image input was sent.

## Model Results

| Model | Command | Result | Latency | Advisory JSON | Fallback | Invalid JSON |
| --- | --- | --- | --- | --- | --- | --- |
| `qwen-vision-cn:latest` | `python scripts/smoke_qwen_ollama_advisory.py --model qwen-vision-cn:latest --timeout-seconds 120` | `REVISE` | 120,000 ms timeout deadline | None | No | No |
| `qwen3.5:9b` | `python scripts/smoke_qwen_ollama_advisory.py --model qwen3.5:9b --timeout-seconds 120` | `REVISE` | 111,700 ms observed end-to-end | None | No | Yes |

### `qwen-vision-cn:latest`

The local endpoint did not return before the 120 second request deadline:

```text
error_type: timeout
HTTPConnectionPool(host='127.0.0.1', port=11434): Read timed out.
```

No advisory JSON was received. No fallback model was selected automatically.

### `qwen3.5:9b`

The local endpoint returned after approximately 111.7 seconds, but the
`message.content` value was not valid JSON for the advisory contract:

```text
error_type: invalid_json
Ollama message content is invalid JSON
```

No advisory JSON was accepted. No fallback model was selected automatically.

## Required Conclusion Fields

```yaml
qwen_vision_cn_smoke: REVISE
qwen35_9b_smoke: REVISE
image_input: DISABLED
external_endpoint: NOT_USED
production_activation: NOT_APPROVED
```

The adapter correctly kept these failures advisory-only. It did not modify a
fall decision, send delivery, or affect the realtime chain. Before another
smoke attempt, investigate local Ollama model loading/inference capacity and
enforce the advisory JSON contract at the selected model layer. Do not treat
this result as a real VLM production-readiness approval.
