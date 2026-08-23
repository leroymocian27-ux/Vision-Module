# Phase 4.2 Realtime Tracking Pipeline Stabilization 验收记录

## 1. 阶段目标

Phase 4.2 的目标不是新增算法能力，而是优化实时感知链路�?
- �?tracking / pose / behavior / result publish �?detection loop 中拆开
- �?tracking/result publish 不再完全�?detection_fps 限制
- �?overlay 输出频率明显高于 YOLO detect 频率
- 保护 RTSP / FrameBuffer / WebRTC 主视频链�?
本阶段未进入�?
- GRU / LSTM
- 跌倒判�?- 告警
- 主后�?POST

## 2. 当前架构变化

改造前�?
```text
DetectionWorker
-> YOLO detect
-> TrackingService
-> IdentityBindingService
-> PoseService
-> BehaviorService
-> WebSocket publish
```

改造后�?
```text
CaptureWorker
-> FrameBuffer

DetectionWorker
-> YOLO detect
-> latest_detection

TrackingWorker
-> latest_detection
-> latest_tracking

PoseWorker
-> latest_tracking + latest frame
-> latest_pose
-> latest_behavior

ResultPublisher
-> merge latest_tracking + latest_pose + latest_behavior
-> WebSocket publish
```

## 3. 新增/扩展模块

- `app/detection/realtime_result_store.py`
- `app/services/tracking_worker_service.py`
- `app/services/pose_worker_service.py`
- `app/services/result_publisher_service.py`
- `/status.pipeline`

## 4. 新增配置�?
```text
TRACKING_WORKER_FPS=12
POSE_WORKER_FPS=2
RESULT_PUBLISH_FPS=10
```

## 5. 代码级自测结�?
已执行：

```powershell
conda run -n torchgpu python -m compileall app
conda run -n torchgpu python -c "from app.main import app; print('app import ok')"
```

结果：通过�?
本地 smoke test 指标�?
```text
detection_worker_fps: 4.6
tracking_worker_fps: 10.23
result_publish_fps: 9.17
latest_detection_age_ms: 203ms
latest_tracking_age_ms: 78ms
detection_to_publish_lag_ms: 156ms
last_error: null
```

代码级结论：

```text
tracking_worker_fps > detection_worker_fps
result_publish_fps >= 8
```

## 6. 真实 RTSP 验收计划

### 6.1 启动配置

Identity Service�?
```powershell
cd D:\vision_service\identity_service
conda activate identity310
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Vision Service�?
```powershell
cd D:\vision_service
conda activate torchgpu

$env:ENABLE_TRACKING="true"
$env:ENABLE_IDENTITY_BINDING="true"
$env:IDENTITY_SERVICE_URL="http://127.0.0.1:8100"
$env:IDENTITY_REQUEST_TIMEOUT_MS="1000"
$env:ENABLE_POSE="true"
$env:POSE_PROVIDER="yolo"
$env:ENABLE_BEHAVIOR="true"
$env:TRACKING_WORKER_FPS="12"
$env:POSE_WORKER_FPS="2"
$env:RESULT_PUBLISH_FPS="10"

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

真实 RTSP�?
```powershell
$CAMERA_IP = "192.168.8.254"
$RTSP_USER = "admin"
$RTSP_PASS = "你的密码"
$RTSP_URL = "rtsp://$RTSP_USER`:***@$CAMERA_IP`:554/tcp/av0_1"

$body = @{
  camera_id = "camera_01"
  rtsp_url = $RTSP_URL
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8000/stream/start `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

前端�?
```text
http://127.0.0.1:8000/demo/?v=phase42
```

### 6.2 状态采样命�?
```powershell
$rows = @()
for ($i = 1; $i -le 20; $i++) {
  $s = Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=camera_01"
  $rows += [pscustomobject]@{
    sample = $i
    stream = $s.cameras[0].stream_state
    frame_age_ms = $s.cameras[0].frame_age_ms
    capture_fps = $s.cameras[0].capture_fps
    detection_worker_fps = $s.pipeline.detection_worker_fps
    tracking_worker_fps = $s.pipeline.tracking_worker_fps
    result_publish_fps = $s.pipeline.result_publish_fps
    pose_fps = $s.pose.pose_fps
    latest_detection_age_ms = $s.pipeline.latest_detection_age_ms
    latest_tracking_age_ms = $s.pipeline.latest_tracking_age_ms
    latest_pose_age_ms = $s.pipeline.latest_pose_age_ms
    detection_to_publish_lag_ms = $s.pipeline.detection_to_publish_lag_ms
    pipeline_error = $s.pipeline.last_error
  }
  Start-Sleep -Seconds 2
}
$rows | Format-Table -AutoSize
```

### 6.3 重点观察指标

| 指标 | 目标 |
| --- | --- |
| `capture_fps` | �?25-30 FPS |
| `frame_age_ms` | 大部�?< 100ms，不持续超过 3000ms |
| `detection_worker_fps` | �?3-5 FPS，允许受 YOLO 负载波动 |
| `tracking_worker_fps` | > `detection_worker_fps`，目�?10-15 FPS |
| `result_publish_fps` | >= 8 FPS |
| `pose_fps` | 1-3 FPS |
| `detection_to_publish_lag_ms` | 越低越好，建议先观察是否稳定低于 300ms |
| `pipeline.last_error` | null |

## 7. 主观前端验收

前端重点观察�?
- 视频是否仍然流畅
- 目标框是否比 Phase 4.1 更顺�?- `Target #id` 是否仍能稳定显示
- skeleton 可低频更新，但不应拖�?bbox
- 右侧 `Detect FPS / Track FPS / Pose FPS` 是否符合预期
- 关闭/超时 identity_service 时，WebRTC �?result publish 不应卡死

通过标准�?
```text
WebRTC 视频稳定
result_publish_fps >= 8
tracking_worker_fps > detection_worker_fps
overlay 主观明显比改造前顺滑
Pose 低频运行但不拖慢 detection
identity timeout 不拖�?result publish
```

## 8. Identity Timeout 验收

建议分两组测试：

```powershell
$env:IDENTITY_REQUEST_TIMEOUT_MS="500"
```

和：

```powershell
$env:IDENTITY_REQUEST_TIMEOUT_MS="3000"
```

观察�?
- `result_publish_fps` 是否仍能保持 >= 8
- `tracking_worker_fps` 是否明显下降
- WebRTC 是否继续流畅
- `/status.identity.last_error` 是否只影�?identity，不影响 pipeline

## 9. 当前边界与风�?
当前 tracking worker 的无�?detection 策略是：

```text
保持上一 bbox
```

这只�?Phase 4.2 的最小预测方案，不是真正的光流、CSRT、KCF �?ReID 视觉跟踪�?
已知风险�?
- 真实 RTSP 长稳待补�?- 快速移动或遮挡时，仅保持上一 bbox 可能仍有目标滞后�?- 真实 YOLO-Pose �?RTSP 下的长时间性能仍需观察�?- `ResultStore` 旧对象仍保留�?Runtime 中，后续可清理�?- 当前阶段没有进入 GRU / 跌�?/ 告警�?
## 10. 阶段结论

Phase 4.2 代码级目标已完成�?
```text
DetectionWorker 不再作为唯一 WebSocket publish 来源�?TrackingWorker 可以高于 detection_fps 运行�?ResultPublisher 可以达到 8-10 FPS�?PoseWorker 已从 detection loop 中拆出�?```

真实 RTSP 真人长稳验收待补�?