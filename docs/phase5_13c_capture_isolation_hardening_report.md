# Phase 5.13C Capture Isolation Hardening 二轮验证与调参

## 目标
本阶段只处理 capture subprocess 诊断补齐与恢复窗口压缩，不修改 AI pipeline、Temporal、前端、RTSP/WebRTC 主接口、告警、POST、snapshot 或 GRU/LSTM。

## 基线：Phase 5.13B
`subprocess_opencv` 第一版已经证明主服务不再被 capture 拖死，但 30 分钟长稳仍出现恢复窗口：

```text
connected_ratio: 97.72%
max_frame_age_ms: 14172ms
frame_age > 3000ms: 23
reconnect_delta: 6
tracking_worker_fps avg: 10.65
result_publish_fps avg: 9.13
pipeline_errors: 0
temporal_errors: 0
```

## 本轮诊断补齐
已补齐长稳采样脚本字段：

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

对应脚本：`scripts/debug_phase5_12_long_run.py`

## 调参前 30 分钟验证
结果文件：`logs/runtime_debug/phase5_13c_before_tuning_30min.json`

核心指标：

```text
sample_count: 1491
status_failures: 0
connected_ratio: 99.60%
max_frame_age_ms: 6594ms
avg_frame_age_ms: 74.09ms
frame_age > 3000ms: 4
avg_capture_fps: 9.07
reconnect_delta: 2
capture_process_restart_delta: 2
capture_ipc_decode_error_delta: 0
max_capture_process_last_frame_age_ms: 3156ms
tracking_worker_fps avg/min: 10.72 / 9.14
result_publish_fps avg/min: 9.19 / 7.92
pipeline_errors: 0
temporal_errors: 0
```

### 峰值原因定位
调参前最大 stale 窗口：

```text
max_frame_age_ms: 6594ms
reconnect_reason: capture_process_frame_timeout
capture_process_last_frame_age_ms: 3156ms
capture_process_last_exit_code: 1
capture_process_last_error: capture process stream closed
```

原因判断：

```text
子进程活着但停止吐包
-> watchdog 在 3000ms 后触发 frame_timeout
-> 再叠加 CAPTURE_PROCESS_RESTART_MS=3000
-> 新子进程首帧到达前，FrameBuffer 继续变旧
```

这说明 14s/6s stale 的主要放大因素不是 AI pipeline，也不是 pipe/JPEG decode，而是 timeout + restart delay + 新进程首帧等待。

## 修改内容
只调整 capture 恢复路径：

```text
CAPTURE_PROCESS_FRAME_TIMEOUT_MS: 3000 -> 2000
CAPTURE_PROCESS_RESTART_MS: 3000 -> 500
```

同时修正：

```text
重启新 child 时清空旧 capture_process_last_frame_age_ms
reader EOF 不再覆盖 child stderr 中更有价值的 last_error
```

修改文件：

```text
app/core/config.py
app/camera/subprocess_capture_worker.py
.env.example
scripts/debug_phase5_12_long_run.py
scripts/debug_start_phase513c.py
```

## 调参后 30 分钟验证
结果文件：`logs/runtime_debug/phase5_13c_after_tuning_30min.json`

配置：

```text
CAPTURE_BACKEND=subprocess_opencv
CAPTURE_PROCESS_FRAME_TIMEOUT_MS=2000
CAPTURE_PROCESS_RESTART_MS=500
CAPTURE_JPEG_QUALITY=60
CAPTURE_PROCESS_OUTPUT_HEIGHT=720
CAPTURE_PROCESS_WRITE_FPS=10
真实 RTSP
全功能开启：Tracking + Identity async + Pose + Behavior + Temporal
```

核心指标：

```text
sample_count: 1532
status_failures: 0
connected_ratio: 99.48%
max_frame_age_ms: 5266ms
avg_frame_age_ms: 69.72ms
frame_age > 3000ms: 1
avg_capture_fps: 8.96
reconnect_delta: 4
capture_process_restart_delta: 4
capture_ipc_decode_error_delta: 0
capture_ipc_dropped_frame_delta: 37164
max_capture_process_last_frame_age_ms: 953ms
tracking_worker_fps avg/min: 10.65 / 7.37
result_publish_fps avg/min: 9.14 / 6.78
pipeline_errors: 0
temporal_errors: 0
GPU avg: 4.04%
```

## 调参前后对比
| 指标 | 调参前 | 调参后 |
| --- | ---: | ---: |
| `connected_ratio` | `99.60%` | `99.48%` |
| `max_frame_age_ms` | `6594ms` | `5266ms` |
| `frame_age > 3000ms` | `4` | `1` |
| `avg_frame_age_ms` | `74.09ms` | `69.72ms` |
| `reconnect_delta` | `2` | `4` |
| `capture_process_restart_delta` | `2` | `4` |
| `max_capture_process_last_frame_age_ms` | `3156ms` | `953ms` |
| `tracking_worker_fps avg` | `10.72` | `10.65` |
| `result_publish_fps avg` | `9.19` | `9.14` |
| `pipeline_errors` | `0` | `0` |
| `temporal_errors` | `0` | `0` |

解读：

- 更短 timeout/restart 让恢复窗口明显压缩。
- 子进程重启次数从 2 增到 4，说明更积极地切换失败 capture。
- `frame_age > 3000ms` 从 4 降到 1，恢复质量提升。
- AI pipeline 没有被拖慢。

## 剩余 stale 峰值原因
调参后唯一 `frame_age > 3000ms` 的样本：

```text
frame_age_ms: 5266ms
stream_state: connecting
capture_process_alive: true
capture_process_pid: 33904
capture_process_restart_count: 1
capture_process_last_frame_age_ms: null
reconnect_reason: null
```

原因判断：

```text
旧 child 已退出/被重启
新 child 已启动
但新 child 首帧尚未到达 parent reader
因此 capture_process_last_frame_age_ms 为 null
FrameBuffer 仍显示旧帧 age，直到新首帧写入
```

排除项：

```text
不是 parent 没及时 kill：重启已经发生
不是 pipe reader 卡死：后续正常恢复
不是 JPEG decode 卡死：decode_errors=0
不是 AI pipeline 阻塞：tracking/result publish 均持续运行
```

## 是否继续 subprocess_opencv
建议继续使用 `subprocess_opencv` 作为当前比赛/演示阶段默认测试 backend。

理由：

```text
主服务稳定
/status 全程可访问
tracking/result publish 保持目标区间
capture 抖动已被隔离为子进程级恢复窗口
调参后 stale 明显减少
```

## 是否需要进入 ffmpeg subprocess backend
建议：暂不立刻切换，但应列为下一阶段增强项。

进入 ffmpeg backend 的触发条件：

```text
真实演示仍不能接受 5s 级偶发 stale
或 30min/60min 长稳仍反复出现 capture_process_read_failed / H264 decode error
或需要更可控的 RTSP reconnect / low-latency 参数
```

当前 `subprocess_opencv` 已经足以支撑 Phase 5 runtime 阶段性封版；如果要追求更强生产级稳定性，下一阶段再实现 `ffmpeg subprocess`。

## 结论
Phase 5.13C 达成目标：

```text
max_frame_age_ms: 14172ms -> 6594ms -> 5266ms
frame_age > 3000ms: 23 -> 4 -> 1
AI pipeline errors: 0
Temporal errors: 0
Tracking avg: ~10.65fps
Result publish avg: ~9.14fps
```

Capture isolation 继续有效，且恢复窗口已被明显压缩。
