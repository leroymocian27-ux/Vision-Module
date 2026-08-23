# Phase 1 Acceptance Record

## 1. 当前已完成能力

第一阶段目标是完成稳定实时视频链路与真实 person 检测能力，不进入 Pose、GRU/LSTM、人脸识别、目标绑定、跌倒状态机和主后端 POST。

当前已完成并通过联调的能力：

- FastAPI 服务启动与基础 API。
- `/healthz` 存活检查。
- `/status` 运行状态检查。
- Mock camera 输入链路。
- 本地视频文件输入链路。
- 真实 RTSP 子码流输入链路。
- 单摄像头单次拉流。
- `FrameBuffer` 最新帧缓存。
- WebRTC 视频输出。
- WebSocket bbox JSON 输出。
- 前端 `/demo` 视频播放与 canvas overlay 数据链路。
- Ultralytics YOLO person detect。
- RTSP 健康状态暴露：`connected`、`frame_age_ms`、`capture_fps`、`reconnect_count`、`last_frame_at`、`stream_state`。
- 断流后自动重连与恢复后状态回稳。

## 2. 测试环境

| 项目 | 当前值 |
| --- | --- |
| 工作目录 | `D:\vision_service` |
| 操作系统 | Windows |
| 环境管理 | Conda |
| 当前推荐环境 | `torchgpu` |
| Python | `3.11.15` |
| PyTorch | `2.6.0+cu124` |
| CUDA runtime | `12.4` |
| CUDA 可用 | `True` |
| GPU | `NVIDIA GeForce RTX 4060 Laptop GPU` |
| 服务地址 | `http://127.0.0.1:8000` |
| 前端 Demo | `http://127.0.0.1:8000/demo` |
| 默认检测模型配置 | `YOLO_MODEL_PATH=yolov8n.pt` |
| stale 阈值 | `STREAM_STALE_THRESHOLD_MS=3000` |
| stale 重连阈值 | `STREAM_STALE_RECONNECT_AFTER_MS=6000` |

环境验证命令：

```powershell
conda activate torchgpu
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.version.cuda); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU')"
python -c "import fastapi, cv2, numpy, aiortc, av, ultralytics, torch; print('deps ok')"
```

实际结果：

```text
2.6.0+cu124
True
12.4
NVIDIA GeForce RTX 4060 Laptop GPU
deps ok
```

说明：早期 `vision311` CPU 环境已完成 mock camera 与本地视频链路验收；当前真实 RTSP 与恢复测试以 `torchgpu` 环境作为记录基线。

## 3. RTSP 地址脱敏记录

摄像头信息：

| 项目 | 值 |
| --- | --- |
| 品牌/型号 | xstrive / 迅思维 XSWCAM-WB4MP |
| 摄像头 IP | `192.168.8.254` |
| RTSP 端口 | `554` |
| 用户名 | `admin` |
| 子码流路径 | `/tcp/av0_1` |
| 主码流路径 | `/tcp/av0_0` |
| 本轮使用 | 子码流 |

脱敏后的 RTSP 地址：

```text
rtsp://admin:***@192.168.8.254:554/tcp/av0_1
```

实际 `/status` 脱敏结果：

```text
source_url_masked: rtsp://admin:***@192.168.8.254:554/tcp/av0_1
```

注意：终端、截图和文档中不要保存明文密码。

## 4. `/status` 字段说明

`/status` 当前返回服务、摄像头、检测和流媒体客户端状态。

摄像头关键字段：

| 字段 | 含义 |
| --- | --- |
| `connected` | 底层捕获链路当前是否认为连接存在，不能单独代表画面健康 |
| `frame_age_ms` | 当前最新帧距离现在的时间，越小越健康 |
| `capture_fps` | 捕获线程近期实际帧率 |
| `reconnect_count` | 当前 worker 已发生的重连次数 |
| `last_frame_at` | 最近一帧的 UTC 时间 |
| `stream_state` | 面向业务和前端的综合流状态 |
| `last_error` | 最近一次捕获错误 |

`stream_state` 状态定义：

| 状态 | 含义 |
| --- | --- |
| `disconnected` | 未连接或连接失败 |
| `connecting` | 正在连接或重新打开流 |
| `connected` | 连接存在，且帧正常更新 |
| `stale` | 连接可能仍存在，但 `frame_age_ms` 超过 stale 阈值 |
| `reconnecting` | 正在主动重连 |

判断原则：

```text
connected=true 不等于摄像头健康。
应同时观察 stream_state、frame_age_ms、capture_fps、reconnect_count 和 last_frame_at。
```

## 5. 正常拉流结果

启动真实 RTSP 子码流后，连续采样结果稳定。

关键结果：

```text
source_url_masked: rtsp://admin:***@192.168.8.254:554/tcp/av0_1
connected: true
stream_state: connected
frame_width: 1920
frame_height: 1080
frame_age_ms: 0-110
capture_fps: 9.83-10.02
reconnect_count: 0
last_error: null
```

连续采样记录：

```text
sample stream_state connected frame_seq frame_age_ms capture_fps reconnect_count last_error
1      connected    true      958       110          9.99        0
2      connected    true      977       63           9.83        0
3      connected    true      997       47           9.84        0
4      connected    true      1018      0            9.83        0
5      connected    true      1038      16           9.84        0
```

当前后续稳定状态也已确认：

```text
frame_seq: 3478
frame_age_ms: 32
capture_fps: 10.02
reconnect_count: 2
stream_state: connected
last_error: null
```

结论：真实 RTSP 子码流正常拉流通过。

## 6. 断流测试结果

断开摄像头网络后，`/status` 返回：

```text
connected: false
stream_state: connecting
frame_age_ms: 4515
reconnect_count: 1
last_error: read frame failed
```

结论：

- 服务未崩溃。
- `connected` 从 `true` 变为 `false`。
- `frame_age_ms` 超过 `3000ms`。
- `reconnect_count` 增长。
- 本次断流走的是 `read frame failed` 后重连路径，不是纯 `stale` 路径。

## 7. 恢复测试结果

恢复摄像头网络后，第一次检查：

```text
connected: true
stream_state: connected
frame_seq: 1847
frame_age_ms: 125
capture_fps: 2.37
reconnect_count: 2
last_error: null
```

等待 5 秒后再次检查：

```text
connected: true
stream_state: connected
frame_seq: 2271
frame_age_ms: 16
capture_fps: 9.99
reconnect_count: 2
last_error: null
```

结论：

- 恢复后 CaptureWorker 成功重新拉流。
- `frame_seq` 继续增长，说明不是缓存旧帧。
- `frame_age_ms` 回到健康范围。
- `capture_fps` 回到约 10 FPS。
- `last_error` 清空。

## 8. `detection_fps` 验证结果

正常 RTSP 拉流时检测状态：

```text
detection.running: true
detection.enabled: true
detection.loaded: true
model_name: yolov8n.pt
detection_fps: 4.61-4.62
inference_latency_ms: 6.70-9.51
last_error: null
```

断流恢复后检测状态：

```text
detection_fps: 1.73 -> 4.61
inference_latency_ms: 10.37 -> 7.46
last_error: null
```

结论：检测链路会随视频恢复而恢复，短暂低帧率是断流恢复窗口内的统计结果，稳定后回到约 `4.6 FPS`。

## 9. 已通过结论

第一阶段当前验收通过。

已确认通过：

- Mock camera 链路通过。
- 本地视频 person 检测链路通过。
- 真实 RTSP 子码流接入通过。
- 单摄像头单次拉流通过。
- `/status` 健康字段暴露通过。
- 正常 10 FPS 左右 RTSP 拉流通过。
- 断流后服务保持运行通过。
- 断流后自动进入连接/重连路径通过。
- 恢复摄像头后画面恢复通过。
- `capture_fps` 回稳通过。
- `detection_fps` 回稳通过。
- WebRTC + WebSocket + `/demo` 基础链路已在第一阶段完成验证。

当前阶段可定义为：

```text
稳定实时视频基础设施 + 真实 Ultralytics YOLO person detect 已形成第一阶段闭环。
```

## 10. 未验证风险

以下风险已记录，但不在本轮继续扩展处理：

| 风险 | 当前状态 | 后续处理建议 |
| --- | --- | --- |
| TCP Established 但不吐帧的纯 `stale` 场景尚未复现 | 本轮断流直接触发 `read frame failed`，进入连接/重连路径 | 后续真实运行中继续观察 `stream_state=stale` 是否出现 |
| WebRTC 长时间播放稳定性还需要继续观察 | 已验证基础播放，但未做长时间持续播放 | 下一阶段做 30-60 分钟播放观察 |
| 多次刷新页面是否只保持单 CaptureWorker 需要继续确认 | 早期观察到 `capture_fps` 未倍增，但 WebRTC peer 清理存在可观察风险 | 下一阶段增加长稳与刷新测试记录 |
| YOLO 长时间运行是否内存/GPU 稳定还需要继续观察 | 已验证 GPU 可用和短时检测 FPS，但未做长时间资源曲线 | 下一阶段观察 GPU 显存、进程内存、推理延迟 |

额外工程说明：

```text
如果 OpenCV 底层 cap.read() 长时间阻塞，当前轻量 watchdog 可能无法立即执行。
本轮已记录该风险，暂不升级为 subprocess capture 或独立 FFmpeg 拉流进程。
```

## 11. 下一阶段建议

建议下一阶段仍然先做稳定性验证，不直接进入复杂算法。

推荐顺序：

1. 先做 WebRTC 长稳测试。
2. 再做 YOLO detect 长稳测试。
3. 最后进入 Pose 叠加。

WebRTC 长稳测试建议：

- 连续播放 30-60 分钟。
- 观察 `webrtc_clients` 是否泄漏。
- 观察刷新页面后是否会残留旧 PeerConnection。
- 观察视频延迟是否累计增加。

YOLO detect 长稳测试建议：

- 连续检测 30-60 分钟。
- 观察 `detection_fps` 是否稳定。
- 观察 `inference_latency_ms` 是否持续升高。
- 观察 CPU、内存、GPU 显存是否稳定。

Pose 叠加建议：

- 仅在 WebRTC 与 YOLO detect 长稳测试通过后进入。
- Pose 只作为检测后的独立模块接入，不改变当前 RTSP、FrameBuffer、WebRTC 和状态监控底座。
