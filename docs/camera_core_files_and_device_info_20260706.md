# 跌倒检测系统摄像头核心文件与设备信息整理

整理时间：2026-07-06  
主工程目录：`D:\Program\vision_service`  
摄像头调试工具目录：`D:\Program\camear_new`

> 安全说明：本文档只记录摄像头型号、协议、端口、运行链路和核心文件职责，不记录真实摄像头密码、告警 token 或完整明文 RTSP 地址。涉及密码的位置统一用 `***` 表示。

---

## 1. 结论摘要

当前跌倒检测系统真正运行摄像头与算法的主工程是：

```text
D:\Program\vision_service
```

摄像头单独探测、预览、拉流验证的辅助工具目录是：

```text
D:\Program\camear_new
```

摄像头设备型号已在本地交接文档中确认：

```text
品牌：xstrive / 迅思维科技
型号：XSWCAM-WB4MP
类型：4MP 网络摄像机
```

系统整体摄像头链路可以概括为：

```text
摄像头 RTSP / 本地视频 / mock 源
-> CameraSourceManager
-> CaptureWorker 或 SubprocessCaptureWorker
-> FrameBuffer
-> DetectionService
-> YOLO 人体检测
-> YOLO 跌倒提示检测
-> Tracking / Pose / Temporal
-> ResultPublisherService
-> WebSocket / WebRTC / 前端展示
-> FallEventReporterService
-> 主系统跌倒告警接口
```

---

## 2. 摄像头型号与硬件信息

### 2.1 已确认设备身份

根据 `D:\Program\camear_new\CAMERA_FULL_HANDOFF_2026-05-05.md` 和 `D:\Program\camear_new\CAMERA_BEGINNER_GUIDE.md`，摄像头信息如下：

| 项目 | 信息 |
| --- | --- |
| 品牌 | `xstrive / 迅思维科技` |
| 型号 | `XSWCAM-WB4MP` |
| 类型 | 4MP 网络摄像机 |
| 网络方式 | 支持 Wi-Fi / 有线 |
| 有线接口 | RJ45 10M/100M |
| 供电 | DC12V 2A |
| 最大分辨率 | 2560x1440 |
| 最大帧率 | 25 FPS |
| 视频编码 | H.264 / H.265 |
| 常用协议 | ONVIF / GB28181 / TCP/IP / DHCP / DNS / NTP / RTSP / RTMP |
| App 线索 | Eye4 |
| 设备类别 | 网络摄像机，不是 4G 摄像机、电池摄像机或可视门铃 |

### 2.2 设备唯一标识与远程后台

本地交接文档记录的设备 SN / UID：

```text
841d5d8b0ac6604c1fd0945eed876459
```

远程管理地址线索：

```text
http://841d5d8b0ac6604c1fd0945eed876459.cloud.xstrive.com:9502/
http://841d5d8b0ac6604c1fd0945eed876459.cloud.xstrive.com:9502/cloud
```

说明：

- 该 UID 是设备唯一标识，不是密码。
- 文档记录该远程后台页面标题为 `配置后台`。
- 文档记录域名解析到 `45.120.100.178`，`9502/tcp` 可达。

---

## 3. 摄像头协议、端口与 RTSP 地址

### 3.1 标准 RTSP 模板

`camear_new` 摄像头指南中给出的常用 RTSP 模板：

```text
rtsp://admin:***@摄像头IP:10554/tcp/av0_0
rtsp://admin:***@摄像头IP:10554/tcp/av0_1
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `admin` | 常见默认账号 |
| `***` | 厂家 App 中设置或开启的明文密码 |
| `10554` | 文档中记录的常用 RTSP 端口 |
| `tcp` | 建议优先使用 TCP，稳定性更好 |
| `av0_0` | 主码流，画质更清晰，适合算法分析 |
| `av0_1` | 子码流，码率更低，适合预览或低负载场景 |

### 3.2 ONVIF 模板

```text
http://摄像头IP:10080/onvif/device_service
```

账号与密码通常与 RTSP 使用同一套设备认证信息：

```text
账号：admin
密码：***
```

### 3.3 当前本机配置中出现的实际地址

在 `D:\Program\vision_service\.env` 中，当前主工程配置为：

```text
DEFAULT_CAMERA_ID=camera_01
DEFAULT_RTSP_URL=rtsp://admin:***@192.168.8.250:10554/tcp/av0_0
MOCK_CAMERA_ENABLED=false
CAPTURE_BACKEND=subprocess_opencv
```

这说明 `vision_service` 当前预期直接接入真实 RTSP 摄像头，而不是 mock 摄像头。

在 `D:\Program\camear_new\camera_live_config.json` 和 `camera_live_config.runtime.json` 中，调试工具配置里出现：

```text
host=192.168.8.248
rtsp_port=554
transport=tcp
stream=av0_0 或 av0_1
viewer=http://127.0.0.1:8090/viewer
```

注意：这里和 `vision_service\.env` 存在差异：

| 来源 | 摄像头 IP | RTSP 端口 | 码流 |
| --- | --- | --- | --- |
| `vision_service\.env` | `192.168.8.250` | `10554` | `/tcp/av0_0` |
| `camear_new\camera_live_config.json` | `192.168.8.248` | `554` | `av0_0` |
| `camear_new\camera_live_config.runtime.json` | `192.168.8.248` | `554` | `av0_1` |

因此，后续联调时需要先确认真实摄像头当前 IP 和端口，不能直接假设所有文件指向同一台设备。

---

## 4. 跌倒检测主工程核心文件

### 4.1 系统入口与服务装配

| 文件 | 作用 |
| --- | --- |
| `D:\Program\vision_service\app\main.py` | FastAPI 主入口；创建摄像头源管理、检测、跟踪、姿态、时序、结果发布和告警上报服务。 |
| `D:\Program\vision_service\app\core\config.py` | 读取 `.env` 和环境变量；管理 RTSP、检测模型、姿态模型、时序模型、告警接口等配置。 |
| `D:\Program\vision_service\app\core\runtime.py` | 保存运行时服务对象，供 API 层调用。 |

`app/main.py` 是主工程最关键的启动文件。它会创建：

- `CameraSourceManager`
- `DetectionService`
- `TrackingWorkerService`
- `PoseWorkerService`
- `TemporalService`
- `FallFusionService`
- `ResultPublisherService`
- `FallEventReporterService`
- `StreamService`
- `StatusService`

并且在存在默认 RTSP 或启用 mock 摄像头时自动启动默认流。

### 4.2 摄像头采集与缓存

| 文件 | 作用 |
| --- | --- |
| `D:\Program\vision_service\app\camera\source_manager.py` | 摄像头运行实例管理；为每个 camera_id 创建 FrameBuffer 和采集 worker。 |
| `D:\Program\vision_service\app\camera\capture_worker.py` | 主采集 worker；负责 OpenCV 拉取 RTSP、本地视频或 mock 源，并写入帧缓存。 |
| `D:\Program\vision_service\app\camera\subprocess_capture_worker.py` | 子进程采集 worker；用于降低 OpenCV RTSP 阻塞对主进程的影响。 |
| `D:\Program\vision_service\app\camera\capture_process.py` | 子进程采集入口，由 `subprocess_capture_worker.py` 启动。 |
| `D:\Program\vision_service\app\camera\capture_process_protocol.py` | 子进程采集时的帧数据传输协议。 |
| `D:\Program\vision_service\app\camera\capture_watchdog.py` | 子进程采集监控和清理辅助逻辑。 |
| `D:\Program\vision_service\app\camera\frame_buffer.py` | 最新帧缓存；检测、WebRTC、截图接口都会从这里拿图像。 |
| `D:\Program\vision_service\app\camera\source_models.py` | 摄像头源配置模型，包含 camera_id、source_url 和源类型判断。 |

摄像头采集层的核心关系：

```text
StreamService.start()
-> CameraSourceManager.start_source()
-> FrameBuffer(camera_id)
-> CaptureWorker / SubprocessCaptureWorker
-> worker.start()
-> 持续读取视频帧
-> FrameBuffer.update()
```

### 4.3 摄像头启动与停止接口

| 文件 | 作用 |
| --- | --- |
| `D:\Program\vision_service\app\services\stream_service.py` | 摄像头流启动/停止的核心调度服务。 |
| `D:\Program\vision_service\app\api\rest_api.py` | 提供 `/stream/start`、`/stream/stop`、`/stream/latest-frame.jpg` 等接口。 |
| `D:\Program\vision_service\app\api\webrtc_api.py` | WebRTC 视频预览接口。 |
| `D:\Program\vision_service\app\api\ws_api.py` | WebSocket 检测结果推送接口。 |
| `D:\Program\vision_service\app\api\status_api.py` | `/status` 状态接口。 |
| `D:\Program\vision_service\app\services\status_service.py` | 汇总摄像头、检测、跟踪、姿态、时序、告警等运行状态。 |

`stream_service.py` 的职责最关键：

1. 选择唯一权威视频源，避免重复拉同一个 RTSP。
2. 如果同一个 camera_id 已经运行，会判断是否需要重启。
3. 启动摄像头采集。
4. 启动检测 worker、跟踪 worker、姿态 worker、结果发布 worker。
5. 停止时按相反顺序关闭服务。

### 4.4 检测、跟踪、姿态与时序判断

| 文件 | 作用 |
| --- | --- |
| `D:\Program\vision_service\app\services\detection_service.py` | 检测服务；读取 FrameBuffer，运行人体检测与跌倒提示检测。 |
| `D:\Program\vision_service\app\detection\object_detector.py` | YOLO 人体检测封装。 |
| `D:\Program\vision_service\app\detection\yolo_fall_detector.py` | YOLO 跌倒提示检测封装，识别 fall / falling / fallen 等提示类别。 |
| `D:\Program\vision_service\app\detection\realtime_result_store.py` | 实时检测、跟踪、姿态、结果快照缓存。 |
| `D:\Program\vision_service\app\services\tracking_service.py` | 跟踪服务，管理 track_id 和目标状态。 |
| `D:\Program\vision_service\app\services\tracking_worker_service.py` | 后台跟踪 worker；会把跌倒提示框与人体框合并/提升为候选。 |
| `D:\Program\vision_service\app\tracking\bytetrack_tracker.py` | ByteTrack 跟踪实现。 |
| `D:\Program\vision_service\app\services\pose_service.py` | 姿态估计服务入口。 |
| `D:\Program\vision_service\app\services\pose_worker_service.py` | 姿态估计后台 worker。 |
| `D:\Program\vision_service\app\pose\yolo11_legacy_pose_estimator.py` | 当前配置中使用的 YOLO11 legacy 姿态提供器之一。 |
| `D:\Program\vision_service\app\services\temporal_service.py` | 时序跌倒判断服务，整合连续帧特征、ONNX LSTM、状态机。 |
| `D:\Program\vision_service\app\temporal\fall_state_machine.py` | 跌倒状态机，决定 falling、fallen_candidate、fallen_confirmed 等状态。 |
| `D:\Program\vision_service\app\temporal\onnx_sequence_model.py` | ONNX LSTM 时序模型推理。 |
| `D:\Program\vision_service\app\fall\feature_builder.py` | 生成跌倒特征，包括运动、姿态、跌倒提示框等。 |
| `D:\Program\vision_service\app\fall\fusion.py` | 跌倒融合与误报抑制，最终决定是否确认跌倒。 |

当前 `.env` 中与算法有关的关键配置：

```text
YOLO_MODEL_PATH=yolov8n.pt
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt
ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=onnx_lstm
```

### 4.5 结果发布与告警上报

| 文件 | 作用 |
| --- | --- |
| `D:\Program\vision_service\app\services\result_publisher_service.py` | 把检测、跟踪、姿态、时序、跌倒融合结果整理成实时结果，并通过 WebSocket/缓存发布。 |
| `D:\Program\vision_service\app\services\fall_event_reporter_service.py` | 生成跌倒事件 payload，管理 incident_id、冷却时间、截图，并向主系统上报告警。 |
| `D:\Program\vision_service\app\api\integration_api.py` | 给主系统或前端轮询使用的集成接口，如最新结果、告警轮询等。 |
| `D:\Program\vision_service\app\api\fall_events_api.py` | 跌倒事件截图/事件相关接口。 |
| `D:\Program\vision_service\app\api\alerting_api.py` | 告警模拟、手动触发和联调接口。 |

当前 `.env` 中主系统地址为：

```text
MAIN_SYSTEM_BASE_URL=http://192.168.8.248:8000/api/v1
```

注意：`192.168.8.248` 在 `camear_new` 中也作为摄像头调试配置 IP 出现过，因此需要确认它到底是当前主系统地址、摄像头地址，还是历史配置遗留。避免把告警 POST 到摄像头 IP，或把摄像头拉流地址写成主系统 IP。

---

## 5. 摄像头调试工具目录 `camear_new`

`D:\Program\camear_new` 不是跌倒检测主工程，而是摄像头接入、探测和本地预览工具包。它适合在正式接入 `vision_service` 前验证摄像头是否能拉流。

### 5.1 关键文件

| 文件 | 作用 |
| --- | --- |
| `D:\Program\camear_new\CAMERA_FULL_HANDOFF_2026-05-05.md` | 摄像头完整交接文档，包含型号、协议、说明书线索、远程后台和工具说明。 |
| `D:\Program\camear_new\CAMERA_BEGINNER_GUIDE.md` | 摄像头接线、供电、RTSP、ONVIF 和新手调试指南。 |
| `D:\Program\camear_new\camera_runtime_main.py` | 摄像头本地运行时主入口。 |
| `D:\Program\camear_new\camera_live_server.py` | 简单入口，调用 `camera_runtime_main.main()`。 |
| `D:\Program\camear_new\camera_runtime\config.py` | 读取摄像头 IP、账号、密码、端口、码流、预览服务配置。 |
| `D:\Program\camear_new\camera_runtime\service.py` | 使用 OpenCV 打开 RTSP，读取帧并编码为 JPEG。 |
| `D:\Program\camear_new\camera_runtime\web.py` | 提供本地预览页面、健康接口、截图接口和 MJPEG 流。 |
| `D:\Program\camear_new\camera_probe_xstrive.py` | xstrive / XSWCAM 摄像头 RTSP 探测脚本。 |
| `D:\Program\camear_new\camera_onvif_probe.py` | ONVIF 探测脚本。 |
| `D:\Program\camear_new\camera_runtime_start.ps1` | 后台启动本地摄像头预览服务。 |
| `D:\Program\camear_new\camera_runtime_stop.ps1` | 停止本地摄像头预览服务。 |
| `D:\Program\camear_new\camera_runtime_status.ps1` | 查看本地摄像头预览服务状态。 |
| `D:\Program\camear_new\run_camera_live_server.ps1` | 前台启动本地摄像头预览服务。 |

### 5.2 本地预览服务接口

`camear_new` 的本地预览服务默认地址：

```text
http://127.0.0.1:8090/viewer
```

常用接口：

```text
GET  /api/v1/camera/health
GET  /api/v1/camera/snapshot
GET  /api/v1/camera/stream.mjpg
POST /api/v1/camera/stream/switch?stream=av0_0
POST /api/v1/camera/stream/switch?stream=av0_1
POST /api/v1/camera/stop
```

---

## 6. 推荐排查顺序

### 6.1 先确认硬件连通

1. 摄像头接 DC12V 2A 电源，或使用符合要求的 PoE 供电设备。
2. 摄像头接路由器 LAN 口，不建议新手直接接电脑网口。
3. 电脑和摄像头在同一局域网。
4. 用厂家工具或路由器后台确认摄像头当前 IP。
5. 确认 RTSP 端口到底是 `10554` 还是 `554`。

### 6.2 再确认 RTSP 可用

优先用 `camear_new` 或 `vision_service` 脚本探测：

```powershell
cd D:\Program\camear_new
python .\camera_probe_xstrive.py --host 摄像头IP --password *** --rtsp-port 10554 --stream sub --transport tcp
```

如果使用完整 RTSP：

```powershell
python .\camera_probe_xstrive.py --source "rtsp://admin:***@摄像头IP:10554/tcp/av0_1"
```

如果 10554 不通，再测试 554：

```powershell
python .\camera_probe_xstrive.py --host 摄像头IP --password *** --rtsp-port 554 --stream sub --transport tcp
```

### 6.3 再启动 Vision Service

主工程推荐入口：

```powershell
cd D:\Program\vision_service
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

或使用当前摄像头启动脚本：

```powershell
cd D:\Program\vision_service
python scripts\start_current_camera.py --host 摄像头IP --rtsp-port 10554 --no-wait
```

启动后检查：

```text
http://127.0.0.1:8000/status
http://127.0.0.1:8000/demo
http://127.0.0.1:8000/integration/results/camera_01/latest
```

---

## 7. 当前需要特别注意的问题

### 7.1 IP 与端口配置存在多处历史值

当前本地文件中至少出现过这些地址：

| 地址 | 出现位置 | 可能含义 |
| --- | --- | --- |
| `192.168.8.250:10554` | `vision_service\.env` | 当前主工程摄像头 RTSP 配置 |
| `192.168.8.248:554` | `camear_new\camera_live_config*.json` | 摄像头调试工具历史/当前配置 |
| `192.168.8.248:8000` | `vision_service\.env` | 主系统 API 地址配置 |
| `192.168.8.254:8000` | 多份旧文档 | 历史主系统或接收端地址 |

这些值不能混用。实际联调前必须先确认：

1. 摄像头当前 IP 是哪个。
2. 摄像头 RTSP 端口是 `10554` 还是 `554`。
3. 主系统 API 地址是哪个。
4. Vision Service 自己运行在哪个 IP 和端口。

### 7.2 不要把密码写进文档或提交到仓库

以下文件可能包含明文或历史密码配置：

```text
D:\Program\vision_service\.env
D:\Program\camear_new\camera_live_config.json
D:\Program\camear_new\camera_live_config.runtime.json
```

建议：

- `.env` 不提交。
- 日志、截图、文档中不要出现完整 RTSP URL。
- 对外沟通统一使用 `rtsp://admin:***@IP:PORT/tcp/av0_0` 格式。

### 7.3 Capture 后端建议

当前 `vision_service\.env` 使用：

```text
CAPTURE_BACKEND=subprocess_opencv
```

这是比普通 `opencv` 更稳的方案，因为 RTSP 读取阻塞时可以通过子进程隔离，减少主服务卡死风险。

---

## 8. 一句话交接

这套跌倒检测系统的摄像头主链路在 `D:\Program\vision_service`，核心是 `StreamService -> CameraSourceManager -> CaptureWorker/SubprocessCaptureWorker -> FrameBuffer -> Detection/Tracking/Pose/Temporal -> ResultPublisher/FallEventReporter`。摄像头设备本身是 `xstrive / 迅思维科技 XSWCAM-WB4MP` 4MP 网络摄像机，支持 RTSP/ONVIF，常用 RTSP 模板为 `rtsp://admin:***@摄像头IP:10554/tcp/av0_0` 和 `rtsp://admin:***@摄像头IP:10554/tcp/av0_1`。

