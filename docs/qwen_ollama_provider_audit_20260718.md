# Qwen Ollama Provider Audit

Date: 2026-07-18

The prior `qwen_http` trace was a thin generic HTTP adapter. It reused the
image-oriented generic review path, could point to an arbitrary endpoint, and
was not suitable for the required local structured-semantics experiment.

Decision: retain `QwenHttpVLMReviewAdapter` only as a direct legacy test shell;
it is no longer accepted by `Settings` and cannot be selected through
`EVENT_VLM_PROVIDER`. This prevents normal configuration from accidentally
using an external Qwen endpoint.

The supported controlled provider is now `qwen_ollama` (`ollama_qwen` is kept as
a compatibility alias for the first audit tests). It uses Ollama's local
`/api/chat` endpoint, rejects non-localhost base URLs by default, requires
`stream=false`, and sends a structured EventSemantics summary only. It does not
send images, image bytes, base64, keyframe URLs, archive paths, snapshot URLs,
or local paths.

Local model inventory confirmed by `ollama list`:

- Preferred: `qwen-vision-cn:latest`
- Comparison only: `qwen3.5:9b`

No real Ollama inference was run during this audit.
