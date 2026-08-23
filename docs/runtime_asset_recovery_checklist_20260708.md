# 运行资产补齐与完整功能恢复清单

生成日期：2026-07-08  
工作目录：`D:\camera`

本文用于回答一个实际问题：如果要让当前 Vision Service 恢复“完整功能”，还需要补齐哪些文件、放到哪里、如何判断文件是否正确、补齐后怎样配置。

## 1. 当前结论

当前项目代码和配置模板是完整的，但本地运行资产不完整。服务现在可以启动，mock 视频、状态接口和结果接口可用；但是完整 AI 链路不可用。

主要原因有两个：

1. 关键模型权重文件不是模型本体，而是 Git LFS 指针文件。  
   这些文件通常只有 `130` 到 `134` 字节，内容以 `version https://git-lfs.github.com/spec/v1` 开头。它们只是“下载索引”，不能被 Ultralytics、ONNX Runtime 或 MMPose 当作模型加载。

2. 当前 `.env` 把 AI 功能开关关闭了。  
   例如 `DETECTION_ENABLED=false`、`FALL_DETECTOR_ENABLED=false`、`ENABLE_POSE=false`、`ENABLE_TEMPORAL=false`。这是一个安全状态：服务能启动，但不会做真实识别。

所以当前可用范围是：

```text
可用：
- FastAPI 服务
- /status
- /integration/results/camera_01/latest
- mock://colorbars 模拟视频
- 前端 demo 基础画面

不可用或未启用：
- 人体检测
- 跌倒提示检测
- ByteTrack 有效跟踪
- 姿态估计
- LSTM 时序跌倒判断
- 主系统真实告警推送
```

## 2. 必须补齐的核心文件

要恢复完整跌倒识别主链路，最少需要补齐以下 4 个模型文件。

| 优先级 | 文件路径 | 用途 | 当前本地大小 | 期望大小 | 说明 |
|---|---|---|---:|---:|---|
| P0 | `yolov8n.pt` | 人体检测入口 | 132 B | 6,549,796 B | 默认 person detector 使用 |
| P0 | `models/yolo_fall_hint_v2_plus_b012_best.pt` | 跌倒提示检测 | 132 B | 5,461,914 B | 文档中稳定主链路常用版本 |
| P0 | `models/pose_yolo_batch001_003_yolo11s_best.pt` | 项目姿态模型 | 133 B | 20,178,504 B | `POSE_PROVIDER=yolo11_legacy` 推荐项目模型 |
| P0 | `models/fall_lstm_v5.onnx` | 时序跌倒 LSTM | 130 B | 85,630 B | `TEMPORAL_MODEL_PROVIDER=onnx_lstm` 使用 |

如果采用 `.env.example` 的默认 fall hint 候选，还需要补齐：

| 优先级 | 文件路径 | 用途 | 当前本地大小 | 期望大小 |
|---|---|---|---:|---:|
| P0 | `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt` | 跌倒提示检测 v3 候选 | 132 B | 5,455,706 B |

如果姿态先使用通用基线模型，而不是项目训练模型，还需要补齐：

| 优先级 | 文件路径 | 用途 | 当前本地大小 | 期望大小 |
|---|---|---|---:|---:|
| P1 | `yolo11n-pose.pt` | YOLO11 pose 基线 | 132 B | 6,255,593 B |
| P1 | `yolov8n-pose.pt` | 旧 YOLO pose provider 候选 | 132 B | 未在当前检查中展开 |

## 3. 可选但建议补齐的模型文件

这些文件不是恢复主链路的最低要求，但用于候选对比、降级方案、后续调优或身份识别。

| 优先级 | 文件路径 | 用途 | 当前状态 |
|---|---|---|---|
| P1 | `models/person_yolo_batch001_yolov8n_best.pt` | 自训练 person 检测候选 | LFS 指针，期望约 6,250,538 B |
| P1 | `models/person_yolo_batch001_003_yolov8n_best.pt` | 自训练 person 候选 | LFS 指针 |
| P1 | `models/person_yolo_batch001_004_yolov8n_best.pt` | 自训练 person 候选 | LFS 指针 |
| P1 | `models/person_yolo_batch001_005_yolov8n_best.pt` | 自训练 person 候选 | LFS 指针 |
| P1 | `models/person_yolo_batch001_008_yolov8n_best.pt` | 自训练 person 候选 | LFS 指针 |
| P1 | `models/fall_lstm_v2.onnx` 到 `models/fall_lstm_v4.onnx` | 时序模型历史版本 | LFS 指针 |
| P1 | `models/fall_lstm_v6_pose_dev_smoke.onnx` | pose 版 LSTM dev smoke | LFS 指针 |
| P2 | `models/yolo_fall_detector_v4_best.pt` 到 `models/yolo_fall_detector_v6_best.pt` | 历史 fall detector | LFS 指针 |
| P2 | `models/7-3bestmodel.pt`、`models/7-3testmodel.pt` | 历史/实验模型 | LFS 指针 |
| P2 | `models/external/**/best.pt` | 外部 fall hint/base 模型 | LFS 指针 |

## 4. RTMPose / MMPose 相关文件

当前主链路建议先使用 `yolo11_legacy`，不建议第一步就切到 RTMPose。RTMPose/MMPose 依赖更重、延迟更高，适合作为后续姿态质量对比。

如果确实要启用 `POSE_PROVIDER=rtmpose_onnx` 或 `POSE_PROVIDER=mmpose`，还需要补齐：

| Provider | 必需文件 | 当前状态 |
|---|---|---|
| `rtmpose_onnx` | `models/rtmpose/rtmpose-x-body7-384x288.onnx` | 当前不存在 |
| `rtmpose_onnx` | 或 README 提到的 `rtmpose-m-body7-256x192` 解压后的 `end2end.onnx` | 当前 zip 也是 LFS 指针，不是真 zip |
| `mmpose` | `models/rtmpose/rtmpose_l_pose_adaptation_384x288.py` | 已存在 |
| `mmpose` | `models/rtmpose/rtmpose-l-pose-adapted-best.pth` | LFS 指针，期望约 111,552,275 B |
| `mmpose` | 对应 OpenMMLab/MMPose Python 依赖 | 需要单独安装验证 |

当前 `models/rtmpose` 目录里只有配置文件是真文件，`.pth` 仍是 LFS 指针。

## 5. 已存在且应保留的配套文件

这些不是大权重，但运行和排障时有用。当前本地已经存在，应随模型一起保留。

| 文件 | 用途 |
|---|---|
| `models/fall_lstm_v5_features.json` | LSTM 输入特征 schema |
| `models/fall_lstm_v5_threshold_calibration.json` | LSTM 阈值校准 |
| `models/fall_lstm_v5_train_config.json` | LSTM 训练配置记录 |
| `models/fall_lstm_v5_metrics.json` | LSTM 指标记录 |
| `models/yolo_fall_hint_v2_plus_b012_metrics.json` | fall hint 指标记录 |
| `models/pose_yolo_batch001_003_yolo11s_metrics.json` | pose 指标记录 |
| `models/pose_yolo_batch001_003_yolo11s_link_match_metrics.json` | pose 与 track 匹配指标 |
| `models/person_yolo_batch001_yolov8n_metrics.json` | 自训练 person 候选指标 |

补文件时不要只复制 `.pt` / `.onnx`。配套 JSON 可以帮助确认模型版本、schema 和阈值是否匹配。

## 6. 如何判断模型文件是否真实

不要只看文件名是否存在，必须看文件大小和文件头。

### 6.1 快速检查命令

在 PowerShell 中运行：

```powershell
Get-ChildItem -Recurse -Include *.pt,*.onnx,*.pth,*.zip -File |
  Select-Object FullName,Length |
  Sort-Object Length
```

如果关键模型只有 `130` 到 `134` 字节，基本就是 LFS 指针。

### 6.2 查看文件头

```powershell
Get-Content yolov8n.pt -TotalCount 3
```

如果看到：

```text
version https://git-lfs.github.com/spec/v1
oid sha256:...
size ...
```

说明这不是模型本体。

### 6.3 当前核心文件的期望校验信息

这些 SHA 前缀来自当前 LFS 指针，可用于寻找原始资产。

| 文件 | LFS SHA256 前缀 | 期望大小 |
|---|---|---:|
| `yolov8n.pt` | `f59b3d833e2f` | 6,549,796 B |
| `models/yolo_fall_hint_v2_plus_b012_best.pt` | `4bafc88b2ec0` | 5,461,914 B |
| `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt` | `9af8f3990296` | 5,455,706 B |
| `yolo11n-pose.pt` | `869e83fcdffd` | 6,255,593 B |
| `models/pose_yolo_batch001_003_yolo11s_best.pt` | `b03c350774db` | 20,178,504 B |
| `models/fall_lstm_v5.onnx` | `01af710c6f89` | 85,630 B |
| `models/person_yolo_batch001_yolov8n_best.pt` | `127e97f88ca3` | 6,250,538 B |
| `models/rtmpose/rtmpose-l-pose-adapted-best.pth` | `6f7ad7be5496` | 111,552,275 B |

## 7. 从哪里找这些文件

优先顺序如下。

1. 原始 Git 仓库加 Git LFS  
   当前 `D:\camera` 没有 `.git` 目录，不能在这里直接 `git lfs pull`。需要找到原始仓库地址，重新 clone：

   ```powershell
   git lfs install
   git clone <repo-url> D:\camera_full
   cd D:\camera_full
   git lfs pull
   ```

   然后把真实权重复制回当前路径，或直接使用完整 clone 后的目录。

2. 之前能正常运行的机器  
   查找同名文件，重点看大小是否接近期望大小。不要复制 130 字节的小文件。

3. 备份目录或交付包  
   重点查找这些目录名或文件名：

   ```text
   pose_detection_model_bundle
   vision_service
   models
   fall_lstm_v5.onnx
   pose_yolo_batch001_003_yolo11s_best.pt
   yolo_fall_hint_v2_plus_b012_best.pt
   ```

4. Ultralytics 官方自动下载  
   `yolov8n.pt`、`yolo11n-pose.pt` 这类通用模型通常可以由 Ultralytics 自动下载，但项目自训练模型不能靠官方下载。

## 8. 推荐恢复顺序

不要一次性全开。建议按下面顺序恢复，这样最容易定位问题。

### 阶段 A：只保证服务和视频源

目标：服务可启动，摄像头或 mock 视频稳定。

`.env` 保持安全配置：

```env
MOCK_CAMERA_ENABLED=true
DEFAULT_RTSP_URL=

DETECTION_ENABLED=false
FALL_DETECTOR_ENABLED=false
ENABLE_TRACKING=false
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
ENABLE_TEMPORAL=false
MAIN_SYSTEM_ALERT_ENABLED=false
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/status
Invoke-RestMethod http://127.0.0.1:8000/integration/results/camera_01/latest
```

期望：

```text
service_status=running
camera connected=true
objects=[]
fall_detected=false
```

### 阶段 B：开启人体检测和跟踪

前置文件：

```text
yolov8n.pt
```

`.env`：

```env
DETECTION_ENABLED=true
YOLO_MODEL_PATH=yolov8n.pt
ENABLE_TRACKING=true
```

验证重点：

```text
detection.enabled=true
detection.loaded=true
latest_raw_person_count > 0
tracking.tracker_running=true
tracked_objects_count > 0
```

### 阶段 C：开启跌倒提示检测

前置文件二选一：

```text
models/yolo_fall_hint_v2_plus_b012_best.pt
models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt
```

推荐先用文档中较稳定的 v2：

```env
FALL_DETECTOR_ENABLED=true
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_v2_plus_b012_best.pt
YOLO_FALL_CONFIDENCE=0.25
YOLO_FALL_IMGSZ=640
```

验证重点：

```text
fall_hint_fps > 0
detector.fall_detector.model_name 正确
latest_fall_model_count 可观测
```

### 阶段 D：开启姿态

前置文件：

```text
models/pose_yolo_batch001_003_yolo11s_best.pt
```

推荐配置：

```env
ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
YOLO11_POSE_MODEL_PATH=models/pose_yolo_batch001_003_yolo11s_best.pt
YOLO11_POSE_IMGSZ=640
YOLO11_POSE_CONF=0.12
YOLO11_POSE_HALF=true
YOLO11_POSE_SMOOTHING=true
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=800
POSE_MAX_FRAME_AGE_MS=800
POSE_SKIP_WHEN_INFERENCE_BUSY=true
POSE_INFERENCE_LOCK_WAIT_MS=160
```

验证重点：

```text
pose.pose_enabled=true
pose.pose_provider=yolo11_legacy
pose.pose_model_path=models/pose_yolo_batch001_003_yolo11s_best.pt
pose.inference_success_count 增长
pose.pose_valid_rate > 0
```

### 阶段 E：开启时序 LSTM

前置文件：

```text
models/fall_lstm_v5.onnx
models/fall_lstm_v5_features.json
models/fall_lstm_v5_threshold_calibration.json
```

推荐配置：

```env
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v5_features.json
TEMPORAL_MODEL_WINDOW_SIZE=32
TEMPORAL_MODEL_INPUT_DIM=15
TEMPORAL_WARMUP_MIN_SIZE=16
TEMPORAL_FALLBACK_TO_MOCK=false
```

如果没有 GPU 或 CUDA provider 不稳定，先用 CPU：

```env
TEMPORAL_ONNX_PROVIDERS=CPUExecutionProvider
```

验证重点：

```text
temporal.enabled=true
temporal.model_provider=onnx_lstm
temporal.model_loaded=true
temporal.model_path=models/fall_lstm_v5.onnx
temporal.fallback_active=false
```

### 阶段 F：接真实摄像头

前置内容：

```text
真实 RTSP 地址
摄像头账号
摄像头密码
摄像头 IP、端口、路径
```

配置：

```env
DEFAULT_RTSP_URL=rtsp://<user>:<password>@<camera-ip>:<port>/<path>
MOCK_CAMERA_ENABLED=false
```

或者启动后调用：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/stream/start `
  -ContentType application/json `
  -Body '{"camera_id":"camera_01","rtsp_url":"rtsp://<user>:<password>@<camera-ip>:<port>/<path>"}'
```

验证重点：

```text
main_stream.source_url_masked 不是 mock://colorbars
connected=true
stream_state=connected
frame_age_ms < 3000
capture_fps > 0
```

### 阶段 G：接主系统告警

前置内容：

```text
主系统 IP
主系统端口
主系统 API 前缀
fall event 接收路径
鉴权 token，如有
```

先 dry-run：

```env
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_REPORT_DRY_RUN=true
MAIN_SYSTEM_BASE_URL=http://<main-system-ip>:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
VISION_SERVICE_PUBLIC_BASE_URL=http://<vision-service-ip>:8000
```

确认 payload 正常后再真实 POST：

```env
MAIN_SYSTEM_REPORT_DRY_RUN=false
```

验证重点：

```text
fall_event_reporter.enabled=true
fall_event_reporter.endpoint 正确
fall_event_reporter.last_post_status 为 2xx
polling_alert.should_popup 在确认跌倒时为 true
```

## 9. 完整功能目标配置示例

下面是模型补齐后的完整功能配置样例。不要在模型缺失时直接套用。

```env
APP_NAME=vision-service
LOG_LEVEL=INFO

DEFAULT_CAMERA_ID=camera_01
DEFAULT_RTSP_URL=rtsp://<user>:<password>@<camera-ip>:<port>/<path>
MOCK_CAMERA_ENABLED=false
MOCK_CAMERA_WIDTH=1280
MOCK_CAMERA_HEIGHT=720
MOCK_CAMERA_FPS=25

DETECTION_ENABLED=true
YOLO_MODEL_PATH=yolov8n.pt
YOLO_CONFIDENCE=0.35
YOLO_IMGSZ=640
YOLO_DEVICE=
DETECTION_INTERVAL_MS=100

FALL_DETECTOR_ENABLED=true
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_v2_plus_b012_best.pt
YOLO_FALL_CONFIDENCE=0.25
YOLO_FALL_IMGSZ=640
YOLO_FALL_DEVICE=
FALL_DETECTOR_INTERVAL_MS=200

ENABLE_TRACKING=true

ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
POSE_DEPLOYMENT_GUARD_ENABLED=false
POSE_FPS=3
POSE_WORKER_FPS=3
YOLO11_POSE_MODEL_PATH=models/pose_yolo_batch001_003_yolo11s_best.pt
YOLO11_POSE_IMGSZ=640
YOLO11_POSE_CONF=0.12
YOLO11_POSE_DEVICE=
YOLO11_POSE_HALF=true
YOLO11_POSE_SMOOTHING=true
YOLO11_POSE_MAX_JUMP_RATIO=0.18
YOLO11_POSE_MIN_MATCH_IOU=0.12
YOLO11_POSE_MAX_CENTER_DISTANCE_RATIO=0.65
YOLO11_POSE_MATCH_SCORE_THRESHOLD=0.30
POSE_RESULT_TTL_MS=800
POSE_PUBLISH_MAX_FRAME_DELTA=8
POSE_MAX_TRACKING_FRAME_DELTA=2
POSE_MAX_FRAME_AGE_MS=800
POSE_SKIP_WHEN_INFERENCE_BUSY=true
POSE_INFERENCE_LOCK_WAIT_MS=160
POSE_MAX_INFERENCE_MS=1500

ENABLE_TEMPORAL=true
FEATURE_WINDOW_SIZE=32
TEMPORAL_TRACK_MODE=all_tracks
TEMPORAL_SEQUENCE_KEY_MODE=identity
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v5_features.json
TEMPORAL_MODEL_WINDOW_SIZE=32
TEMPORAL_MODEL_INPUT_DIM=15
TEMPORAL_WARMUP_MIN_SIZE=16
TEMPORAL_FALLBACK_TO_MOCK=false
TEMPORAL_ONNX_PROVIDERS=CPUExecutionProvider

ENABLE_BEHAVIOR=false
ENABLE_IDENTITY=false
ENABLE_TARGET_BINDING=false
ENABLE_IDENTITY_BINDING=false

MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_REPORT_DRY_RUN=true
MAIN_SYSTEM_BASE_URL=http://<main-system-ip>:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TIMEOUT_MS=2500
MAIN_SYSTEM_ALERT_COOLDOWN_SECONDS=90
MAIN_SYSTEM_ALERT_TOKEN=
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
VISION_SERVICE_PUBLIC_BASE_URL=http://<vision-service-ip>:8000
FALL_EVENT_SNAPSHOT_DIR=logs/fall_events/snapshots
```

说明：

- `POSE_DEPLOYMENT_GUARD_ENABLED=false` 是恢复阶段建议值，避免证据包不匹配导致服务启动被拦截。正式上线前再开启并跑证据包。
- `TEMPORAL_ONNX_PROVIDERS=CPUExecutionProvider` 是保守配置。确认 CUDA/ONNX Runtime GPU 正常后再换成 `CUDAExecutionProvider,CPUExecutionProvider`。
- 主系统先保持 `MAIN_SYSTEM_REPORT_DRY_RUN=true`，确认事件结构和截图 URL 正常后再设为 `false`。

## 10. 最终验收清单

补齐文件和配置后，至少检查下面这些字段。

```text
/status:
- service_status = running
- cameras[0].connected = true
- detection[0].enabled = true
- detection[0].loaded = true
- detection[0].latest_raw_person_count 能随画面变化
- tracking.tracker_running = true
- pose.pose_enabled = true
- pose.pose_provider = yolo11_legacy
- pose.inference_success_count > 0
- temporal.enabled = true
- temporal.model_loaded = true
- temporal.fallback_active = false
- pipeline.result_publish_fps > 0

/integration/results/camera_01/latest:
- objects 有 person
- person 有 track_id
- pose 开启时 person.pose 有 keypoints 或明确 debug
- temporal 开启时 person.temporal 有 window_size / fall_probability
- fall_decision 字段存在
- alarm_confirmed 只在确认跌倒后为 true
```

如果这些字段满足，才可以认为“完整功能链路”基本恢复。

## 11. 当前还需要人工提供的信息

除了模型文件，还需要确认以下外部信息：

1. 真实摄像头 RTSP 地址、账号、密码。
2. 主系统接收地址：IP、端口、API 前缀、事件路径。
3. 主系统是否需要 `X-Vision-Service-Token` 或其他鉴权。
4. 当前机器是否有 GPU、CUDA、对应 PyTorch/ONNX Runtime GPU 环境。
5. 是否要启用身份识别。如果启用，需要额外确认 InsightFace 模型缓存和身份库 `data/identities`。

## 12. 一句话行动项

先找到并复制真实模型本体，至少补齐：

```text
yolov8n.pt
models/yolo_fall_hint_v2_plus_b012_best.pt
models/pose_yolo_batch001_003_yolo11s_best.pt
models/fall_lstm_v5.onnx
```

确认这些文件不再是 130 字节左右的 LFS 指针后，再按“阶段 B 到阶段 G”逐步打开 `.env` 开关。
