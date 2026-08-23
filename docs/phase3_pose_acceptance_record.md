# Phase 3 Pose Acceptance Record

## 1. 阶段结论

Phase 3 Pose 接入开发完成。

本阶段只做姿态估计接入与 skeleton overlay，不进入：

- GRU
- LSTM
- 跌倒判断
- 跌倒状态机
- 分级告警
- 主后端 POST

当前 Pose 能力作为实时视觉链路的增强层存在：

```text
RTSP
-> CaptureWorker
-> FrameBuffer
-> YOLO person detect
-> ByteTrack tracking
-> Identity binding
-> YOLO-Pose / Mock Pose
-> WebSocket result
-> frontend overlay
```

Pose 不重新拉 RTSP，不使用 `model.track(rtsp_url)`。

## 2. 已完成能力

- 新增 `app/pose/` 模块。
- 新增 `PoseService`。
- 支持 `POSE_PROVIDER=mock`。
- 支持 `POSE_PROVIDER=yolo`。
- 支持 YOLO-Pose 模型：`yolov8n-pose.pt`。
- Pose 只消费 tracking 后的 `objects`。
- 如果存在 `is_target=true`，只对 target 跑 pose。
- 如果不存在 target，则对最大 bbox person 跑 pose。
- WebSocket object 已扩展 `pose` 字段。
- 前端 overlay 已支持 skeleton 绘制。
- `/status.pose` 已暴露：
  - `pose_enabled`
  - `pose_provider`
  - `pose_fps`
  - `last_error`
- Pose 出错会 graceful fallback，不影响 RTSP / WebRTC / YOLO / Tracking。

## 3. 配置

默认稳态配置：

```text
ENABLE_POSE=false
POSE_PROVIDER=mock
POSE_FPS=3
```

YOLO-Pose 测试配置：

```text
ENABLE_POSE=true
POSE_PROVIDER=yolo
POSE_FPS=2
YOLO_POSE_MODEL_PATH=yolov8n-pose.pt
YOLO_POSE_CONFIDENCE=0.25
YOLO_POSE_IMGSZ=640
YOLO_POSE_DEVICE=
POSE_CROP_PADDING_RATIO=0.08
```

说明：`ENABLE_POSE=true` 当前属于测试态。默认稳定运行时应保持关闭，待真实 RTSP 验收通过后再决定是否常开。

## 4. Mock Pose 验收

Mock Pose 已通过。

测试方式：

- 启动主服务。
- 设置 `ENABLE_POSE=true`。
- 设置 `POSE_PROVIDER=mock`。
- 切换本地 person 视频源。
- 通过 WebSocket 抓取 pose payload。

实际结果：

```text
keypoint_count=17
skeleton_confidence=0.75
pose_fps 可观测
last_error=null
```

结论：Mock Pose 数据链路通过。

## 5. YOLO-Pose 本地视频验收

YOLO-Pose 本地视频验收通过。

测试视频：

```text
D:\vision_service\tests\fixtures\person_bus_loop.mp4
```

模型：

```text
D:\vision_service\yolov8n-pose.pt
```

WebSocket 抓取结果：

```json
{
  "track_id": 1,
  "is_target": true,
  "keypoint_count": 17,
  "skeleton_confidence": 0.9139,
  "first_keypoint": {
    "name": "nose",
    "x": 143.4,
    "y": 442.04,
    "confidence": 0.9871
  }
}
```

`/status.pose` 结果：

```json
{
  "pose_enabled": true,
  "pose_provider": "yolo",
  "pose_fps": 0.84,
  "last_error": null
}
```

关键指标：

```text
pose_fps=0.84
skeleton_confidence=0.9139
keypoint_count=17
```

结论：YOLO-Pose 本地视频链路通过。

## 6. 真实 RTSP 验收状态

真实 RTSP + 真人目标 Pose 验收待补。

待验证内容：

- 真实摄像头下 skeleton overlay 是否能稳定显示。
- Pose 是否只对 `is_target=true` 的目标运行。
- 多人场景下是否避免对所有人跑 pose。
- 骨架是否跟随目标移动。
- `pose_fps` 是否稳定。
- `frame_age_ms` 是否保持健康。
- `detection_fps` 是否明显下降。
- WebRTC 播放是否受 Pose 推理影响。

## 7. 当前风险

| 风险 | 当前表现 | 处理建议 |
| --- | --- | --- |
| `pose_fps` 偏低 | 本地视频 YOLO-Pose 实测 `pose_fps=0.84` | 真实 RTSP 下继续观察，必要时降低 `YOLO_POSE_IMGSZ` 或降低 `POSE_FPS` 目标 |
| 本地 mp4 到结尾会 reconnect | `reconnect_count` 增长，`stream_state` 可能出现 `reconnecting` | 已知 mock 源风险，不代表真实 RTSP 表现 |
| `ENABLE_POSE=true` 是测试态 | 当前测试期间启用了 Pose | 默认稳态应保持 `ENABLE_POSE=false` |
| 真实 RTSP 性能影响未验证 | 本地视频不能代表真实摄像头长期表现 | 需要补真实 RTSP 长稳验收 |
| Pose 可能拖慢 detection loop | 当前 Pose 在 detection 后处理链路中执行 | 后续如影响明显，可拆为独立 Pose worker |

## 8. 真实 RTSP 验收计划

建议使用真实摄像头子码流：

```text
rtsp://admin:***@192.168.8.254:554/tcp/av0_1
```

建议启动配置：

```powershell
$env:ENABLE_TRACKING="true"
$env:ENABLE_IDENTITY_BINDING="true"
$env:ENABLE_POSE="true"
$env:POSE_PROVIDER="yolo"
$env:POSE_FPS="2"
$env:YOLO_POSE_MODEL_PATH="yolov8n-pose.pt"
```

验收项：

| 验收项 | 观察指标 | 通过标准 |
| --- | --- | --- |
| target pose 是否只对目标运行 | WebSocket `objects[].pose` | 只有 `is_target=true` 的对象有 pose，或无 target 时只有最大 bbox 有 pose |
| skeleton overlay 是否跟随目标 | `/demo` 画面 | 骨架贴合并跟随人体移动 |
| `pose_fps` 是否稳定 | `/status.pose.pose_fps` | 稳定非 0，且不持续下降 |
| `frame_age_ms` 是否健康 | `/status.cameras[0].frame_age_ms` | 大部分时间低于 3000ms |
| `detection_fps` 是否明显下降 | `/status.detection[0].detection_fps` | 不出现不可接受的长期下降 |
| WebRTC 是否受影响 | `/demo` WebRTC 状态 | 视频持续播放，不因 Pose 断流 |
| Pose 错误是否隔离 | `/status.pose.last_error` | 即使出错，RTSP/WebRTC/YOLO/Tracking 仍正常 |

建议采样命令：

```powershell
$rows = @()
for ($i = 1; $i -le 20; $i++) {
  $s = Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=camera_01"
  $rows += [pscustomobject]@{
    sample = $i
    stream = $s.cameras[0].stream_state
    frame_age_ms = $s.cameras[0].frame_age_ms
    capture_fps = $s.cameras[0].capture_fps
    detection_fps = $s.detection[0].detection_fps
    tracking_fps = $s.tracking.tracking_fps
    pose_fps = $s.pose.pose_fps
    pose_error = $s.pose.last_error
  }
  Start-Sleep -Seconds 2
}
$rows | Format-Table -AutoSize
```

## 9. 当前阶段判定

Phase 3 当前状态：

```text
开发完成
Mock Pose 通过
YOLO-Pose 本地视频通过
真实 RTSP + 真人目标 Pose 验收待补
```

下一步建议先补真实 RTSP Pose 验收，不要直接进入 GRU 或跌倒状态机。
