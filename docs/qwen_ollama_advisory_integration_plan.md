# Local Ollama Qwen Advisory Integration Plan

`qwen_ollama` is advisory-only and default-disabled. It runs after the rule
result exists and cannot modify `fall_state`, `final_event_type`,
`final_risk_level`, `support_fall_alarm`, delivery state, incident identity, or
the realtime result.

```dotenv
EVENT_VLM_ENABLED=false
EVENT_VLM_PROVIDER=dummy
EVENT_VLM_OLLAMA_ENDPOINT=http://127.0.0.1:11434/api/chat
EVENT_VLM_OLLAMA_MODEL=qwen-vision-cn:latest
EVENT_VLM_OLLAMA_FALLBACK_MODEL=qwen3.5:9b
EVENT_VLM_OLLAMA_TIMEOUT_SECONDS=15
EVENT_VLM_OLLAMA_TEXT_ONLY=true
EVENT_VLM_OLLAMA_INCLUDE_IMAGES=false
```

When explicitly enabled with `EVENT_VLM_PROVIDER=qwen_ollama`, the request is
restricted to loopback by default and contains only motion, posture, evidence,
risk, uncertainty, and degradation summaries. The adapter sends `stream=false`
and asks Ollama for JSON output. `ollama_qwen` remains a compatibility alias for
earlier tests. The accepted output is the standard `vlm_review_result_v1`
advisory schema, including:

- `observed_process`
- `risk_interpretation`
- `adl_likelihood`
- `uncertainty`
- `alarm_title`
- `alarm_body`
- `recommended_action`

Malformed JSON, HTTP errors, timeouts, non-localhost endpoints, and schema
violations degrade back to the rule result. Confirmed falls remain confirmed.
Image/multimodal input remains unadmitted even though the selected local model
has vision capability.
