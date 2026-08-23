# Vision Service 当前系统与功能介绍文档

更新日期：2026-07-08  
适用目录：`D:\camera`

## 1. 文档目标

本文面向项目负责人、主系统联调工程师、前端工程师、测试人员和后续维护人员，系统性介绍当前 `Vision Service` 的系统定位、运行链路、核心模块、对外接口、配置项、数据产物和典型排障方式。

当前系统的核心目标是：从摄像头实时视频中识别人、跟踪目标、分析姿态和时序动作，融合多种证据判断跌倒事件，并把确认后的跌倒告警推送给主系统，同时为浏览器 Demo、联调接口和排障工具提供可观测结果。

## 2. 系统定位

`Vision Service` 是一个独立运行的实时视觉分析服务，基于 FastAPI 提供 HTTP、WebSocket 和 WebRTC 能力。它在整个养老看护系统中的角色是“视频智能分析侧车”：

- 接入 RTSP 摄像头或本地 mock 摄像头。
- 持续维护最新视频帧。
- 执行人体检测、跌倒提示检测、目标跟踪、姿态估计、行为/时序分析。
- 融合多路证据输出统一的 `VisionResult`。
- 生成跌倒事件快照和 `incident_id`。
- 将确认跌倒事件推送到主系统。
- 为前端 Demo、主系统、测试脚本提供实时状态和结果接口。

系统主入口是 [app/main.py](/D:/camera/app/main.py)，配置入口是 [app/core/config.py](/D:/camera/app/core/config.py)。

## 3. 总体链路

当前运行链路可以概括为：

```text
RTSP Camera / Mock Camera
-> CameraSourceManager
-> CaptureWorker / SubprocessCaptureWorker
-> FrameBuffer
-> DetectionService
   -> YOLO person detector
   -> YOLO fall hint detector
-> TrackingWorkerService
   -> ByteTrack tracking
   -> target selection
-> PoseWorkerService
   -> YOLO / YOLO11 legacy / RTMPose / RTMPose ONNX / MMPose provider
-> BehaviorService
-> ResultPublisherService
   -> merge detection / tracking / pose / behavior / fall hint
   -> TemporalService
   -> FallFeatureBuilder
   -> FallFusionService
   -> FallEventReporterService
-> RealtimeResultStore.latest_published
-> WebSocket / HTTP integration API / Demo / main-system push
```

系统内部以“最新快照”为核心，而不是完整保存每一帧的长队列。`RealtimeResultStore` 保存各处理阶段的最新结果：

- `latest_detection`：人体检测结果。
- `latest_fall_detection`：跌倒提示检测结果。
- `latest_tracking`：跟踪后的目标结果。
- `latest_pose`：姿态结果。
- `latest_behavior`：行为结果。
- `latest_published`：最终融合并发布的结果。

这种设计优先保证实时性。过期结果会被 TTL、帧号差或 stale 状态过滤，不会无限堆积。

## 4. 启动与生命周期

FastAPI 应用在启动时通过 lifespan 初始化所有服务：

- `CameraSourceManager`：管理摄像头源、采集 worker 和帧缓存。
- `RealtimeResultStore`：内部实时结果交换中心。
- `DetectionService`：人体检测和跌倒提示检测。
- `TrackingService` / `TrackingWorkerService`：目标跟踪和目标锁定。
- `PoseService` / `PoseWorkerService`：姿态估计。
- `BehaviorService`：基础行为判断。
- `TemporalService`：时序窗口和跌倒序列模型。
- `FallFusionService`：跌倒融合判定。
- `FallEventReporterService`：确认跌倒事件落图、去重、推送和轮询状态。
- `AlertSimulatorService`：主系统告警联调模拟。
- `ResultPublisherService`：最终结果融合、发布、告警检查。
- `PeerManager`：WebRTC 视频连接管理。
- `ResultChannelManager`：WebSocket 结果广播。
- `StatusService`：系统状态聚合。

如果配置了 `DEFAULT_RTSP_URL`，或 `MOCK_CAMERA_ENABLED=true`，服务启动后会自动启动默认摄像头。

## 5. 摄像头采集功能

摄像头采集模块位于 `app/camera/`，主要职责是把 RTSP 或 mock 源转成系统可消费的最新帧。

关键能力：

- 支持默认摄像头自动启动。
- 支持 `/stream/start` 动态启动摄像头。
- 支持 `/stream/stop` 停止摄像头。
- 支持 `/stream/switch-host` 按主机信息切换 RTSP 地址。
- 支持 `/stream/probe` 探测目标 host/port 是否可达。
- 支持 `/stream/latest-frame.jpg` 输出最新原始帧。
- 支持 stale 检测和重连策略。
- 支持 OpenCV 后端和子进程采集相关配置。

关键状态字段：

- `stream_state`：`disconnected`、`connecting`、`connected`、`stale`、`reconnecting`。
- `connected`：采集后端是否认为源已连接。
- `frame_age_ms`：最新帧距离当前时间的年龄。
- `capture_fps`：近期采集帧率。
- `reconnect_count`：重连次数。

判断摄像头是否健康时，不应只看 `connected=true`。更可靠的组合是：

```text
stream_state=connected
frame_age_ms 较小
capture_fps 稳定大于 0
```

## 6. 人体检测功能

人体检测由 `DetectionService` 调用 YOLO 模型完成，默认模型路径来自：

```text
YOLO_MODEL_PATH=yolov8n.pt
YOLO_CONFIDENCE=0.35
YOLO_IMGSZ=640
YOLO_DEVICE=<可选>
DETECTION_INTERVAL_MS=100
```

职责：

- 输入最新摄像头帧。
- 输出 `label=person` 的人体框。
- 为后续跟踪、姿态、时序、融合提供基础对象。

人体检测是整条 AI 链路的基础。如果人体检测不稳定，跟踪、姿态、时序和跌倒融合都会受到影响。

## 7. 跌倒提示检测功能

跌倒提示检测同样在 `DetectionService` 中运行，使用独立 YOLO 模型：

```text
FALL_DETECTOR_ENABLED=true
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_v2_plus_b012_best.pt
YOLO_FALL_CONFIDENCE=0.25
YOLO_FALL_IMGSZ=640
FALL_DETECTOR_INTERVAL_MS=200
```

职责：

- 识别画面中的 `fall`、`falling`、`fallen`、`lying` 等跌倒相关候选框。
- 为融合逻辑提供 `fall_hint` 证据。
- 与人体框、跟踪目标、时序特征结合，而不是单独决定最终告警。

当前代码中强跌倒标签包括：

```text
fall
falling
fallen
```

弱提示标签包括：

```text
lying
```

弱提示不会直接确认跌倒，主要作为辅助证据。

## 8. 跟踪与目标锁定功能

跟踪模块位于 `app/tracking/` 和 `app/services/tracking_worker_service.py`，基于 ByteTrack。

职责：

- 接收人体检测框。
- 给同一人员分配稳定的 `track_id`。
- 短时间维持已有目标，减少检测偶发丢失造成的结果跳变。
- 为时序窗口、姿态匹配、事件去重提供目标身份。
- 在没有身份绑定时选择临时 `is_target` 目标。

相关配置：

```text
ENABLE_TRACKING=true
TRACKING_WORKER_FPS=20
BYTETRACK_TRACK_HIGH_THRESH=0.5
BYTETRACK_TRACK_LOW_THRESH=0.1
BYTETRACK_NEW_TRACK_THRESH=0.6
BYTETRACK_MATCH_THRESH=0.8
BYTETRACK_TRACK_BUFFER=30
BYTETRACK_FRAME_RATE=10
```

当前目标锁定不是完整的人脸身份识别，只是实时跟踪层面的临时目标选择。

## 9. 姿态估计功能

姿态估计由 `PoseService` 和 `PoseWorkerService` 负责，支持多个 provider：

- `disabled_placeholder`：不开启真实姿态，生成占位或空姿态。
- `yolo`：Ultralytics YOLO pose。
- `yolo11_legacy`：历史兼容的 YOLO11 姿态路径。
- `rtmpose`：OpenMMLab RTMPose。
- `rtmpose_onnx`：轻量 ONNX RTMPose 路径。
- `mmpose`：适配训练后的 MMPose 路径。

常见配置：

```text
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=800
POSE_MAX_FRAME_AGE_MS=800
POSE_MAX_TRACKING_FRAME_DELTA=2
POSE_INFERENCE_LOCK_WAIT_MS=160
```

姿态结果会写入对象的 `pose` 字段，典型用途：

- 判断低姿态、横卧、倒地倾向。
- 为时序模型提供头部、髋部、关键点置信度等特征。
- 辅助区分跌倒和坐下、弯腰、蹲下、正常躺卧。

启动时如果 `ENABLE_POSE=true` 且 `MAIN_SYSTEM_ALERT_ENABLED=true`，系统会执行姿态部署 guard。guard 不通过时会拒绝启动，避免把没有证据包或配置不合格的姿态链路用于正式告警。

## 10. 行为分析功能

行为模块由 `BehaviorService` 负责，当前是轻量行为判断层。

相关配置：

```text
ENABLE_BEHAVIOR=false
BEHAVIOR_RAPID_DESCENT_PX_PER_SEC=260
BEHAVIOR_LONG_STILL_SEC=5
BEHAVIOR_STILL_VELOCITY_PX_PER_SEC=18
BEHAVIOR_RESULT_TTL_MS=1500
```

它可以提供快速下降、长时间静止等行为线索，作为跌倒融合的补充证据。

## 11. 时序分析功能

时序模块由 `TemporalService` 和 `app/temporal/` 下的组件负责。

核心思想是：跌倒不是单帧图像问题，而是连续动作变化问题。系统会按目标维护特征窗口，并把连续特征输入时序模型或状态机。

关键配置：

```text
ENABLE_TEMPORAL=false
FEATURE_WINDOW_SIZE=32
TEMPORAL_MODEL_PROVIDER=mock
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
TEMPORAL_MODEL_WINDOW_SIZE=32
TEMPORAL_MODEL_INPUT_DIM=15
TEMPORAL_WARMUP_MIN_SIZE=16
TEMPORAL_TRACK_MODE=all_tracks
TEMPORAL_SEQUENCE_KEY_MODE=identity
```

时序特征来源包括：

- bbox 中心点变化。
- bbox 宽高比。
- 位移和速度。
- 低姿态状态。
- 姿态可用性。
- 姿态置信度。
- 头部和髋部高度关系。
- fall hint 相关证据。

输出会写入对象的 `temporal` 字段，典型字段包括：

- `fall_probability`
- `window_size`
- `features`
- `shadow`
- `field_rule_debug`
- `event_metadata`

## 12. 跌倒融合与确认功能

最终跌倒判定不是由单一模型直接给出，而是由 `ResultPublisherService`、`FallFeatureBuilder`、`TemporalService` 和 `FallFusionService` 联合完成。

融合输入：

- 人体检测证据。
- 跌倒提示检测证据。
- 跟踪稳定性。
- 姿态关键点和姿态质量。
- 行为线索。
- 时序模型概率。
- bbox 形态、位置、速度等场地规则。
- ADL 抑制逻辑。

融合输出写入每个 `DetectedObject`：

- `fall_decision`
- `alarm_preview`
- `features`
- `fusion_debug`

典型状态：

```text
normal
falling
fallen_candidate
fallen_confirmed
confirmed_fall
suppressed
```

推荐业务理解：

- `fallen_candidate`：存在跌倒嫌疑，但证据尚未达到正式告警标准。
- `fallen_confirmed` / `confirmed_fall`：确认跌倒，可触发正式事件和主系统告警。
- `suppressed`：更像日常活动或证据不足，被抑制。

正式告警通常要求：

```text
alarm_preview.confirmed=true
fall_state in ["fallen_confirmed", "confirmed_fall"]
risk_level in ["high", "critical"]
```

## 13. 日常活动抑制功能

ADL 指日常活动，例如坐下、蹲下、弯腰、正常躺卧、受控下降等。它们可能在单帧视觉上与跌倒相似，因此系统会通过 ADL 抑制和证据评分减少误报。

相关配置：

```text
FALL_V6_SCORING_ENABLED=true
FALL_V6_DECISION_ENABLED=false
FALL_EVIDENCE_CONFIRM_THRESHOLD=0.75
ADL_SUPPRESSION_CONFIRM_MAX=0.45
ADL_SUPPRESSION_SLOW_MAX=0.55
ADL_SUPPRESSION_BLOCK_THRESHOLD=0.65
TRACK_QUALITY_MIN_CONFIRM=0.70
SLOW_FALL_ENABLED=true
```

当系统判断更像日常活动时，结果会包含 `suppressed_reason`、`missing_conditions` 或相关 debug 字段，便于复盘。

## 14. 事件生成、快照和去重

`FallEventReporterService` 负责确认跌倒后的事件闭环：

- 检查最终 `VisionResult` 中是否有确认跌倒对象。
- 生成或复用 `incident_id`。
- 保存事件快照。
- 构造推送 payload。
- 推送到主系统。
- 保存最近告警，用于轮询接口。
- 对重复事件做冷却和复用处理。

重要字段：

- `incident_id`：一次跌倒事件的唯一业务 ID，主系统应使用它去重。
- `snapshot_url`：给主系统或前端展示的图片 URL。
- `snapshot_path`：Vision Service 本机快照路径，不建议直接暴露给用户。
- `fall_prob` / `fall_score`：跌倒概率或融合评分。
- `track_id`：跟踪目标 ID，便于排障，但不建议作为告警去重主键。

默认快照目录：

```text
FALL_EVENT_SNAPSHOT_DIR=logs/fall_events/snapshots
```

快照访问接口：

```http
GET /fall-events/snapshots/{filename}
```

## 15. 主系统告警推送功能

主系统推送由 `FallEventReporterService` 完成。配置项：

```text
MAIN_SYSTEM_ALERT_ENABLED=false
MAIN_SYSTEM_REPORT_DRY_RUN=false
MAIN_SYSTEM_BASE_URL=http://127.0.0.1:8090/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TIMEOUT_MS=10000
MAIN_SYSTEM_ALERT_COOLDOWN_SECONDS=90
MAIN_SYSTEM_ALERT_TOKEN=
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
VISION_SERVICE_PUBLIC_BASE_URL=http://127.0.0.1:8000
```

最终推送地址由 `MAIN_SYSTEM_BASE_URL` 和 `MAIN_SYSTEM_FALL_EVENT_PATH` 组成：

```text
{MAIN_SYSTEM_BASE_URL}{MAIN_SYSTEM_FALL_EVENT_PATH}
```

推送成功判断：

```text
HTTP status code < 400
```

主系统弹窗建议判断：

```text
event_type == "fall_confirmed"
AND fall_detected == true
AND status in ["fallen_confirmed", "confirmed_fall"]
AND risk_level in ["high", "critical"]
AND incident_id 未处理过
```

## 16. 身份注册与身份绑定功能

当前系统有两层身份相关能力。

第一层是本地身份注册接口：

- `POST /identity/enroll`
- `GET /identity/list`
- `DELETE /identity/{person_id}`

注册信息默认存储在：

```text
IDENTITY_STORE_DIR=data/identities
```

相关配置：

```text
ENABLE_IDENTITY=false
IDENTITY_MAX_IMAGES=5
INSIGHTFACE_MODEL_NAME=buffalo_l
INSIGHTFACE_CTX_ID=0
INSIGHTFACE_DET_SIZE=640
```

第二层是实时身份绑定：

```text
ENABLE_IDENTITY_BINDING=false
IDENTITY_SERVICE_URL=http://127.0.0.1:8100
IDENTITY_MATCH_INTERVAL_MS=1000
IDENTITY_MATCH_THRESHOLD=0.45
IDENTITY_BINDING_ASYNC=true
IDENTITY_BINDING_WORKER_FPS=1
```

当前跌倒主链路不依赖身份识别才能工作。身份能力主要用于后续目标绑定、人名显示和多系统联动。

## 17. 前端 Demo 与实时结果

前端 Demo 位于 `frontend_demo/`，由 FastAPI 挂载到：

```http
GET /demo
```

Demo 主要消费：

- WebRTC 视频流。
- WebSocket 实时结果。
- `/status` 状态。
- `/stream/latest-frame.jpg` 原始帧。

实时结果对象的统一 schema 是 `VisionResult`：

```json
{
  "type": "vision_result",
  "camera_id": "camera_01",
  "timestamp": "...",
  "frame_seq": 123,
  "frame_width": 640,
  "frame_height": 360,
  "objects": [
    {
      "label": "person",
      "confidence": 0.91,
      "bbox": [10, 20, 100, 220],
      "track_id": 3,
      "is_target": true,
      "person_id": null,
      "person_name": null,
      "identity_state": "target_locked",
      "pose": {},
      "behavior": {},
      "temporal": {},
      "fall_decision": {},
      "alarm_preview": {}
    }
  ],
  "detector": {}
}
```

## 18. 对外接口总览

### 18.1 健康与状态

```http
GET /healthz
GET /status?camera_id=camera_01
```

用途：

- 判断服务是否存活。
- 查看摄像头、采集、检测、跟踪、姿态、时序、推送状态。
- 排查 `frame_age_ms`、`capture_fps`、`analysis_fps`、最新结果等。

### 18.2 视频源控制

```http
POST /stream/start
GET  /stream/source?camera_id=camera_01
GET  /stream/latest-frame.jpg?camera_id=camera_01
POST /stream/switch-host
POST /stream/probe
POST /stream/stop
```

用途：

- 启停摄像头。
- 切换现场摄像头地址。
- 探测网络连通性。
- 拉取最新原始帧用于排障。

### 18.3 WebRTC 与 WebSocket

```http
POST /webrtc/offer
POST /webrtc/candidate
WS   /ws/results?camera_id=camera_01
GET  /demo
```

用途：

- 浏览器实时看视频。
- 前端订阅识别结果和 overlay 数据。

### 18.4 身份接口

```http
POST   /identity/enroll
GET    /identity/list
DELETE /identity/{person_id}
```

用途：

- 注册人员身份。
- 查询身份库。
- 删除身份。

### 18.5 集成接口

```http
GET /integration/connection-status
GET /integration/results/{camera_id}/latest
GET /integration/fall-alerts/{camera_id}/poll
```

用途：

- 主系统或第三方系统查看 Vision Service 与主系统连通性。
- 获取某路摄像头最新融合结果。
- 轻量轮询是否有需要弹窗的跌倒告警。

`/integration/results/{camera_id}/latest` 会把内部 `VisionResult` 转成更适合外部消费的字段，包括：

- `service_state`
- `camera_lost`
- `capture_stale`
- `source_fps`
- `analysis_fps`
- `fall_detected`
- `fall_state`
- `risk_level`
- `fall_prob`
- `incident_id`
- `snapshot_url`
- `alarm_confirmed`
- `metadata`

### 18.6 告警控制与模拟

```http
GET  /alerting/status
POST /alerting/endpoint
POST /alerting/simulation/start
POST /alerting/simulation/send-once
POST /alerting/simulation/stop
```

用途：

- 查看当前告警推送目标。
- 临时修改推送目标。
- 给主系统发送模拟跌倒事件，验证后端接收和前端弹窗。

### 18.7 跌倒事件快照

```http
GET /fall-events/snapshots/{filename}
```

用途：

- 主系统详情页展示事件截图。
- 联调时核对告警是否有实际画面证据。

## 19. 运行方式

安装依赖：

```powershell
cd D:\camera
python -m pip install -r requirements.txt
```

启动服务：

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

打开 Demo：

```text
http://127.0.0.1:8000/demo
```

如果没有配置 `DEFAULT_RTSP_URL` 且 `MOCK_CAMERA_ENABLED=true`，系统会使用 mock 摄像头，便于本地验证接口和前端流程。

## 20. 重要配置分组

### 20.1 摄像头与采集

```text
DEFAULT_CAMERA_ID=camera_01
DEFAULT_RTSP_URL=
MOCK_CAMERA_ENABLED=true
CAPTURE_BACKEND=opencv
STREAM_STALE_THRESHOLD_MS=3000
STREAM_STALE_RECONNECT_AFTER_MS=6000
OPENCV_CAPTURE_BUFFERSIZE=1
```

### 20.2 检测

```text
DETECTION_ENABLED=true
YOLO_MODEL_PATH=yolov8n.pt
YOLO_CONFIDENCE=0.35
FALL_DETECTOR_ENABLED=true
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_v2_plus_b012_best.pt
YOLO_FALL_CONFIDENCE=0.25
```

### 20.3 跟踪

```text
ENABLE_TRACKING=true
TRACKING_WORKER_FPS=20
ENABLE_TARGET_BINDING=false
```

### 20.4 姿态

```text
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=800
```

### 20.5 时序与融合

```text
ENABLE_TEMPORAL=false
FEATURE_WINDOW_SIZE=32
TEMPORAL_MODEL_PROVIDER=mock
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
FALL_CONFIRM_FRAMES=5
FALL_STILL_MS=1500
COOLDOWN_SECONDS=10
```

### 20.6 主系统推送

```text
MAIN_SYSTEM_ALERT_ENABLED=false
MAIN_SYSTEM_REPORT_DRY_RUN=false
MAIN_SYSTEM_BASE_URL=http://127.0.0.1:8090/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
VISION_SERVICE_PUBLIC_BASE_URL=http://127.0.0.1:8000
```

## 21. 数据与资产目录

主要目录：

- `app/`：服务端核心代码。
- `frontend_demo/`：浏览器 Demo 页面。
- `identity_service/`：独立身份服务相关代码。
- `models/`：项目模型、训练配置和指标。
- `scripts/`：训练、评估、验收、联调脚本。
- `tools/`：数据标注、采集、导入和辅助工具。
- `tests/`：自动化测试。
- `evaluations/`：评估结果和验收产物。
- `reports/`：专题报告。
- `docs/`：设计、接口、验收和交接文档。
- `logs/`：运行日志和跌倒事件快照。
- `artifacts/`：临时产物、备份、探测图片和数据清单。

根目录常见模型文件：

- `yolov8n.pt`
- `yolo11n-pose.pt`
- `yolo11s-pose.pt`
- `yolo_fall_detector_v2_recall_probe_best.pt`

`models/` 下常见项目模型：

- `yolo_fall_hint_v2_plus_b012_best.pt`
- `yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt`
- `yolo_fall_detector_v6_best.pt`
- `threshold_calibration.json`
- `train_config.json`

## 22. 典型联调流程

### 22.1 确认服务在线

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8000/status
```

### 22.2 确认摄像头有画面

```powershell
Invoke-RestMethod http://127.0.0.1:8000/stream/source
```

浏览器打开：

```text
http://127.0.0.1:8000/stream/latest-frame.jpg
```

### 22.3 查看最新集成结果

```powershell
Invoke-RestMethod http://127.0.0.1:8000/integration/results/camera_01/latest
```

### 22.4 检查主系统连通性

```powershell
Invoke-RestMethod http://127.0.0.1:8000/integration/connection-status
```

### 22.5 发送一次模拟告警

```powershell
$body = @{
  camera_id = "camera_01"
  track_id = "test_track"
  fall_prob = 0.93
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8000/alerting/simulation/send-once `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

## 23. 排障建议

### 23.1 Demo 没有画面

优先检查：

- `/healthz` 是否返回 `{"status":"ok"}`。
- `/stream/source` 中 `running`、`stream_state`、`frame_age_ms`、`capture_fps`。
- `/stream/latest-frame.jpg` 是否能打开。
- RTSP 地址、账号、端口是否正确。
- 是否正在使用 mock 摄像头。

### 23.2 有画面但没有检测框

优先检查：

- `DETECTION_ENABLED` 是否为 `true`。
- `YOLO_MODEL_PATH` 是否存在。
- `/status` 中 detection 相关状态和错误。
- 画面中是否真的有人。
- 模型置信度是否过高。

### 23.3 有检测但没有跌倒告警

优先检查：

- `/integration/results/camera_01/latest` 中 `objects[].fall_decision`。
- `alarm_preview.confirmed` 是否为 `true`。
- `missing_conditions` 或 `rejected_reason`。
- `FALL_DETECTOR_ENABLED` 和跌倒模型路径。
- `ENABLE_TEMPORAL`、时序窗口是否 ready。
- 姿态是否启用和可用。
- 是否被 ADL 抑制。

### 23.4 已确认跌倒但主系统没有弹窗

优先检查：

- `MAIN_SYSTEM_ALERT_ENABLED` 是否为 `true`。
- `MAIN_SYSTEM_REPORT_DRY_RUN` 是否为 `false`。
- `MAIN_SYSTEM_BASE_URL` 和 `MAIN_SYSTEM_FALL_EVENT_PATH` 是否正确。
- `/alerting/status` 当前 endpoint。
- 主系统是否返回 2xx。
- 主系统是否用 `incident_id` 去重导致未重复弹窗。
- `snapshot_url` 是否能从主系统前端访问。

### 23.5 结果延迟或卡顿

优先检查：

- `capture_fps` 和 `analysis_fps`。
- `frame_age_ms` 是否持续升高。
- GPU/CPU 占用。
- 姿态模型是否过慢。
- fall detector 与 person detector 是否串行拖慢。
- `POSE_INFERENCE_LOCK_WAIT_MS`、`POSE_MAX_INFERENCE_MS` 和 circuit breaker 状态。

## 24. 当前架构边界与后续优化方向

当前系统已经具备完整闭环：

```text
采集 -> 检测 -> 跟踪 -> 姿态/时序 -> 融合 -> 快照 -> 主系统告警
```

但仍有几个需要关注的架构边界：

- 人体检测和跌倒提示检测当前仍在 `DetectionService` 内串联执行，一个模型变慢可能影响另一部分刷新。
- 多个视觉模型可能共享推理锁，稳定性更高，但并发性能会受限制。
- `ResultPublisherService` 同时承担结果合并、时序调用、融合、告警检查，职责较重。
- 姿态链路正式启用时需要证据包和部署 guard 支持，否则会拒绝进入告警生产模式。

建议后续优化方向：

- 将 fall hint detector 拆成独立 worker。
- 给每个模型结果增加统一 TTL、健康状态和超时统计。
- 让 fusion 使用“可降级的最新证据”，不强等所有模型同步。
- 为慢模型增加 circuit breaker 和 cooldown。
- 把告警 reporter 与最终结果发布进一步解耦，减少发布延迟。

## 25. 一句话总结

当前 `Vision Service` 是一个面向养老看护场景的实时视觉跌倒检测服务：它通过单路摄像头采集、多模型证据、目标跟踪、姿态与时序分析、融合判定和主系统推送，完成从实时画面到确认跌倒告警的全链路闭环。
