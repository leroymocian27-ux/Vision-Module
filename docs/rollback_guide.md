# Rollback Guide

Version: `fall-monitor-stable-v1.0-rc`

## Runtime Rollback

1. Stop the service:

```powershell
.\scripts\stop_service.ps1
```

2. Restore the previous release directory or working tree.
3. Re-run config validation.
4. Start with `safe_demo` before using real RTSP.

## Configuration Rollback

Use profile files under `configs/` instead of editing the real `.env` during stabilization. If a production candidate profile fails, revert to `configs/safe_demo.env` and preserve the failing validation report.

## Safety Rollback

If any external delivery, Qwen/VLM, Robot Assist, or Go2 setting is unexpectedly enabled, stop the service and return to `safe_demo` before further testing.
