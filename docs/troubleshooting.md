# Troubleshooting

Version: `fall-monitor-stable-v1.0-rc`

## First Checks

1. Check process and port with `scripts/status.ps1`.
2. Check `GET /healthz` for HTTP process liveness.
3. Check `GET /status` for camera, model, worker, and result state.
4. Run `python scripts/validate_config.py --profile safe_demo`.
5. Run `python scripts/run_stable_smoke.py --profile safe_demo`.

## Common Causes

| Symptom | Likely area | Action |
| --- | --- | --- |
| Service does not start | Python import, dependency, or config | Check uvicorn log and run `py_compile` on recently changed files. |
| `/healthz` is alive but no frame | Camera or capture worker | Inspect `/status` camera state and latest frame age. |
| Detection is not running | Model path or worker startup | Run config validation and check detection section in `/status`. |
| Real RTSP fails | Credentials, port, network, or path | Use `production_candidate` only with approved RTSP env values. |
| Unexpected external calls | Unsafe flags enabled | Confirm delivery, Qwen/VLM, Robot, and Go2 flags are disabled. |

## Evidence Rule

Do not mark a scenario as `PASS` unless there is a report, log, screenshot, or machine-readable artifact.
