# Post-RTSP Dry-Run And A/B Report 2026-07-08

## Current Runtime State

- Vision Service is running on `http://127.0.0.1:8000`.
- Current service process PID: `30688`.
- Current runtime stream was restored to `av0_0` after A/B testing.
- Current source: `rtsp://admin:***@192.168.8.252:10554/tcp/av0_0`.
- Current frame size: `2304x1296`.
- Current capture state: connected.
- Current capture FPS after restore: about `14.99`.
- Current detection FPS after restore: about `4.19`.

## P1 Main System / Dry-Run

Main system target remains unavailable from this host:

- `MAIN_SYSTEM_BASE_URL=http://192.168.8.248:8000/api/v1`
- HTTP health probe timed out.
- TCP probe to `192.168.8.248:8000` also did not complete in the current check window.

Local runtime has been switched to dry-run:

```env
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

Runtime confirmation:

- `/alerting/status` returns `endpoint.dry_run=true`.
- Fall event reporter remains enabled, but it will not perform real POST delivery while dry-run is active.

Conclusion: P1 is isolated as a main-system/network availability issue. The AI/Vision local chain can continue validating in dry-run mode.

## P2 Person-Visible Baseline

A 15-second precheck was run before the 60-second baseline.

Artifacts:

- `artifacts/person_visible_baseline_20260708/precheck_samples.json`
- `artifacts/person_visible_baseline_20260708/precheck_status_*.json`

Result:

- Current frame had no continuously visible person.
- `latest_raw_person_count` stayed at `0` during the precheck window.
- Therefore the requested 60-second person-visible stability baseline was not executed, because the acceptance condition was not present.

Previous smoke result is still valid as a single-frame chain proof:

- person detection worked once.
- tracking object existed once.
- pose attached once.
- temporal/fusion fields appeared.

Remaining gap: continuous 60-second person-visible stability data still needs a person kept in frame.

## P3 av0_1 A/B Baseline

Runtime stream was temporarily switched through `/stream/start` to:

```text
rtsp://admin:***@192.168.8.252:10554/tcp/av0_1
```

Artifacts:

- `artifacts/perf_av0_1_20260708/perf_av0_1_3min_samples.json`
- `artifacts/perf_av0_1_20260708/perf_av0_1_3min_samples.csv`
- `artifacts/perf_av0_1_20260708/gpu_av0_1_3min_samples.json`
- `artifacts/perf_av0_1_20260708/latest_av0_1_final.jpg`
- `artifacts/perf_av0_1_20260708/summary.json`

3-minute av0_1 summary:

| Metric | av0_1 |
|---|---:|
| Samples | 180 |
| Valid samples | 180 |
| Errors | 0 |
| Resolution | 640x360 |
| Capture FPS avg | 14.933 |
| Detection FPS avg | 4.077 |
| Fall hint FPS avg | 4.077 |
| Result publish FPS avg | 9.213 |
| Tracking FPS avg | 4.078 |
| Pose FPS avg | 0.325 |
| Person inference latency avg | 17.978 ms |
| Fall hint latency avg | 16.741 ms |
| Frame age avg | 49.174 ms |
| Reconnect count last | 0 |
| Read timeout count last | 0 |
| GPU util avg | 21% |
| GPU memory avg | 2455 MiB |

Comparison with prior av0_0 sample:

| Metric | av0_0 prior | av0_1 current |
|---|---:|---:|
| Resolution | 2304x1296 | 640x360 |
| Capture FPS avg | 14.946 | 14.933 |
| Detection FPS avg | 4.058 | 4.077 |
| Fall hint FPS avg | 4.058 | 4.077 |
| Result publish FPS avg | 9.203 | 9.213 |
| Person inference latency avg | 19.099 ms | 17.978 ms |
| Fall hint latency avg | 28.682 ms | 16.741 ms |
| Frame age avg | 35.556 ms | 49.174 ms |

Conclusion:

- av0_1 is stable for 3 minutes with no read timeout and no reconnect.
- av0_1 reduces fall-hint inference latency substantially in this run.
- Overall pipeline FPS is still capped around `4.0` for detection/fall-hint and around `9.2` for result publishing.
- This supports using av0_1 as a candidate analysis stream, but final choice should wait for the 60-second person-visible baseline because low-resolution pose/tracking quality must be validated with a person present.

## Current Operator Commands

Start Vision Service:

```powershell
cd D:\camera
C:\Users\Test1\.conda\envs\health\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check runtime:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=camera_01" |
  ConvertTo-Json -Depth 80
```

Check alerting dry-run:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/alerting/status" |
  ConvertTo-Json -Depth 80
```

Capture 60-second person-visible baseline when a person is kept in frame:

```powershell
New-Item -ItemType Directory -Force artifacts\person_visible_baseline_20260708 | Out-Null
for ($i = 0; $i -lt 60; $i++) {
  $ts = Get-Date -Format "yyyyMMdd_HHmmss_fff"
  Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=camera_01" |
    ConvertTo-Json -Depth 80 > "artifacts\person_visible_baseline_20260708\status_$ts.json"
  Invoke-RestMethod "http://127.0.0.1:8000/integration/results/camera_01/latest" |
    ConvertTo-Json -Depth 80 > "artifacts\person_visible_baseline_20260708\latest_$ts.json"
  Start-Sleep -Seconds 1
}
Invoke-WebRequest "http://127.0.0.1:8000/stream/latest-frame.jpg?camera_id=camera_01" `
  -OutFile "artifacts\person_visible_baseline_20260708\latest_person_visible_final.jpg"
```

## Next Recommendation

1. Keep `MAIN_SYSTEM_REPORT_DRY_RUN=true` until `192.168.8.248:8000` is reachable again.
2. Put one person in frame for at least 60 seconds and rerun the person-visible baseline command above.
3. After P2 is complete, decide whether analysis should use `av0_0` or `av0_1`.
4. Only after P2/P3 are both stable should FallHintWorker split or deeper model-threshold tuning be implemented.
