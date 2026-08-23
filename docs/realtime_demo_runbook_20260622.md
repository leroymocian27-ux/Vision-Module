# Realtime Demo Runbook - 2026-06-22

目标：明天展示“实时摄像头视频检测最小演示”。不展示完整智慧养老系统，不真实 POST 主系统，不训练模型，不启用新多模态能力。

## 安全开场检查

```powershell
cd D:\Program\vision_service
Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=camera_01"
Invoke-RestMethod "http://127.0.0.1:8000/alerting/status"
```

必须看到：

```text
service_status=running
cameras[0].connected=true
cameras[0].stream_state=connected
endpoint.dry_run=true
fall_event_reporter.last_post_status 不应是 http_2xx
```

如果 `dry_run=false`，立即停止演示，不要继续。

## 打开实时页面

```text
http://127.0.0.1:8000/demo/
```

推荐展示顺序：

1. 先展示页面连接状态：WebRTC、WS、stream state、FPS。
2. 让单人全身入镜，确认人体框和 track。
3. 展示 `fallState`、`riskLevel`、`fallProbability` 这些字段会随结果更新。
4. 明确说明当前不会真实 POST，只会 dry-run 记录。

## 摄像头动作脚本

推荐动作：

```text
1. 正常站立 3 秒
2. 慢走 3 秒
3. 弯腰捡东西 2 秒
4. 蹲下或坐下 2 秒
5. 恢复站立
```

说明：

- 这段用于展示实时摄像头链路、人体框、track、风险面板。
- 不建议把这段作为“稳定确认跌倒”的唯一证明。
- 若要现场模拟跌倒，动作必须安全，最好只作为加分项。

## 本地 replay 主证明

稳定 replay 视频：

```text
D:\Program\vision_service\logs\acceptance\cropped_recording_2026-06-20T07-32-20-181Z\run2\cropped_recording_run2.mp4
```

用 `/stream/start` 切换到本地文件：

```powershell
$body = @{
  camera_id = "camera_01"
  rtsp_url = "D:\Program\vision_service\logs\acceptance\cropped_recording_2026-06-20T07-32-20-181Z\run2\cropped_recording_run2.mp4"
} | ConvertTo-Json

Invoke-RestMethod "http://127.0.0.1:8000/stream/start" `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

观察：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/integration/results/camera_01/latest"
Invoke-RestMethod "http://127.0.0.1:8000/integration/fall-alerts/camera_01/poll"
Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=camera_01"
```

理想结果：

```text
fall_state=fallen_confirmed
risk_level=critical
fall_score 非空
incident_id 非空
last_post_status=dry_run_skipped
```

如果 replay 只到 `fallen_candidate` 或 `high`，也可以作为“候选跌倒”演示，不要临时改阈值。

## 切回实时摄像头

优先使用现有 `.env` 默认 RTSP 或手动调用 `/stream/start`。不要在文档、截图或投屏里展示真实密码。

如果使用脚本，注意不要启用真实主系统告警：

```powershell
python scripts/start_current_camera.py --host 192.168.8.252 --api-port 8000 --no-wait
```

脚本默认会启动新服务进程，若已有 8000 服务在跑，先确认当前演示安排，避免重复开服务。

更稳妥方式是在已有服务上调用 `/stream/start`，使用已打码记录中的同一路摄像头配置。

## 推荐讲解词

```text
今天展示的是视觉服务的最小实时检测链路，不是完整智慧养老业务系统。链路包括 RTSP 摄像头接入、取帧、WebRTC 实时画面、YOLO 人体检测、目标跟踪、跌倒候选识别、风险状态输出、WebSocket/轮询结果，以及 dry-run 事件记录。当前不会向主系统真实发送告警。
```

```text
实时摄像头用于展示在线能力。本地 replay 用于稳定证明跌倒确认链路，因为现场动作、角度、遮挡和安全因素会影响实时触发稳定性。
```

```text
视觉风险分级和误报降级已经有离线审计和部分 runtime 字段，但完整 0-5 风险审核层还不是明天实时演示的主功能。
```

## 禁止操作

```text
1. 不修改 .env。
2. 不设置 MAIN_SYSTEM_REPORT_DRY_RUN=false。
3. 不调用真实 POST。
4. 不点击前端手动 alert simulation 按钮。
5. 不启用 pose_use_for_fall。
6. 不改 FallStateMachine。
7. 不改 ResultPublisherService。
8. 不改主系统 bridge。
9. 不训练模型。
10. 不接入新多模态模型。
11. 不 git add .
12. 不 git commit -am。
```

## 故障处理

### 页面打不开

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/healthz"
```

若失败，只重启当前 Vision Service：

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 摄像头卡顿

检查：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=camera_01"
```

重点看：

```text
stream_state
frame_age_ms
capture_fps
reconnect_count
read_timeout_count
```

如果 RTSP 不稳定，立即切本地 replay，不要现场调模型。

### 没有人体框

调整：

```text
1. 单人完整入镜。
2. 人离摄像头稍远一点，保证全身。
3. 避免背光。
4. 避免多人同时入镜。
```

不要临时降低大量阈值。

### 没有跌倒确认

处理：

```text
1. 先接受 fallen_candidate/high 作为候选结果。
2. 切换本地 replay 展示 fallen_confirmed。
3. 不临时改确认帧数、保持时长、模型阈值。
```

### 出现真实 POST 风险

立即停止，确认：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/alerting/status"
```

必须恢复：

```text
dry_run=true
```

