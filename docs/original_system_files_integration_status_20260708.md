# 原系统文件合入状态与剩余阻塞

生成时间：2026-07-08  
工作目录：`D:\camera`

## 1. 已合入的原系统文件

已从 `C:\Users\Test1\Desktop\新建文件夹` 合入：

```text
.env
.env.example
.gitignore
```

已从 `C:\Users\Test1\Downloads` 合入：

```text
docs/project_reproduction_handoff_20260708.md
```

合入前已备份当前文件：

```text
artifacts/env_backup_before_original_restore_20260708_151715.env
artifacts/env_example_backup_before_original_restore_20260708_151715.env.example
artifacts/gitignore_backup_before_original_restore_20260708_151715.gitignore
```

## 2. 已做的必要兼容调整

原系统 `.env` 基本保留，但为了让当前机器可用，做了以下调整。

### 2.1 LSTM ONNX provider

原配置：

```env
TEMPORAL_ONNX_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider
```

当前配置：

```env
TEMPORAL_ONNX_PROVIDERS=CPUExecutionProvider
```

原因：当前 `C:\Users\Test1\.conda\envs\health` 环境中 `onnxruntime` 可用 provider 为：

```text
AzureExecutionProvider
CPUExecutionProvider
```

没有 `CUDAExecutionProvider`。虽然 PyTorch 能识别 RTX 3060，YOLO 可以走 `cuda:0`，但 ONNX Runtime GPU provider 当前不可用。为了避免时序 LSTM 加载失败，先使用 CPU provider。

### 2.2 RTSP 地址

原系统 `.env` 指向：

```env
DEFAULT_RTSP_URL=rtsp://admin:***@192.168.8.250:10554/tcp/av0_0
```

当前调整为：

```env
DEFAULT_RTSP_URL=rtsp://admin:***@192.168.8.252:10554/tcp/av0_0
```

原因：本轮恢复过程中，`192.168.8.252` 曾经在 `/status` 中出现过 connected 状态；`192.168.8.250` 在重启后无法连接。

### 2.3 Capture backend

原系统 `.env`：

```env
CAPTURE_BACKEND=subprocess_opencv
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp|stimeout;8000000
```

当前调整为：

```env
CAPTURE_BACKEND=opencv
OPENCV_FFMPEG_CAPTURE_OPTIONS=
```

原因：恢复模型后，普通 `opencv` 后端曾经成功连接并产生帧；切到原系统 `subprocess_opencv` 后，RTSP 处于 connecting/reconnecting。为减少变量，当前保留最简 `opencv` 配置。

## 3. 当前模型与 AI 链路状态

核心模型已经放到标准位置并验证可加载：

```text
yolov8n.pt
yolo11n-pose.pt
models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt
models/yolo_fall_hint_v2_plus_b012_best.pt
models/pose_yolo_batch001_003_yolo11s_best.pt
models/fall_lstm_v5.onnx
models/fall_lstm_v5_features.json
```

已验证：

```text
Ultralytics 可加载 yolov8n.pt
Ultralytics 可加载 yolo_fall_hint_v2_plus_b012_best.pt
Ultralytics 可加载 pose_yolo_batch001_003_yolo11s_best.pt
ONNX Runtime 可加载 fall_lstm_v5.onnx
```

当前 `.env` 已启用：

```env
DETECTION_ENABLED=true
FALL_DETECTOR_ENABLED=true
ENABLE_TRACKING=true
ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
ENABLE_TEMPORAL=true
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_REPORT_DRY_RUN=false
```

也就是说，代码、模型、运行配置层面的完整主链路已经合入。

## 4. 当前阻塞问题

### 4.1 RTSP 当前无法打开

当前 `/status` 中看到：

```text
service_status=running
source=rtsp://admin:***@192.168.8.252:10554/tcp/av0_0
connected=false
stream_state=connecting 或 reconnecting
capture_fps=0
detection_fps=0
fall_hint_fps=0
```

解释：

服务和模型已启动，但没有摄像头帧进入，所以检测、跟踪、姿态、时序没有输入可处理。

需要现场检查：

1. 摄像头 `192.168.8.252` 是否在线。
2. 摄像头账号密码是否仍为当前 `.env` 中的值。
3. 摄像头 RTSP 端口 `10554` 和路径 `/tcp/av0_0` 是否正确。
4. 当前机器是否能访问 `192.168.8.252:10554`。
5. 是否应改回原系统地址 `192.168.8.250`，或使用其他实际在线摄像头。
6. 是否有其他程序占用了摄像头连接数。

建议用 VLC 或 ffmpeg 单独验证：

```powershell
ffplay "rtsp://<user>:<password>@<camera-ip>:10554/tcp/av0_0"
```

只有 RTSP 单独可播放后，再让 Vision Service 拉流。

### 4.2 主系统推送配置已打开，但尚未触发真实告警

当前配置：

```env
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_REPORT_DRY_RUN=false
MAIN_SYSTEM_BASE_URL=http://192.168.8.248:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN=<已在本地 .env 中配置>
```

当前未触发真实 POST，因为没有摄像头帧和跌倒事件。

需要现场确认：

1. 主系统 `192.168.8.248:8000` 是否在线。
2. 接口 `/api/v1/video-bridge/fall-events` 是否存在。
3. token 是否仍有效。
4. 主系统是否能访问 `VISION_SERVICE_PUBLIC_BASE_URL` 指向的截图 URL。

### 4.3 ONNX Runtime GPU 未启用

当前不是功能阻塞，因为 LSTM 很小，CPU 可运行。

如果必须让 LSTM 使用 GPU，需要安装匹配版本：

```powershell
pip install onnxruntime-gpu
```

并确保：

```python
import onnxruntime as ort
print(ort.get_available_providers())
```

输出包含：

```text
CUDAExecutionProvider
```

之后再恢复：

```env
TEMPORAL_ONNX_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider
```

## 5. 当前建议

先不要继续改模型参数。当前最该处理的是外部输入：

1. 用 VLC/ffplay 确认哪个 RTSP 地址真正可用。
2. 把 `.env` 的 `DEFAULT_RTSP_URL` 固定为可播放地址。
3. 重启服务。
4. `/status` 出现：

```text
connected=true
capture_fps>0
detection.loaded=true
detection_fps>0
```

之后再让画面中出现人，验证：

```text
latest_raw_person_count>0
tracked_objects_count>0
pose.inference_success_count>0
temporal.active_tracks>0
```

最后做跌倒动作测试，验证主系统推送。

## 6. 结论

已完成：

```text
原系统配置文件合入
复现交付说明合入
模型资产放置
模型加载验证
AI 主链路配置启用
主系统推送配置启用
```

当前剩余阻塞：

```text
RTSP 摄像头当前无法打开，导致没有帧进入系统
主系统推送尚未在真实跌倒事件中验证
ONNX GPU provider 未安装，但 CPU provider 可用，不影响功能
```
