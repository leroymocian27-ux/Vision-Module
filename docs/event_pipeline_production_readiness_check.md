# Event Pipeline Production Readiness Check

`scripts/check_event_pipeline_production_readiness.py` is a read-only local
configuration checker. It parses an env file and source mount declaration only;
it does not modify files, send network traffic, start workers, call Ollama, or
load the service runtime.

Run:

```powershell
.\.venv\Scripts\python.exe scripts\check_event_pipeline_production_readiness.py --env .env.example --json
```

It checks default-disable posture, post delivery prerequisites, archive/keyframe
containment, archive-path redaction markers in the event API, static archive
exposure, allowed VLM providers, local Ollama loopback restriction, text-only
image-input prohibition, and archive capacity settings. It accepts both the
current `EVENT_VLM_OLLAMA_*` keys and the documented compatibility aliases.

`--json` returns a stable `ok`, `findings`, and `checked_keys` object.
`checked_keys` is limited to the readiness gate's relevant setting names; no
configuration values or secrets are printed. A nonzero exit status means at least one `fail` finding;
`warn` findings require operator review but do not claim approval. Passing this
checker is a configuration gate only, not authorization to enable production
POST, VLM, or archive image access.
