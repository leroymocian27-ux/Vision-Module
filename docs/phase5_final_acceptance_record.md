# Phase 5 Final Acceptance Record

## 1. Phase 5 总体目标
Phase 5 的目标是完成规则版跌倒判定闭环，并把它接入当前实时视觉系统中，作为本地 preview 能力，而不是正式告警系统。

本阶段已经完成：

- 规则版 Temporal Decision Layer。
- 前端 Fall Preview 展示。
- 公开数据集规则验收。
- Identity Binding 异步化，解除 TrackingWorker 热路径阻塞。
- Capture Isolation 第一版，使用 `subprocess_opencv` 隔离 RTSP/OpenCV capture 风险。

## 2. 当前系统能力
当前系统链路：

```text
RTSP
-> subprocess_opencv capture child process
-> FrameBuffer latest-frame
-> YOLO detect
-> TrackingWorker
-> Async IdentityBindingWorker
-> YOLO-Pose
-> Behavior
-> Temporal rule preview
-> ResultPublisher
-> WebRTC + WebSocket frontend demo
```

当前具备能力：

- 真实 RTSP 摄像头输入。
- Capture 子进程隔离，主进程不直接承受 OpenCV `cap.read()` 长阻塞。
- `FrameBuffer(maxsize=1)` latest-frame 语义。
- YOLO person detection。
- TrackingWorker 高频目标状态输出。
- IdentityBindingWorker 异步低频身份绑定。
- YOLO-Pose 目标骨架点输出。
- Behavior 解释层：`standing / walking / sitting / bending / lying / unknown`。
- Temporal rule preview：`normal / unstable / falling / fallen_candidate / fallen_confirmed / cooldown`。
- ResultPublisher 合并 tracking、identity、pose、behavior、temporal 后发布 WebSocket。
- `/demo` 前端展示实时视频、目标框、骨架、身份、行为、fall preview。

## 3. 当前明确没有进入
Phase 5 当前没有进入以下能力：

- GRU/LSTM。
- 训练模型。
- 正式告警。
- POST 主后端。
- snapshot。
- retry queue。
- 移动端推送或业务闭环通知。

当前 `alarm_preview` 仅是本地预览字段，不代表正式告警。

## 4. 数据集验收结果
引用 Phase 5.8 规则版数据集验收结果：

```text
ADL videos: 11
Fall videos: 7

ADL unstable: 0/11
ADL falling FP: 0
ADL candidate FP: 0
ADL confirmed FP: 0

Fall falling recall: 5/7
Fall candidate recall: 0/7
Fall confirmed recall: 0/7
```

结论：

- 正常动作高等级误报目前压住了。
- 规则版整体偏保守。
- `falling` preview 有一定召回，但 `candidate/confirmed` 暂未优化召回。
- 当前规则适合作为 preview，不适合作为最终正式告警依据。

## 5. Runtime 关键修复
### Identity Async
Phase 5.10 修复 IdentityBindingService 同步阻塞 TrackingWorker 的问题。

修复前：

```text
full tracking_worker_fps ≈ 1.82
```

修复后：

```text
full tracking_worker_fps ≈ 10.56
identity-timeout tracking_worker_fps ≈ 10.63
```

结论：IdentityBinding 已从 TrackingWorker 热路径拆出，identity service 超时或不可达不再拖慢 tracking。

### Capture Isolation
Phase 5.12 证明主进程内 OpenCV capture 存在长阻塞风险：

```text
Phase 5.12 max_frame_age_ms: 23641ms
```

Phase 5.13 引入 `subprocess_opencv`，将 OpenCV capture 隔离到子进程。

阶段对比：

```text
Phase 5.12 max_frame_age_ms: 23641ms
Phase 5.13B max_frame_age_ms: 14172ms
Phase 5.13C max_frame_age_ms: 5266ms

Phase 5.13B frame_age > 3000ms: 23
Phase 5.13C frame_age > 3000ms: 1

Phase 5.13B connected_ratio: 97.72%
Phase 5.13C connected_ratio: 99.48%
```

结论：capture isolation 有效，主服务不再被 OpenCV `cap.read()` 直接拖死；Phase 5.13C 调参后恢复窗口明显压缩。

## 6. 当前推荐运行配置
比赛/测试阶段推荐配置：

```text
CAPTURE_BACKEND=subprocess_opencv
CAPTURE_PROCESS_FRAME_TIMEOUT_MS=2000
CAPTURE_PROCESS_RESTART_MS=500
CAPTURE_JPEG_QUALITY=60
CAPTURE_PROCESS_OUTPUT_HEIGHT=720
CAPTURE_PROCESS_WRITE_FPS=10
CAPTURE_PROCESS_MAX_RESTARTS=0

ENABLE_TRACKING=true
ENABLE_IDENTITY_BINDING=true
IDENTITY_BINDING_ASYNC=true
IDENTITY_SERVICE_URL=http://127.0.0.1:8100
IDENTITY_REQUEST_TIMEOUT_MS=1000

ENABLE_POSE=true
POSE_PROVIDER=yolo
ENABLE_BEHAVIOR=true
ENABLE_TEMPORAL=true

TRACKING_WORKER_FPS=12
POSE_WORKER_FPS=2
RESULT_PUBLISH_FPS=10
```

说明：`CAPTURE_PROCESS_MAX_RESTARTS=0` 表示 unlimited。

## 7. 当前边界
当前系统仍有以下边界：

- `subprocess_opencv` 仍然使用 OpenCV，只是隔离到了子进程。
- capture 子进程异常退出或重启后，仍可能出现几秒连接窗口。
- 当前 capture 输出为 720p、JPEG quality 60、10fps，优先稳定而非画质。
- Temporal 仍是规则 preview，不是最终智能模型。
- `fallen_candidate / fallen_confirmed` 仍偏保守。
- 公开数据集规模仍小，不能作为正式算法泛化能力证明。
- Identity service 当前仍可能 fallback CPU，但已经不在 tracking 热路径。

## 8. 封版结论
Phase 5 封版建议：

```text
Phase 5 AI pipeline 可以封版。
Phase 5 runtime 可以阶段性封版。
当前比赛/测试建议使用 CAPTURE_BACKEND=subprocess_opencv。
```

暂不进入 `ffmpeg subprocess` backend，除非后续真实演示仍出现不可接受 stale，或需要更强的 RTSP low-latency/reconnect 可控性。

当前版本适合作为：

- 比赛演示版本。
- 真人测试版本。
- Phase 6 GRU/LSTM 前的数据采集和误报/漏报记录版本。

当前版本不应作为：

- 正式医疗/养老告警系统。
- 无人工复核的正式跌倒检测闭环。

## 9. 下一阶段建议
建议下一阶段顺序：

1. 真人动作验收。
2. 继续扩充 ADL/fall 样本。
3. 记录误报/漏报样本与对应状态流。
4. 在数据和 runtime 稳定后进入 Phase 6 GRU/LSTM。
5. 正式告警、POST 主后端、snapshot、retry queue 放在模型和 runtime 稳定之后。

Phase 6 前建议保留当前规则版 preview 作为 baseline，对比 GRU/LSTM 是否真正带来收益。
