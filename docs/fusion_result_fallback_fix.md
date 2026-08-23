# Fusion Result Fallback Fix

On 2026-07-17, `ResultPublisherService` was changed so that a fresh fused result remains preferred when `FUSION_WORKER_ENABLED=true`, but an empty or stale fusion slot falls back to the ordinary snapshot builder. The published detector metadata now reports `result_source` as `fusion_slot`, `snapshot_fallback`, or `snapshot`.

This does not change `FallFusionService` decisions, REST schemas, WebSocket payload schemas, or the existing reporter path.

Validation command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fused_result_fallback.py tests\test_result_publisher_service.py tests\test_end_to_end_pipeline.py tests\test_fall_alert_polling_api.py -q
```
