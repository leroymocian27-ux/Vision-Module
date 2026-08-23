# Local Ollama Qwen Advisory Acceptance

Date: 2026-07-18

Status: PASS for mock-backed local adapter contract; real Ollama smoke: REVISE.

The implementation adds `ollama_qwen`, default-disabled local configuration,
loopback validation, a structured-only `/api/chat` request, `stream=false`,
JSON schema validation, and advisory-only trusted-result fields. Tests verify:

- default configuration creates no VLM adapter;
- `ollama_qwen` uses the local default base URL and preferred model;
- non-localhost URLs are rejected before HTTP;
- request bodies omit keyframes, paths, URLs, image bytes, and base64;
- a valid mock response populates advisory fields only;
- a VLM disagreement cannot downgrade `fallen_confirmed`;
- existing timeout, invalid JSON, and rule fallback tests remain green.

Initial mock-backed test result: `57 passed` across VLM, Qwen compatibility,
merge-policy, prompt-guard, and local privacy-contract tests. During that mock
acceptance, no real Ollama request, external URL, image, keyframe, local path,
or image bytes were sent.

The controlled local smoke was subsequently run against both installed models.
`qwen-vision-cn:latest` timed out at 120 seconds and `qwen3.5:9b` returned
invalid advisory JSON. See `qwen_ollama_real_smoke_20260718.md`. Those results
do not change the mock-contract PASS and do not approve production activation.
