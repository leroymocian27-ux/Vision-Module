# Phase 5.13B Capture Isolation Long-Run Acceptance

## 背景
Phase 5.12 长稳验收确认：上层 AI pipeline 已经稳定，但主进程内 OpenCV `VideoCapture.read()` 存在长阻塞风险。历史数据中出现过：

- `max_frame_age_ms=23641ms`
- `frame_age_ms > 3000ms` 共 `32` 次
- `read_latency_ms` 峰值达到秒级
- `reconnect_delta=9`
- 跨线程 `cap.release()` 打断 `read()` 会触发 FFmpeg 断言：`Assertion fctx->async_lock failed at libavcodec/pthread_frame.c:173`

因此 Phase 5.13 的目标不是继续修补主进程 OpenCV CaptureWorker，而是把 capture 隔离到独立子进程，让 OpenCV/FFmpeg 卡死时不会拖垮主 `vision_service`。

## 解决方案
本阶段实现并验收第一版 `subprocess_opencv` capture backend：

```text
RTSP
-> child process: cv2.VideoCapture.read()
-> resize to 720p
-> JPEG encode quality=60
-> VSF1 length-prefixed binary packet on stdout
-> parent reader daemon thread
-> JPEG decode
-> FrameBuffer latest-frame update
```

关键设计：

- 主进程在 `CAPTURE_BACKEND=subprocess_opencv` 下不直接调用 `cv2.VideoCapture.read()`。
- reader thread 为 daemon，主进程 stop/restart 不被 pipe read 阻塞。
- watchdog 依赖 `last_child_packet_timestamp`，child 活着但不吐帧也会被 kill/restart。
- 保持 `FrameBuffer(maxsize=1)` latest-frame semantics，不做可靠逐帧队列。
- 保留 `CAPTURE_BACKEND=opencv` fallback。

## 新增模块
- `app/camera/capture_process_protocol.py`
- `app/camera/capture_process.py`
- `app/camera/capture_watchdog.py`
- `app/camera/subprocess_capture_worker.py`

## 新增配置
```text
CAPTURE_BACKEND=opencv
CAPTURE_PROCESS_FRAME_TIMEOUT_MS=3000
CAPTURE_PROCESS_RESTART_MS=3000
CAPTURE_IPC_MODE=jpeg_pipe
CAPTURE_JPEG_QUALITY=60
CAPTURE_PROCESS_OUTPUT_HEIGHT=720
CAPTURE_PROCESS_WRITE_FPS=10
CAPTURE_PROCESS_MAX_RESTARTS=0
```

说明：`CAPTURE_PROCESS_MAX_RESTARTS=0` 表示 unlimited。

## 新增 Status 字段
`/status.cameras[0]` 增加：

```text
capture_backend
capture_process_alive
capture_process_pid
capture_process_restart_count
capture_process_last_frame_age_ms
capture_process_last_error
capture_process_last_exit_code
capture_ipc_decode_errors
capture_ipc_dropped_frames
capture_output_width
capture_output_height
```

## 15 分钟验证结果
配置：

```text
CAPTURE_BACKEND=subprocess_opencv
ENABLE_TRACKING=true
ENABLE_IDENTITY_BINDING=true
IDENTITY_BINDING_ASYNC=true
ENABLE_POSE=true
ENABLE_BEHAVIOR=true
ENABLE_TEMPORAL=true
真实 RTSP
```

结果文件：`logs/runtime_debug/phase5_13_subprocess_15min.json`

核心指标：

```text
sample_count: 694
status_failures: 0
connected_ratio: 100%
max_frame_age_ms: 110ms
frame_age > 3000ms: 0
avg_frame_age_ms: 58.92ms
avg_capture_fps: 9.21
reconnect_delta: 0
stale_delta: 0
read_timeout_delta: 0
tracking_worker_fps avg: 10.74
result_publish_fps avg: 9.21
pipeline_errors: 0
temporal_errors: 0
GPU avg: 9.67%
```

结论：15 分钟验收完全通过，没有出现旧 OpenCV 主进程 capture 的 20s 级 stall。

## 30 分钟长稳验证结果
结果文件：`logs/runtime_debug/phase5_13_subprocess_30min.json`

核心指标：

```text
duration_sec: 1800
sample_count: 1488
status_failures: 0
connected_ratio: 97.72%
max_frame_age_ms: 14172ms
avg_frame_age_ms: 180.72ms
frame_age > 3000ms: 23
avg_capture_fps: 8.79
min_capture_fps: 3.31
max_read_latency_ms: 969ms
max_recorded_read_latency_ms: 8187ms
read_timeout_delta: 0
stale_delta: 0
reconnect_delta: 6
tracking_worker_fps avg: 10.65
tracking_worker_fps min: 8.60
result_publish_fps avg: 9.13
result_publish_fps min: 7.46
pose_fps avg: 0.06
pipeline_errors: 0
temporal_errors: 0
GPU avg: 9.26%
vision memory delta: +7.47MB
identity memory delta: +1.12MB
```

30 分钟中发生了 capture 子进程异常/超时重启窗口。典型原因包括：

```text
reconnect_reason=capture_process_exit
reconnect_reason=capture_process_frame_timeout
```

其中最大 `frame_age_ms=14172ms` 出现在一次 `capture_process_frame_timeout` 后的恢复窗口内。重要的是：

- `/status` 全程可访问，`status_failures=0`。
- 主 `vision_service` 未崩溃。
- Tracking/ResultPublisher 没有被 capture 卡死。
- 子进程最终恢复，当前服务仍可继续出帧。

注意：本次 30 分钟采样脚本在运行时尚未记录新增的 `capture_process_*` 字段；脚本已补齐，后续长稳日志会包含子进程 pid/restart/decode/dropped 等字段。本报告中的子进程恢复判断主要来自 `reconnect_reason`、`reconnect_delta`、`stream_state`、`frame_age_ms` 和采样后当前 `/status` 快照。

采样后当前快照：

```text
capture_backend: subprocess_opencv
capture_process_alive: true
capture_process_restart_count: 9
capture_process_last_frame_age_ms: 62ms
capture_ipc_decode_errors: 0
capture_process_last_error: null
frame_age_ms: 47ms
```

## 与 Phase 5.12 对比
| 指标 | Phase 5.12 in-process OpenCV | Phase 5.13 15min subprocess | Phase 5.13B 30min subprocess |
| --- | ---: | ---: | ---: |
| `max_frame_age_ms` | `23641ms` | `110ms` | `14172ms` |
| `frame_age > 3000ms` | `32` | `0` | `23` |
| `connected_ratio` | `92.99%` | `100%` | `97.72%` |
| `tracking_worker_fps avg` | `10.70` | `10.74` | `10.65` |
| `result_publish_fps avg` | `9.17` | `9.21` | `9.13` |
| `pipeline_errors` | `0` | `0` | `0` |
| `temporal_errors` | `0` | `0` | `0` |
| 主服务是否崩溃 | 否 | 否 | 否 |

解读：

- 15 分钟结果非常理想，证明隔离方向有效。
- 30 分钟仍出现 capture 子进程重启导致的短期 stale 窗口，说明第一版还没有完全消除 RTSP/capture 层抖动。
- 但与 Phase 5.12 不同，capture 异常没有拖死主服务，Tracking/ResultPublisher 保持工作。

## 当前边界
- 第一版仍然使用 OpenCV，只是从主进程隔离到了 capture 子进程。
- JPEG pipe 会带来压缩/解码开销，并且当前输出为 720p、10fps，优先稳定而非高画质。
- 30 分钟长稳显示：隔离有效，但子进程内部 OpenCV 仍可能退出或超时。
- 后续可升级为 FFmpeg subprocess backend，进一步降低 OpenCV 子进程内部不稳定性。

## 是否建议 Phase 5 Runtime 封版
建议结论：

```text
Phase 5 AI pipeline 可以封版。
Phase 5 runtime 可以阶段性封版，但标注 capture isolation 第一版仍需后续 hardening。
```

理由：

- 主服务不再被 capture 直接拖死。
- `/status` 全程可访问。
- Tracking/ResultPublisher 均保持目标区间。
- 30 分钟内仍有 `frame_age_ms > 3000ms`，因此不应宣称 capture 层完全稳定。

## 下一阶段建议
1. Phase 5.13C：基于已补齐的子进程字段，再跑一次 30 分钟，确认 `capture_process_restart_count`、`last_exit_code`、`last_error` 的完整证据链。
2. 调整 subprocess reconnect 时间窗，降低重启恢复期间的 stale 时长。
3. 评估 `ffmpeg` subprocess backend，替换子进程内部 OpenCV read。
4. 在 capture 稳定性继续提升前，暂缓进入 GRU/LSTM 和正式告警链路。
