# Ollama Qwen Advisory Re-Evaluation Runbook

Use this runbook only after the C-line freeze. Default status remains
`KEEP_DISABLED`.

## When To Re-Evaluate

Re-evaluation is appropriate only when one or more of these conditions is true:

- A faster local model is available.
- Ollama runtime performance has been tuned outside this application.
- Local GPU/CPU resources are confirmed stable.
- There is enough time before a demo to run and inspect samples.
- The evaluation cannot affect realtime detection or event generation.

## Steps

1. Keep `EVENT_VLM_ENABLED=false`.
2. Run the evaluation script in dry-run mode.
3. Inspect JSON and JSONL output for schema, policy, and privacy fields.
4. Run local smoke only with `--allow-local-ollama`.
5. Use only `http://127.0.0.1:11434/api/chat` or localhost loopback.
6. Keep the payload text-only.
7. Run 5 cases first, then 10 cases if the first batch passes.
8. Record JSON and JSONL reports under a temporary evaluation directory.
9. Compare results against the enablement gate.

## Prohibited Actions

- Do not directly enable `EVENT_VLM_ENABLED=true` for a demo.
- Do not send images.
- Do not send local paths, keyframe paths, or timeline paths.
- Do not use an external endpoint.
- Do not treat timeout as success.
- Do not treat mock or dry-run output as real model acceptance.
- Do not present model output as medical diagnosis.

## Commands

Dry-run, no Ollama call:

```powershell
python scripts/evaluate_ollama_advisory_review.py `
  --cases fall_candidate_support,fallen_confirmed_high,adl_suppressed_review,missing_keyframes,vlm_timeout_fallback `
  --max-cases 5
```

Local smoke with `qwen-vision-cn:latest`:

```powershell
python scripts/evaluate_ollama_advisory_review.py `
  --allow-local-ollama `
  --endpoint http://127.0.0.1:11434/api/chat `
  --model qwen-vision-cn:latest `
  --timeout 15 `
  --max-cases 5
```

Local comparison with `qwen3.5:9b`:

```powershell
python scripts/evaluate_ollama_advisory_review.py `
  --allow-local-ollama `
  --endpoint http://127.0.0.1:11434/api/chat `
  --model qwen3.5:9b `
  --timeout 15 `
  --max-cases 5
```

Optional 10-case follow-up after a clean 5-case pass:

```powershell
python scripts/evaluate_ollama_advisory_review.py `
  --allow-local-ollama `
  --endpoint http://127.0.0.1:11434/api/chat `
  --model qwen-vision-cn:latest `
  --timeout 15 `
  --max-cases 10 `
  --output tmp_qwen_ollama_eval/ollama_advisory_eval_10.json `
  --jsonl tmp_qwen_ollama_eval/ollama_advisory_eval_10.jsonl
```

## Result Decision

- `KEEP_DISABLED`: choose this for timeout, insufficient samples, parse failures,
  policy violations, path leaks, or uncertain operator control.
- `ALLOW_DEMO_ONLY`: choose this only for a controlled demo after the text-only
  gate passes and rollback is immediate.
- `READY_FOR_STAGING`: do not assign lightly. It requires all gates to pass,
  enough real local samples, and a separate staging approval.

Timeline image evaluation is not allowed until text-only review is stable.
