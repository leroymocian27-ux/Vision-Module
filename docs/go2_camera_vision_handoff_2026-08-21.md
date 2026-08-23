# 机器狗 Go2 画面接入与视觉处理工程交接文档

版本：`2026-08-21`  
适用工程：`E:\国赛\camera-service`  
面向对象：视觉算法工程师、后端工程师、机器狗/设备接入工程师、现场联调工程师  
当前运行架构：`PIPELINE_MODE=post_fall_v2`

> 本文是当前项目的工程交接入口。它描述“机器狗相机画面如何进入视觉服务、如何被处理、如何观察结果、如何继续完成现场接入”，并明确当前实现边界。文中不记录真实 RTSP 密码、Token、内网敏感地址或个人信息。

---

## 1. 先看结论

### 1.1 当前已经具备的能力

本项目已经具备一套可运行的实时视觉服务：

```text
RTSP / 本地视频 / Mock
    -> CameraSourceManager
    -> CaptureWorker
    -> FrameBuffer（最新帧）
    -> Post-Fall V2 FrameSampler（5 FPS）
    -> EfficientNet-B0 ONNX
    -> BinaryDecisionAggregator
    -> FallEvent
    -> 结果缓存 / WebSocket / WebRTC / 事件 Outbox
    -> 事件后关键帧采集
    -> 本地 Qwen 辅助描述（可选）
```

当前默认模型和二分类决策属于 Binary-First 架构：

- EfficientNet-B0 二分类模型负责正式跌倒确认。
- 多帧聚合器负责去抖、持续性判断、恢复和冷却。
- Qwen 只对已经确认的事件做画面描述和辅助复核。
- Qwen 不得创建、取消、推翻或替代二分类事件。
- 外部主系统告警和真实事件投递在安全配置中默认关闭。

### 1.2 当前不能直接承诺的能力

以下能力尚未完成现场验收，不能在交接时表述为“已上线”：

1. 尚未完成当前机器狗目标相机的 RTSP 接入验收。
2. 尚未取得合格的目标相机标定集和独立验收集。
3. 当前阈值 `0.3979087471961975` 是 OOF 工程基线，不是目标相机生产标定阈值。
4. 当前系统按“整幅画面”输入模型，尚未支持经过验证的机器狗特定 ROI 策略。
5. 仓库中的 `UnitreeGo2Adapter` 是机器人控制侧安全骨架，不负责读取 Go2 相机视频，也没有实现 Unitree SDK/DDS 控制。
6. 机器狗视频若不是 RTSP、文件或 Mock，需要新增桥接器或新增帧输入适配层。
7. 多人画面下当前 PFV2 只能输出摄像头级跌倒信号，不具备可靠的人员级归因。

### 1.3 当前验收状态

权威状态记录见：

```text
docs/post_fall_v2_current_state.md
artifacts/post_fall_v2/finalization/final_p3_gate_report.json
```

截至 2026-08-14 的状态：

| 项目 | 状态 |
| --- | --- |
| PFV2 focused tests | PASS |
| 全量测试 | PASS，738 passed，2 warnings |
| Mock 运行链路 | PASS |
| 通用回放 E2E | PASS |
| Qwen 解析鲁棒性 | PASS |
| 目标机器狗相机数据 | BLOCKED |
| 目标相机标定 | BLOCKED |
| 目标相机独立验收 | BLOCKED |
| 当前授权 RTSP | BLOCKED |
| `P3_ALLOWED` | `NO` |

---

## 2. 重要概念边界

### 2.1 “机器狗画面接入”和“机器狗控制接入”是两条链

本项目包含两个相互独立的能力边界：

```text
机器狗相机视频
    -> 视频桥接 / RTSP
    -> camera-service
    -> 视觉算法与事件输出
```

```text
主系统告警 / 人工审批
    -> Robot Assist Service
    -> Mock 或未来的 Go2 Adapter
    -> 机器狗任务执行
```

当前视觉服务只需要一个可解码的视频源。它不会因为配置了 `ROBOT_ASSIST_MODE=go2` 就自动获得机器狗相机画面。

当前 Robot Assist 相关代码：

```text
robot_assist_service/main.py
robot_assist_service/api.py
robot_assist_service/service.py
robot_assist_service/adapters/mock.py
robot_assist_service/adapters/unitree_go2.py
```

`robot_assist_service/adapters/unitree_go2.py` 明确禁止真实 Go2 执行，当前返回：

```text
real Go2 control is forbidden until the dedicated read-only and safety gates pass
```

因此，机器狗相机接入工程师不应从 Robot Assist Service 中寻找视频读取逻辑。

### 2.2 当前视觉服务支持的源类型

由 `app/camera/source_models.py` 判断：

| 源类型 | 示例 | 当前支持 |
| --- | --- | --- |
| Mock | `mock://colorbars` | 支持 |
| RTSP | `rtsp://user:***@host:port/path` | 支持 |
| RTSPS | `rtsps://...` | 代码识别，现场需验证 OpenCV/FFmpeg 支持 |
| 本地视频文件 | `E:\data\go2_demo.mp4` | 支持 |
| HTTP/HLS | `http://...`、`https://...` | 不按本地文件处理，需现场验证或桥接 |
| Go2 原生 DDS/UDP/SDK 帧 | 取决于设备 SDK | 当前不支持，需新增适配 |

推荐现场方案：

```text
Go2 相机输出
    -> 设备侧或旁路机转换为 RTSP
    -> camera-service /stream/start
```

如果 Go2 只能通过 SDK 回调返回图像，推荐新增独立的 `go2_video_bridge`，把 SDK 图像发布为 RTSP。不要把 SDK、DDS、机器人控制和视觉模型推理全部塞进 `CaptureWorker`。

---

## 3. 系统架构与数据流

### 3.1 服务装配

FastAPI 应用入口为：

```text
app/main.py
```

启动时主要完成：

1. 读取 `.env` 或 `VISION_SERVICE_ENV_FILE` 指定的配置文件。
2. 创建 `CameraSourceManager` 和 `FrameBuffer`。
3. 创建实时结果、事件 Outbox、WebSocket、WebRTC 管理器。
4. 创建 PFV2 二分类器、聚合器、关键帧会话和 Qwen 服务。
5. 创建 `StreamService`。
6. 如果配置了默认 RTSP，或启用了 Mock，自动启动默认摄像头。

### 3.2 PFV2 正式运行链路

```mermaid
flowchart LR
    A["Go2 Camera"] --> B["RTSP Bridge"]
    B --> C["CaptureWorker"]
    C --> D["FrameBuffer latest"]
    D --> E["FrameSampler 5 FPS"]
    E --> F["EfficientNet-B0 ONNX"]
    F --> G["BinaryDecisionAggregator"]
    G --> H["FallEvent"]
    H --> I["VisionResult"]
    I --> J["WebSocket / integration API"]
    I --> K["Frontend WebRTC overlay"]
    H --> L["Post-fall keyframe session"]
    L --> M["Local Qwen advisory"]
    M --> I
```

关键代码：

| 文件 | 责任 |
| --- | --- |
| `app/main.py` | 创建并连接运行时服务 |
| `app/services/stream_service.py` | 启停视频源和按模式启动算法 worker |
| `app/camera/source_manager.py` | 管理每个 `camera_id` 的源、缓存和采集 worker |
| `app/camera/capture_worker.py` | OpenCV 读取 Mock、RTSP、本地文件并写入最新帧 |
| `app/camera/frame_buffer.py` | 线程安全的最新帧缓存 |
| `app/post_fall_v2/frame_sampler_service.py` | 按时间采样，不消费旧帧 |
| `app/post_fall_v2/fall_binary_classifier_service.py` | ONNX 加载、SHA256 校验、预处理和推理 |
| `app/post_fall_v2/binary_decision_aggregator.py` | 多帧聚合和事件状态机 |
| `app/post_fall_v2/post_fall_runtime_service.py` | PFV2 采样线程、推理线程、事件、发布和关键帧编排 |
| `app/post_fall_v2/keyframe_collection_session.py` | 事件前后关键帧定位和后采集 |
| `app/post_fall_v2/qwen_fall_analyzer.py` | 本地 Qwen 辅助描述适配器 |

### 3.3 PFV2 与旧链路的隔离

当 `PIPELINE_MODE=post_fall_v2` 时，`StreamService.start()` 只启动：

```text
CaptureWorker
PostFallV2RuntimeService
```

不会为该 camera 启动旧链路的：

```text
DetectionService
FallHintWorkerService
TrackingWorkerService
PoseWorkerService
TemporalWorkerService
FusionWorkerService
ResultPublisherService
```

这条隔离由 `tests/test_post_fall_v2_stream_mode_isolation.py` 保护。切换模式或扩展多模型时，不能悄悄把旧链路重新接回正式跌倒决策。

---

## 4. 机器狗视频接入合同

### 4.1 机器狗侧必须提供的信息

现场开始前，机器狗/设备工程师必须提供以下信息：

| 信息 | 示例或要求 |
| --- | --- |
| 视频输出方式 | RTSP、RTMP、HTTP、SDK 回调、ROS2、DDS、UDP |
| 设备 IP | 现场实际地址，不写历史地址 |
| 视频端口 | 例如 `554`、`8554`、`10554` |
| 完整视频路径 | 例如 `/stream/main` |
| 账号 | 通过现场安全渠道提供 |
| 密码 | 不写入仓库和普通文档 |
| 传输协议 | 优先 TCP |
| 编码 | H.264 优先，H.265 需验证解码环境 |
| 分辨率 | 例如 1920x1080 |
| 帧率 | 建议稳定在 10 FPS 以上，算法采样为 5 FPS |
| 码流类型 | 主码流或子码流 |
| 画面方向 | 前视、后视、云台、机身固定 |
| 机器狗运动时画面 | 是否有强抖动、自动曝光、夜间红外 |
| 网络拓扑 | Go2、桥接机、视觉服务是否同网段 |
| 断网行为 | 断开后是否恢复、恢复时 URL 是否变化 |
| 隐私授权 | 是否允许保存关键帧和发送给本地 Qwen |

### 4.2 推荐的 RTSP 接入方式

机器狗相机输出经确认后，用以下方式接入：

```powershell
cd E:\国赛\camera-service

$body = @{
  camera_id = "go2_front_camera"
  rtsp_url = "rtsp://<user>:<password>@<go2-or-bridge-ip>:<port>/<path>"
} | ConvertTo-Json

Invoke-RestMethod "http://127.0.0.1:8000/stream/start" `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

注意：

- 真实密码只在本地进程环境或受控 `.env` 中保存。
- 返回内容会通过 `mask_source_url()` 隐藏密码。
- 同一个 `camera_id` 只能有一个权威视频源。
- 如果同时传 `rtsp_url`、`main_rtsp_url`、`analysis_rtsp_url`，服务按优先级选择 `rtsp_url`，然后是 `analysis_rtsp_url`，最后是 `main_rtsp_url`。
- 当前 `display_source` 和 `analysis_source` 都是 single source，不会自动双拉流。

### 4.3 Go2 原生 SDK 接入的推荐改造

如果现场无法提供 RTSP，而只能通过 Go2 SDK 获取图像，建议新增以下独立结构：

```text
go2_video_bridge/
  source_adapter.py       # Go2 SDK / DDS / ROS2 只负责收图像
  rtsp_publisher.py       # 将 BGR/RGB 帧发布为 RTSP
  health.py               # 输出帧率、延迟、断线和源代次
  README.md
```

桥接器必须具备：

1. 单一输出地址，例如 `rtsp://127.0.0.1:8554/go2_front`。
2. 帧时间戳和源代次。
3. 断线重连。
4. 输入帧为空或过旧时可观测的错误状态。
5. 不发送任何机器人运动控制指令。
6. 不将图片写入公共日志。

不建议第一阶段直接修改 `FrameBuffer` 让它接收跨进程回调。那会同时改变采集、线程安全、源代次和 WebRTC 的现有契约，现场排障成本较高。

---

## 5. 环境与启动

### 5.1 环境要求

项目当前依赖：

```text
Python 3.10
FastAPI
Uvicorn
OpenCV
NumPy
aiortc
av
Ultralytics
Pydantic 2
onnxruntime
```

当前机器已经存在：

```text
E:\国赛\camera-service\.venv
```

建议使用项目虚拟环境：

```powershell
cd E:\国赛\camera-service
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

### 5.2 安全 Mock 启动

用于验证软件链路，不代表真实机器狗相机通过：

```powershell
cd E:\国赛\camera-service
.\scripts\start_safe_demo.ps1
```

默认访问：

```text
http://127.0.0.1:8000/demo
```

该脚本使用：

```text
configs/safe_demo.env
```

并设置：

```text
PIPELINE_MODE=post_fall_v2
MOCK_CAMERA_ENABLED=true
DEFAULT_RTSP_URL=
EVENT_DELIVERY_ENABLED=false
MAIN_SYSTEM_ALERT_ENABLED=false
```

### 5.3 目标相机候选启动

`configs/post_fall_v2_candidate.env` 是目标 RTSP 候选配置，不等于生产批准配置。

推荐通过环境变量覆盖目标地址：

```powershell
cd E:\国赛\camera-service

$env:VISION_SERVICE_ENV_FILE = (Resolve-Path ".\configs\post_fall_v2_candidate.env")
$env:DEFAULT_RTSP_URL = "rtsp://<user>:<password>@<host>:<port>/<path>"
$env:MOCK_CAMERA_ENABLED = "false"
$env:DEVICE_DISCOVERY_ENABLED = "false"

.\.venv\Scripts\python.exe -m uvicorn app.main:app `
  --host 0.0.0.0 `
  --port 8000
```

如需后台启动，建议复制或仿照 `scripts/start_safe_demo.ps1`，不要把明文 RTSP 写入新的脚本。

### 5.4 启动前检查

```powershell
cd E:\国赛\camera-service

.\.venv\Scripts\python.exe scripts\validate_config.py `
  --profile configs\post_fall_v2_candidate.env

Test-Path .\models\post_fall_v2\efficientnet_b0\fall_candidate_efficientnet_b0.onnx

Get-FileHash `
  .\models\post_fall_v2\efficientnet_b0\fall_candidate_efficientnet_b0.onnx `
  -Algorithm SHA256
```

当前模型 SHA256：

```text
e9871cdb4687055fb5d934dd994c2ad883adac0c2acab375c240f8e005ee04cc
```

---

## 6. RTSP 接入验证顺序

### 6.1 先验证网络端口

端口探测只说明 TCP 可达，不说明 RTSP 可以解码：

```powershell
$body = @{
  host = "<go2-or-bridge-ip>"
  port = 8554
  timeout_ms = 1500
} | ConvertTo-Json

Invoke-RestMethod "http://127.0.0.1:8000/stream/probe" `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

### 6.2 再验证服务是否能收到帧

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/stream/source?camera_id=go2_front_camera" |
  ConvertTo-Json -Depth 10

Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=go2_front_camera" |
  ConvertTo-Json -Depth 20
```

必须观察：

```text
running=true
connected=true
stream_state=connected
frame_seq 持续增长
frame_width/frame_height 有值
frame_age_ms 不持续增长
capture_fps > 0
last_error=null
```

### 6.3 最后验证实际图像内容

```powershell
Invoke-WebRequest `
  "http://127.0.0.1:8000/stream/latest-frame.jpg?camera_id=go2_front_camera" `
  -OutFile ".\artifacts\go2_latest_frame.jpg"
```

如果返回 404：

- 不要把它解释成“当前没有跌倒”。
- 检查 `stream_state`、`frame_status`、`last_error` 和 `frame_age_ms`。
- `safe_to_interpret_as_no_fall=false` 时，算法结果应视为不可用。

### 6.4 验证结果推送

REST：

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8000/integration/results/go2_front_camera/latest" |
  ConvertTo-Json -Depth 30
```

WebSocket：

```text
ws://127.0.0.1:8000/ws/results?camera_id=go2_front_camera
```

前端：

```text
http://<vision-service-ip>:8000/demo
```

WebRTC 是画面传输；WebSocket 是检测结果传输。两者不是同一条链，WebRTC 正常不代表推理正常，WebSocket 有结果也不代表当前画面没有延迟。

---

## 7. PFV2 算法与参数

### 7.1 模型输入

当前正式输入策略：

```text
POST_FALL_V2_INPUT_POLICY=FULL_FRAME_TRAIN_MATCHED
```

`FallBinaryClassifierService.preprocess_bgr()` 做的处理：

1. 输入必须是 `H x W x 3` 的 BGR NumPy 数组。
2. BGR 转 RGB。
3. 按最长边等比例缩放到 224。
4. 使用 `BORDER_REFLECT_101` 补齐到 `224 x 224`。
5. 除以 255。
6. ImageNet mean/std 标准化。
7. 转成 `float32 NCHW`，形状为 `1 x 3 x 224 x 224`。

当前不应擅自改成：

- 人体框 ROI；
- 机器狗头部/云台裁剪；
- 只保留画面下半区；
- 先运行 YOLO 再裁剪；
- 改变缩放和 Padding 规则。

除非同步完成目标相机数据重采集、训练/验证和标定。

### 7.2 二分类阈值与多帧确认

当前基线：

| 参数 | 当前值 |
| --- | --- |
| 采样频率 | 5 FPS |
| 窗口长度 | 8 帧 |
| 窗口正例数 | 至少 4 帧 |
| 连续正例数 | 至少 3 帧 |
| 候选持续时间 | 至少 800 ms |
| 恢复时间 | 1500 ms |
| 冷却时间 | 3000 ms |
| 二分类阈值 | 0.3979087471961975 |

简化状态机：

```text
NORMAL
  -> FALL_CANDIDATE       首个正例
  -> EVENT_ACTIVE         满足窗口、连续帧、持续时间
  -> RECOVERY_PENDING     由正变负
  -> COOLDOWN             持续负达到恢复时间
  -> NORMAL               冷却结束
```

重要行为：

- 单帧正例不会直接创建事件。
- 持续躺倒只创建一个事件，不会每帧重复告警。
- 恢复并完成冷却后，下一次跌倒才创建新的 `incident_id`。
- 相机断流不能被解释为负例。
- Qwen 超时、失败或解析失败不能删除已经确认的 `FallEvent`。

### 7.3 事件后关键帧

默认请求的关键帧偏移：

```text
-3000 ms, -1000 ms, 0 ms, +1000 ms, +3000 ms, +5000 ms
```

允许的最大时间误差：

```text
750 ms
```

PFV2 在事件确认时立即创建事件，并在事件后继续采集未来帧。关键帧状态可能为：

```text
collecting
ready
degraded
```

未来帧不可用时不能阻塞正式跌倒事件。即使关键帧不完整，事件也可以进入结果和 Outbox。

### 7.4 Qwen 辅助边界

当前 Qwen 配置是本地 Ollama：

```text
POST_FALL_V2_QWEN_PROVIDER=qwen_keyframe
POST_FALL_V2_QWEN_BASE_URL=http://127.0.0.1:11434/api/chat
POST_FALL_V2_QWEN_MODEL=qwen-vision-cn:latest
```

安全要求：

- Endpoint 必须是 localhost。
- 图片输入必须经过隐私审批。
- 图片只传内存压缩副本，不在公共 payload 中泄漏路径。
- Qwen 只输出视觉辅助描述。
- 不输出医疗诊断。
- Qwen 不得成为正式跌倒决策权威。

---

## 8. 主要接口清单

### 8.1 服务和状态

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/healthz` | HTTP 进程存活检查 |
| `GET` | `/status` | 业务状态总览 |
| `GET` | `/status?camera_id=...` | 指定 camera 状态 |
| `GET` | `/stream/source?camera_id=...` | 当前源和采集状态 |
| `GET` | `/stream/latest-frame.jpg?camera_id=...` | 最新帧 |
| `GET` | `/integration/connection-status` | 集成连接状态 |
| `GET` | `/integration/results/{camera_id}/latest` | 最新视觉结果 |
| `GET` | `/integration/fall-alerts/{camera_id}/poll` | 告警轮询 |

### 8.2 流控制

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/stream/start` | 启动或切换视频源 |
| `POST` | `/stream/stop` | 停止视频源 |
| `POST` | `/stream/probe` | TCP 端口探测 |
| `POST` | `/stream/switch-host` | 根据主机、端口、路径拼 RTSP |
| `POST` | `/stream/mock-fault` | 仅 safe_demo 注入 Mock 故障 |

### 8.3 实时画面和结果

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/webrtc/offer` | WebRTC Offer |
| `POST` | `/webrtc/candidate` | WebRTC ICE candidate |
| `WS` | `/ws/results?camera_id=...` | 实时 VisionResult |

### 8.4 事件和关键帧

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/events/status` | 事件流水线状态 |
| `GET` | `/events/latest?camera_id=...` | 最新事件 |
| `GET` | `/events/{incident_id}` | 事件详情 |
| `GET` | `/events/{incident_id}/keyframes/{selector}` | 事件关键帧 |
| `GET` | `/events/delivery/status` | 投递状态 |

事件接口依赖相应事件配置。PFV2 内存事件和结果发布不应因为外部 Delivery 关闭而失效。

---

## 9. 结果字段解释

PFV2 发布的 `VisionResult` 仍复用统一的 `objects` 结构，以保持前端和旧集成接口兼容。

典型对象：

```json
{
  "label": "person",
  "confidence": 1.0,
  "bbox": [0, 0, 1920, 1080],
  "track_id": 0,
  "is_target": true,
  "temporal": {
    "source": "post_fall_v2_binary",
    "fall_probability": 0.81,
    "window_size": 8
  },
  "fall_decision": {
    "source": "post_fall_v2_binary",
    "binary_label": "FALL",
    "fall_state": "confirmed",
    "incident_id": "pfv2-go2_front_camera-xxxxxxxxxxxx",
    "vlm_status": "collecting_keyframes"
  },
  "alarm_preview": {
    "confirmed": true,
    "risk_level": "high",
    "fall_probability": 0.81,
    "source": "post_fall_v2_binary"
  }
}
```

注意：

- `bbox` 在 PFV2 当前是整幅画面占位框，不应解释为真实人体检测框。
- `track_id=0` 是 PFV2 摄像头级事件占位值，不是可靠的人体跟踪 ID。
- `fall_state=confirmed` 表示二分类聚合器确认事件。
- `vlm_status=completed` 只表示辅助描述完成，不表示 Qwen 参与确认。
- `safe_to_interpret_as_no_fall=false` 时不能把 `NON_FALL` 当作安全结论。

---

## 10. 状态监控与故障定位

### 10.1 推荐排查顺序

```text
1. 进程和端口
2. /healthz
3. /status
4. /stream/source
5. /stream/latest-frame.jpg
6. frame_seq 是否增长
7. stream_state 和 frame_age_ms
8. post_fall_v2_runtime 状态
9. /integration/results/{camera_id}/latest
10. 日志和测试报告
```

### 10.2 常见问题

#### 页面能打开但没有画面

检查：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/stream/source?camera_id=go2_front_camera"
Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=go2_front_camera"
```

重点字段：

```text
running
connected
stream_state
frame_seq
frame_age_ms
capture_fps
last_error
reconnect_count
```

处理顺序：

1. 确认 Go2 或桥接器进程还在发布。
2. 先用端口探测确认网络。
3. 用 VLC、FFplay 或 OpenCV 单独验证 RTSP。
4. 确认 TCP/UDP 传输模式。
5. 检查 H.264/H.265 解码支持。
6. 检查视觉服务与桥接器是否使用同一个地址和端口。

#### `connected=true` 但画面不更新

`connected=true` 只表示采集后端认为源已打开，不代表最新帧持续到达。

如果出现：

```text
frame_age_ms 持续上升
stream_state=stale
frame_status=stale
```

应按画面停滞处理。当前默认：

```text
STREAM_STALE_THRESHOLD_MS=3000
STREAM_STALE_RECONNECT_AFTER_MS=6000
```

#### 画面正常但没有 PFV2 推理

检查：

```text
pipeline_mode=post_fall_v2
post_fall_v2.enabled=true
binary_model_loaded=true
frames_sampled > 0
frames_processed > 0
last_error=null
```

模型无法加载时重点看：

- 模型路径是否相对于 `camera-service` 根目录。
- ONNX 文件是否存在。
- SHA256 是否匹配。
- `onnxruntime` 是否安装。
- ONNX 输入名是否为 `input`。
- ONNX 输出名是否为 `logits`。

#### 有 `NON_FALL` 但无法判断是否安全

如果摄像头没有新帧、帧过旧、源已断开或相机处于重连状态，不能把 `NON_FALL` 当成安全结论。前端和主系统应优先展示视频不可用/结果降级状态。

#### Qwen 失败

Qwen 失败只影响：

```text
vlm_status
vlm_analysis
vlm_summary
```

不应影响：

```text
FallEvent
fall_state=confirmed
incident_id
binary evidence
```

检查：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=go2_front_camera" |
  ConvertTo-Json -Depth 30
```

重点字段：

```text
vlm_enabled
vlm_provider
vlm_model
vlm_queue_depth
vlm_active_count
vlm_call_count
vlm_rejected_count
keyframe_collection_status
```

---

## 11. 运行日志、证据和文件位置

### 11.1 日志

```text
logs/vision_safe_demo.out.log
logs/vision_safe_demo.err.log
logs/vision_local.out.log
logs/vision_local.err.log
```

现场建议为每次联调建立独立目录，至少记录：

```text
启动配置摘要
服务启动时间
camera_id
源代次 source_generation
RTSP 掩码地址
/status 定时快照
关键帧或截图的 SHA256
异常时间和错误
```

### 11.2 模型资产

```text
models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx
models/post_fall_v2/efficientnet_b0/MODEL_CARD.md
models/post_fall_v2/efficientnet_b0/summary.json
models/post_fall_v2/efficientnet_b0/deployment_verification.json
```

### 11.3 PFV2 验收证据

```text
artifacts/post_fall_v2/finalization/baseline_snapshot.json
artifacts/post_fall_v2/finalization/runtime_validation_report.json
artifacts/post_fall_v2/finalization/replay_e2e_report.json
artifacts/post_fall_v2/finalization/qwen_robustness_report.json
artifacts/post_fall_v2/finalization/target_data_inventory.json
artifacts/post_fall_v2/finalization/calibration_report.json
artifacts/post_fall_v2/finalization/acceptance_report.json
artifacts/post_fall_v2/finalization/final_p3_gate_report.json
```

### 11.4 敏感数据规则

禁止进入普通日志、公共 API 或提交记录：

- 明文 RTSP 密码；
- 主系统 Token；
- 完整绝对路径；
- 原始人脸、原始视频和未经审批的关键帧；
- Go2 控制密钥；
- 设备序列号与不必要的个人信息。

---

## 12. 测试与验收计划

### 12.1 代码回归

```powershell
cd E:\国赛\camera-service
.\.venv\Scripts\python.exe -m pytest `
  tests\test_post_fall_v2_binary_decision_aggregator.py `
  tests\test_post_fall_v2_runtime_service.py `
  tests\test_post_fall_v2_runtime_keyframe_collection.py `
  tests\test_post_fall_v2_stream_mode_isolation.py -q
```

重点保证：

- 单帧正例不创建事件。
- 持续正例只创建一个事件。
- 恢复和冷却后可以创建第二个事件。
- 关键帧缺失时事件仍然存在。
- Qwen 失败或超时时事件不被删除。
- PFV2 不启动旧链路 worker。

### 12.2 Mock 运行验收

```powershell
cd E:\国赛\camera-service
.\scripts\start_safe_demo.ps1

Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod "http://127.0.0.1:8000/status?camera_id=camera_01"
Invoke-RestMethod "http://127.0.0.1:8000/stream/source?camera_id=camera_01"
```

Mock 通过只说明：

- HTTP 服务能启动；
- Mock 源能产出帧；
- PFV2 线程能运行；
- WebSocket/WebRTC/结果接口基本可用。

Mock 不能证明：

- Go2 相机 RTSP 可用；
- 目标相机的阈值有效；
- 目标场景误报率；
- 机器狗运动时的画面稳定性。

### 12.3 目标 RTSP 验收

目标 RTSP 至少连续观察 10 分钟，建议 30 分钟。验收条件：

```text
connected=true
stream_state=connected
frame_seq 单调增长
frame_width/frame_height 稳定
capture_fps 达到设备预期
frame_age_ms < 1000 ms 为主
last_error=null
reconnect_count 不持续增加
latest-frame.jpg 能看到当前画面
```

若使用子进程采集后端，还要检查：

```text
capture_process_alive=true
capture_process_last_error=null
capture_ipc_decode_errors=0
capture_ipc_dropped_frames 可解释
```

### 12.4 目标相机算法验收

必须使用当前机器狗相机采集的数据，不能用生成视频替代：

| 数据集 | 建议内容 |
| --- | --- |
| 标定集 | 18 个 session，包含正常活动、硬负例和跌倒 |
| 独立验收集 | 12 个 session，人与场景不能与标定集泄漏 |
| 正常活动 | 站立、行走、坐下、弯腰、下蹲、跪姿 |
| 硬负例 | 床上躺、沙发躺、正常地面躺、短暂低姿态 |
| 跌倒 | 仰倒、侧倒、俯倒、慢倒、快倒、遮挡 |
| 特殊场景 | 启动时已倒地、断线重连后已倒地 |

标定流程：

1. 只在标定集上扫描阈值和聚合参数。
2. 冻结阈值、窗口、连续帧、候选持续时间、恢复和冷却。
3. 将冻结参数写入带时间和数据 SHA256 的报告。
4. 独立验收集只运行一次，不重新调参。
5. 通过后才讨论真实外部告警。

### 12.5 外部事件投递验收

外部投递必须后置，顺序如下：

```text
Mock -> 目标 RTSP -> 目标域回放 -> 目标域独立验收 -> dry_run -> staging post -> production approval
```

默认保持：

```text
MAIN_SYSTEM_ALERT_ENABLED=false
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_POST_APPROVED=false
```

除非已有明确批准，不得打开真实 POST。

---

## 13. 机器狗接入待办清单

### A. 设备和视频源

- [ ] 确认 Go2 相机输出方式。
- [ ] 确认真实 IP、端口、路径和认证。
- [ ] 确认主码流/子码流的分辨率、帧率和编码。
- [ ] 确认视觉服务主机可访问视频源。
- [ ] 如非 RTSP，完成旁路 RTSP bridge。
- [ ] 验证 Go2 行走、转向、上下坡时视频不断流。

### B. 视觉服务

- [ ] 使用唯一 `camera_id`，建议 `go2_front_camera`。
- [ ] 使用 `post_fall_v2_candidate.env`，关闭 Mock。
- [ ] 校验 ONNX SHA256。
- [ ] 启动后确认 `binary_model_loaded=true`。
- [ ] 确认 `frame_seq`、采样数和处理数增长。
- [ ] 确认外部 Delivery 仍为关闭。

### C. 数据和模型

- [ ] 采集 18 个标定 session。
- [ ] 采集 12 个独立验收 session。
- [ ] 保存原始视频、设备信息、相机位姿和时间戳。
- [ ] 做跨 session 去重和数据清单。
- [ ] 完成目标域阈值转移报告。
- [ ] 完成硬负例报告。
- [ ] 完成独立验收报告。

### D. 系统联调

- [ ] 完成 WebRTC 画面验收。
- [ ] 完成 WebSocket 结果验收。
- [ ] 完成 `integration/results` 兼容性验收。
- [ ] 完成事件 Outbox dry-run。
- [ ] 完成主系统 staging 接口验收。
- [ ] 完成告警幂等、重试和冷却验收。

### E. 控制侧安全

- [ ] 不把相机接入和 Go2 控制一起放开。
- [ ] `GO2_LOW_LEVEL_CONTROL_ENABLED=false`。
- [ ] `GO2_CONTROL_ENABLED=false`，除非完成专门批准。
- [ ] Robot Assist 先保持 Mock。
- [ ] 真实控制必须有单独的只读、审批、急停和现场安全门禁。

---

## 14. 推荐的下一阶段实现顺序

### 阶段 1：机器狗视频桥接

目标：让 Go2 相机输出一个稳定、可观测、可解码的 RTSP。

交付：

```text
RTSP 地址
桥接器启动命令
桥接器健康检查
帧率和延迟
断线重连说明
```

### 阶段 2：目标 RTSP 稳定性

目标：不改模型，先证明视频本身可用。

交付：

```text
10/30 分钟稳定性记录
frame_seq 增长曲线
frame_age_ms 统计
断线重连记录
源代次变化记录
```

### 阶段 3：目标相机数据标定

目标：替换当前 OOF 工程基线为目标域冻结参数。

交付：

```text
target_data_inventory.json
calibration_report.json
calibration_freeze.json
hard_negative_report.json
```

### 阶段 4：独立验收

目标：在不重新调参的前提下评估目标域效果。

交付：

```text
acceptance_report.json
final_p3_gate_report.json
```

### 阶段 5：dry-run 和主系统 staging

目标：验证事件格式、幂等、重试和前端展示，但不触发真实生产动作。

### 阶段 6：真实告警和机器人任务

只有视觉、主系统、审批、设备安全和现场急停全部通过后，才讨论真实 Robot Assist。

---

## 15. 工程师接手时优先阅读的文件

按推荐顺序：

```text
docs/go2_camera_vision_handoff_2026-08-21.md
docs/post_fall_v2_current_state.md
docs/post_fall_v2_architecture_audit.md
configs/post_fall_v2_candidate.env
configs/safe_demo.env
app/main.py
app/services/stream_service.py
app/camera/source_manager.py
app/camera/capture_worker.py
app/post_fall_v2/post_fall_runtime_service.py
app/post_fall_v2/fall_binary_classifier_service.py
app/post_fall_v2/binary_decision_aggregator.py
app/post_fall_v2/keyframe_collection_session.py
app/post_fall_v2/qwen_fall_analyzer.py
app/api/rest_api.py
app/api/status_api.py
app/api/integration_api.py
app/api/ws_api.py
tests/test_post_fall_v2_runtime_service.py
tests/test_post_fall_v2_runtime_keyframe_collection.py
tests/test_post_fall_v2_stream_mode_isolation.py
tests/test_post_fall_v2_binary_decision_aggregator.py
```

---

## 16. 最终交接判断

当前项目可以交接为：

```text
“具备 RTSP/文件/Mock 画面输入能力的 Post-Fall V2 视觉服务，
已完成本地运行链路、通用回放和代码测试，
等待机器狗目标相机视频桥接、目标域标定、独立验收和现场 RTSP 稳定性验证。”
```

当前不能交接为：

```text
“已经完成 Go2 原生相机 SDK 接入并具备现场生产告警能力。”
```

现场交接的第一个成功标准不是“模型输出了一个概率”，而是：

```text
机器狗画面稳定进入 FrameBuffer，
frame_seq 持续增长，
服务能拿到真实最新帧，
PFV2 使用正确的源和参数处理画面，
结果状态可被 HTTP/WebSocket 观察，
断流时系统不会伪装成安全状态。
```
