# 完整链路恢复状态与剩余问题清单

生成时间：2026-07-08 13:42  
工作目录：`D:\camera`  
补充模型来源：`C:\Users\Test1\Desktop\新建文件夹`

## 1. 已完成事项

已将补充模型文件放到项目标准位置，并覆盖原来的 Git LFS 指针文件。

原占位文件已备份到：

```text
artifacts/model_lfs_pointer_backup_20260708_133909
```

`.env` 修改前已备份到：

```text
artifacts/env_backup_before_full_chain_20260708_133931.env
```

## 2. 已放置的模型文件

| 文件 | 当前路径 | 当前大小 | 状态 |
|---|---|---:|---|
| 人体检测模型 | `yolov8n.pt` | 6,549,796 B | 已放置，可加载 |
| 姿态基线模型 | `yolo11n-pose.pt` | 6,255,593 B | 已放置，可作为备用 |
| 跌倒提示 v2 | `models/yolo_fall_hint_v2_plus_b012_best.pt` | 5,461,914 B | 已放置，可加载，当前启用 |
| 跌倒提示 v3 候选 | `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt` | 5,455,706 B | 已放置，备用 |
| 项目姿态模型 | `models/pose_yolo_batch001_003_yolo11s_best.pt` | 20,178,504 B | 已放置，可加载，当前启用 |
| 时序 LSTM | `models/fall_lstm_v5.onnx` | 85,630 B | 已放置，可加载，当前启用 |
| LSTM schema | `models/fall_lstm_v5_features.json` | 729 B | 已放置，schema hash 正确 |

## 3. 模型加载验证

使用运行服务相同的 Python 环境：

```text
C:\Users\Test1\.conda\envs\health\python.exe
```

验证结果：

```text
ultralytics OK 8.4.45
onnxruntime OK 1.24.3
cv2 OK 4.13.0
numpy OK 2.4.4
fastapi OK 0.115.8
```

模型加载结果：

```text
yolov8n.pt                                              OK, names_count=80
models/yolo_fall_hint_v2_plus_b012_best.pt              OK, names_count=7
models/pose_yolo_batch001_003_yolo11s_best.pt           OK, names_count=1
models/fall_lstm_v5.onnx                                OK, input=input, output=fall_probability
```

结论：当前补充的核心模型是真实模型文件，不是 LFS 指针，并且能被运行时库加载。

## 4. 已更新 `.env`

当前已打开内部 AI 主链路：

```env
DETECTION_ENABLED=true
FALL_DETECTOR_ENABLED=true
ENABLE_TRACKING=true
ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
YOLO11_POSE_MODEL_PATH=models/pose_yolo_batch001_003_yolo11s_best.pt
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v5_features.json
TEMPORAL_ONNX_PROVIDERS=CPUExecutionProvider
```

当前未强开主系统真实告警：

```env
MAIN_SYSTEM_ALERT_ENABLED=false
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

原因：还没有确认主系统接收地址、鉴权 token、是否允许真实 POST。避免误发和误判网络故障。

## 5. 服务重启与当前运行状态

已重启服务：

```text
C:\Users\Test1\.conda\envs\health\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

当前 `/status` 摘要：

```text
service_status=running
source=rtsp://admin:***@192.168.8.252:10554/tcp/av0_0
detection.enabled=true
detection.loaded=true
detection_fps≈6.79
fall_hint_fps≈3.40
tracking.tracker_running=true
pose.pose_enabled=true
pose.pose_provider=yolo11_legacy
temporal.enabled=true
temporal.model_loaded=true
temporal.fallback_active=false
fall_event_reporter.enabled=false
```

当前 `/integration/results/camera_01/latest` 摘要：

```text
service_state=running
camera_lost=false
capture_stale=false
source_fps≈14.88
analysis_fps≈16.10
fall_detected=false
objects=[]
detector.name=ultralytics_yolo
detector.fall_detector.model_name=models/yolo_fall_hint_v2_plus_b012_best.pt
```

结论：服务、摄像头、人体检测模型、fall hint 模型、tracking worker、pose worker、temporal ONNX 模型都已经启动。当前没有检测到人，所以后续 pose 和 temporal 没有目标可处理。

## 6. 当前仍未完全验证的功能

### 6.1 当前画面没有检测到人

现象：

```text
latest_raw_person_count=0
tracked_objects_count=0
pose.inference_attempt_count=0
pose.skip_reasons={"no_tracking":157}
objects=[]
```

解释：

检测模型已加载并运行，但当前画面里没有被检测为 `person` 的目标。由于没有 person，tracking 没有 track，pose 没有目标，temporal 也没有活动窗口。这不是模型加载失败，而是当前输入画面没有触发下游链路。

需要检查：

1. 摄像头画面中是否有人。
2. 摄像头角度是否拍到完整人体。
3. 光照、遮挡、距离是否导致 `yolov8n.pt` 未检出。
4. 如果画面有人但仍 `latest_raw_person_count=0`，需要调低 `YOLO_CONFIDENCE` 或换用自训练 person 模型。

### 6.2 `.env` 未写入固定 RTSP，但运行态接入了 RTSP

当前 `.env` 中：

```env
DEFAULT_RTSP_URL=
MOCK_CAMERA_ENABLED=true
```

但当前 `/status` 显示运行态 source 是：

```text
rtsp://admin:***@192.168.8.252:10554/tcp/av0_0
```

这说明 RTSP 很可能是前端、接口调用或外部启动逻辑在服务启动后传入的，不是 `.env` 固定配置。

如果希望服务每次重启后自动拉同一个真实摄像头，需要把 `.env` 改成：

```env
DEFAULT_RTSP_URL=rtsp://<user>:<password>@192.168.8.252:10554/tcp/av0_0
MOCK_CAMERA_ENABLED=false
```

注意：不要把带明文密码的 `.env` 提交或公开。

### 6.3 主系统真实告警未开启

当前状态：

```text
fall_event_reporter.enabled=false
MAIN_SYSTEM_ALERT_ENABLED=false
MAIN_SYSTEM_REPORT_DRY_RUN=true
```

要启用完整主系统告警，还需要你确认：

```text
主系统 IP
主系统端口
API 前缀，例如 /api/v1
跌倒事件接收路径，例如 /video-bridge/fall-events
是否需要 X-Vision-Service-Token
token 的真实值
VISION_SERVICE_PUBLIC_BASE_URL，也就是主系统访问本服务截图的地址
```

确认后再打开：

```env
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_REPORT_DRY_RUN=false
MAIN_SYSTEM_BASE_URL=http://<main-system-ip>:<port>/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN=<token_if_required>
VISION_SERVICE_PUBLIC_BASE_URL=http://<vision-service-ip>:8000
```

### 6.4 身份识别未开启

当前身份识别仍关闭：

```env
ENABLE_IDENTITY=false
ENABLE_IDENTITY_BINDING=false
```

如果“全部功能”包含人脸身份绑定，还需要：

1. 确认是否安装 `insightface`。
2. 确认 InsightFace 模型缓存是否存在，例如 `buffalo_l`。
3. 确认身份库目录 `data/identities` 是否有注册人员数据。
4. 再打开：

```env
ENABLE_IDENTITY=true
ENABLE_IDENTITY_BINDING=true
```

当前跌倒识别主链路不强依赖身份识别，所以我没有默认开启。

### 6.5 RTMPose / MMPose 候选仍未补齐

当前主链路使用 `yolo11_legacy` pose，已经可加载。

如果要测试 RTMPose/MMPose，还缺：

```text
models/rtmpose/rtmpose-x-body7-384x288.onnx
models/rtmpose/rtmpose-l-pose-adapted-best.pth 的真实 100MB+ 文件
MMPose/OpenMMLab 依赖
```

这不是当前主链路必需项。

### 6.6 `/ws/alarms` 有 403 日志

日志里仍有：

```text
WebSocket /ws/alarms 403
```

这通常表示前端或外部客户端连接了告警 WebSocket，但请求不满足服务端要求。当前主告警 reporter 未开启，因此这不是 AI 链路阻塞项。若要联调弹窗/告警 WebSocket，需要单独检查该接口的鉴权和客户端连接方式。

## 7. 下一步建议

1. 让摄像头画面中出现一个人，观察：

```text
latest_raw_person_count > 0
tracked_objects_count > 0
pose.inference_attempt_count > 0
pose.inference_success_count > 0
temporal.active_tracks > 0
```

2. 做一次跌倒/非跌倒测试，观察：

```text
fall_hint_fps > 0
detector.fall_detector 存在
fall_decision 有状态
alarm_preview 有状态
```

3. 确认主系统接收信息后，再打开真实告警推送。

4. 如果当前摄像头有人但检测不到，优先调整：

```env
YOLO_CONFIDENCE=0.25
YOLO_IMGSZ=640
```

必要时再评估是否切换到自训练 person 模型。

## 8. 当前结论

内部完整 AI 主链路已经恢复到可运行状态：

```text
RTSP / mock frame
-> YOLO person detection
-> YOLO fall hint detection
-> ByteTrack tracking
-> YOLO11 legacy pose
-> ONNX LSTM temporal model
-> fall feature builder / fusion
-> latest result API
```

尚未完成的是外部联动与场景触发验证：

```text
主系统真实告警推送：等待主系统地址/token 确认
身份识别：等待是否需要启用
pose/temporal 实际目标验证：等待画面中出现 person
RTMPose 候选：非主链路，仍缺额外权重和依赖
```
