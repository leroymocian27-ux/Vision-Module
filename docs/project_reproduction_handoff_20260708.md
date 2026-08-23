# Vision Service 项目复现交付说明

生成日期：2026-07-08

当前项目目录：`D:\Program\vision_service`

参考问题文档：`C:\Users\YANG\Downloads\full_chain_recovery_status_20260708.md`

## 1. 先说结论

如果要让对方完整复现当前 Vision Service 跌倒检测项目，不能只给 GitHub 代码。当前仓库里的大模型、`.env`、数据目录、日志目录都被 `.gitignore` 排除了，其中模型文件是运行必需资产。

建议给对方两个东西：

1. 项目代码包：包含 `app`、`scripts`、`frontend_demo`、`requirements.txt`、`.env.example`、关键文档等。
2. 运行资产包：包含跌倒检测主链路所需模型文件、LSTM 配套 JSON、必要的接口说明文档。

不要直接给当前 `.env`，因为里面通常包含摄像头账号密码、主系统 token、现场 IP 等敏感配置。应给 `.env.example` 或单独的 `.env.local.template`，让对方按现场信息填写。

## 2. 必须给他的文件

### 2.1 项目代码

必须包含：

```text
app/
frontend_demo/
scripts/
tests/
requirements.txt
requirements-identity.txt
README.md
.env.example
```

建议同时包含：

```text
docs/project_reproduction_handoff_20260708.md
docs/runtime_missing_file_search_report_20260708.md
docs/fall_decision_algorithm_design_20260708.md
docs/main_system_fall_event_push_interface_20260707.md
docs/vision_service_json_report_format_20260707.json
docs/vision_service_core_system_overview_20260706.md
docs/vision_service_visual_architecture_20260706.md
```

### 2.2 主链路必需模型

这些文件是复现“摄像头 -> 人体检测 -> 跌倒提示 -> 跟踪 -> 姿态 -> LSTM 时序 -> 告警结果”的最低模型资产。

| 用途 | 文件路径 | 大小 | SHA256 |
|---|---|---:|---|
| 人体检测 | `yolov8n.pt` | 6,549,796 B | `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36` |
| 当前 fall hint 候选 | `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt` | 5,455,706 B | `9af8f3990296106b3cbcbae2fd634f0815e116caed59f6ec8dfc58b099206521` |
| fall hint v2 备用/稳定版 | `models/yolo_fall_hint_v2_plus_b012_best.pt` | 5,461,914 B | `4bafc88b2ec068921776c8d4d0e4efd020dfab29afd313044ecfb07098ca67a8` |
| 当前姿态基线 | `yolo11n-pose.pt` | 6,255,593 B | `869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0` |
| 项目训练姿态模型 | `models/pose_yolo_batch001_003_yolo11s_best.pt` | 20,178,504 B | `b03c350774dbb83e3c2d0bf6f1f72700044e3fd0f1a14d17c61e7ab564c0c5fb` |
| 时序 LSTM | `models/fall_lstm_v5.onnx` | 85,630 B | `01af710c6f8996ea0b894ef063956121988f32df6df10208f21eda4869fb0a8c` |

### 2.3 LSTM 和模型配套文件

这些不是大模型，但建议一并给出，便于确认模型版本、阈值和特征 schema。

```text
models/fall_lstm_v5_features.json
models/fall_lstm_v5_threshold_calibration.json
models/fall_lstm_v5_train_config.json
models/fall_lstm_v5_metrics.json
models/yolo_fall_hint_v2_plus_b012_metrics.json
models/pose_yolo_batch001_003_yolo11s_metrics.json
models/pose_yolo_batch001_003_yolo11s_link_match_metrics.json
```

### 2.4 可选模型

如果对方只复现当前主链路，下面这些不是必须。

| 文件 | 是否必须 | 用途 |
|---|---:|---|
| `models/person_yolo_batch001_yolov8n_best.pt` | 否 | 自训练 person 检测候选，当前可用于人体检测效果对比 |
| `models/rtmpose/rtmpose_l_pose_adaptation_384x288.py` | 否 | MMPose/RTMPose 适配配置 |
| `models/rtmpose/rtmpose-l-pose-adapted-best.pth` | 否 | MMPose/RTMPose 适配权重 |
| `models/external/rtmpose-m-body7-256x192/rtmpose-m-body7-256x192.zip` | 否 | RTMPose-M ONNX 候选来源 |

当前仍缺的可选文件：

```text
models/rtmpose/rtmpose-x-body7-384x288.onnx
models/rtmpose/rtmpose-l_8xb256-420e_coco-384x288.py
models/rtmpose/rtmpose-l_simcc-coco_pt-aic-coco_420e-384x288-9ec0a4e5_20230127.pth
```

这些缺失不会影响当前 `POSE_PROVIDER=yolo11_legacy` 主链路。

## 3. 不建议给他的文件

除非有明确需要，不建议交付：

```text
.env
logs/
tmp/
backups/
artifacts/
runs/
data/identities/
datasets/
video/
.venv/
.pytest_cache/
```

原因：

1. `.env` 可能包含摄像头密码和主系统 token。
2. `logs`、`tmp`、`runs`、`video` 通常是运行产物，体积大且不影响复现。
3. `data/identities` 可能包含人员身份、人脸图片或隐私数据。
4. `datasets` 是训练数据，不是运行主链路的必要文件。

## 4. 对方需要自己准备的信息

对方复现真实现场时，还需要填写这些外部信息：

```text
摄像头 IP、端口、RTSP 路径
摄像头账号、密码
主系统 IP、端口、API 前缀
主系统跌倒事件接收路径
主系统鉴权 token，如有
Vision Service 在局域网中的可访问地址
是否启用 GPU/CUDA
是否需要身份识别
```

当前现场常见形态是：

```text
摄像头：192.168.8.250
主系统：192.168.8.248
Vision Service：本机 8000 端口
```

但这些地址不应写死到交付包里，应由对方按实际网络填写。

## 5. 建议给他的 `.env` 模板

让对方复制 `.env.example` 为 `.env`，然后至少确认以下字段：

```env
APP_NAME=vision-service
DEFAULT_CAMERA_ID=camera_01

# 真实摄像头
DEFAULT_RTSP_URL=rtsp://<camera_user>:<camera_password>@<camera_ip>:10554/tcp/av0_0
MOCK_CAMERA_ENABLED=false

# 人体检测
DETECTION_ENABLED=true
YOLO_MODEL_PATH=yolov8n.pt
YOLO_CONFIDENCE=0.35
YOLO_IMGSZ=640

# 跌倒提示检测
FALL_DETECTOR_ENABLED=true
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt
YOLO_FALL_CONFIDENCE=0.25
YOLO_FALL_IMGSZ=512

# 跟踪
ENABLE_TRACKING=true

# 姿态
ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
YOLO11_POSE_MODEL_PATH=yolo11n-pose.pt
YOLO11_POSE_IMGSZ=640
YOLO11_POSE_CONF=0.12
POSE_WORKER_FPS=1

# 时序 LSTM
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v5_features.json
TEMPORAL_MODEL_WINDOW_SIZE=32
TEMPORAL_MODEL_INPUT_DIM=15
TEMPORAL_WARMUP_MIN_SIZE=16
TEMPORAL_FALLBACK_TO_MOCK=false
TEMPORAL_ONNX_PROVIDERS=CPUExecutionProvider

# 主系统联动，首次复现建议先 dry-run
MAIN_SYSTEM_ALERT_ENABLED=false
MAIN_SYSTEM_REPORT_DRY_RUN=true
MAIN_SYSTEM_BASE_URL=http://<main_system_ip>:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN=
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
VISION_SERVICE_PUBLIC_BASE_URL=http://<vision_service_lan_ip>:8000
FALL_EVENT_SNAPSHOT_DIR=logs/fall_events/snapshots
```

确认主系统接口、token 和弹窗逻辑没问题后，再改为：

```env
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_REPORT_DRY_RUN=false
```

## 6. 环境安装步骤

推荐 Python 3.10。Windows 上建议使用 Conda 或固定虚拟环境，避免系统 Python 混乱。

```powershell
cd D:\Program\vision_service

py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install onnxruntime
```

如果要使用 GPU：

```powershell
.\.venv\Scripts\python.exe -m pip install onnxruntime-gpu
```

如果要启用身份识别：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-identity.txt
```

如果要启用 MMPose/RTMPose：

```powershell
.\.venv\Scripts\python.exe -m pip install openmim
.\.venv\Scripts\python.exe -m mim install mmengine
.\.venv\Scripts\python.exe -m mim install "mmcv>=2.0.0,<2.2.0"
.\.venv\Scripts\python.exe -m mim install "mmdet>=3.0.0,<3.4.0"
.\.venv\Scripts\python.exe -m pip install mmpose
```

主链路暂时不建议先启用 RTMPose，先用 `yolo11_legacy` 跑通。

## 7. 启动方式

```powershell
cd D:\Program\vision_service
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器访问：

```text
http://127.0.0.1:8000/demo
```

状态接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/status
Invoke-RestMethod http://127.0.0.1:8000/integration/results/camera_01/latest
```

如果 `.env` 没有写固定 RTSP，也可以启动后手动接入：

```powershell
$body = @{
  camera_id = "camera_01"
  rtsp_url = "rtsp://<camera_user>:<camera_password>@<camera_ip>:10554/tcp/av0_0"
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8000/stream/start `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

## 8. 复现验收标准

### 8.1 服务和摄像头

`GET /status` 里应看到：

```text
service_status=running
cameras[0].connected=true
stream_state=connected
frame_age_ms 小于 3000
capture_fps 大于 0
```

### 8.2 人体检测和跟踪

摄像头画面中有人时，应看到：

```text
detection.enabled=true
detection.loaded=true
latest_raw_person_count > 0
tracking.tracker_running=true
tracked_objects_count > 0
```

如果画面有人但 `latest_raw_person_count=0`，优先检查摄像头角度、光照、人体是否完整入镜，然后再调低：

```env
YOLO_CONFIDENCE=0.25
YOLO_IMGSZ=640
```

### 8.3 姿态和时序

有人并形成 track 后，应看到：

```text
pose.pose_enabled=true
pose.pose_provider=yolo11_legacy
pose.inference_attempt_count 增长
pose.inference_success_count 增长
temporal.enabled=true
temporal.model_loaded=true
temporal.fallback_active=false
```

### 8.4 跌倒告警

做跌倒测试时，应观察：

```text
fall_decision 存在
fall_detected 在确认跌倒时为 true
alarm_preview.confirmed 在确认跌倒时为 true
fall_event_reporter.enabled 在打开主系统推送后为 true
fall_event_reporter.last_post_status 为 2xx
```

主系统接口文件见：

```text
docs/main_system_fall_event_push_interface_20260707.md
```

JSON 回报格式见：

```text
docs/vision_service_json_report_format_20260707.json
```

## 9. 当前剩余问题怎么理解

参考问题文档中提到“当前画面没有检测到人”，这不等于模型缺失。判断逻辑是：

```text
模型加载成功 + detection_fps 正常
但 latest_raw_person_count=0
```

这通常表示当前画面没有可识别人体，或者角度、遮挡、光照、距离导致 person detector 没检出。只有当画面中明确有人且持续 `latest_raw_person_count=0`，才需要继续调阈值或切换自训练 person 模型。

主系统真实告警是否开启，需要以现场 `.env` 为准。复现交付时建议默认关闭真实 POST，用 dry-run 先验证 payload，避免误触发主系统弹窗。

身份识别不是当前跌倒检测主链路的必要条件。除非对方明确要做人脸身份绑定，否则不建议第一轮复现时开启。

RTMPose/MMPose 是姿态候选路线，不是当前主链路依赖。当前主链路建议保持：

```env
POSE_PROVIDER=yolo11_legacy
```

## 10. 推荐交付包结构

建议最终交付时整理为：

```text
vision_service_delivery/
  code/
    app/
    frontend_demo/
    scripts/
    tests/
    docs/
    README.md
    requirements.txt
    requirements-identity.txt
    .env.example
  runtime_assets/
    yolov8n.pt
    yolo11n-pose.pt
    models/
      yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt
      yolo_fall_hint_v2_plus_b012_best.pt
      pose_yolo_batch001_003_yolo11s_best.pt
      fall_lstm_v5.onnx
      fall_lstm_v5_features.json
      fall_lstm_v5_threshold_calibration.json
      fall_lstm_v5_train_config.json
      fall_lstm_v5_metrics.json
      yolo_fall_hint_v2_plus_b012_metrics.json
      pose_yolo_batch001_003_yolo11s_metrics.json
      pose_yolo_batch001_003_yolo11s_link_match_metrics.json
  env/
    .env.local.template
  docs_for_handoff/
    project_reproduction_handoff_20260708.md
    main_system_fall_event_push_interface_20260707.md
    vision_service_json_report_format_20260707.json
```

对方拿到后，把 `runtime_assets` 中的文件按相同相对路径放回 `code/` 目录，再按第 5 到第 8 节配置、启动和验收。
