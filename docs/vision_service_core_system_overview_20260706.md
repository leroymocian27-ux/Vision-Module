# Vision Service 核心链路、逻辑与模型说明

更新时间：2026-07-06

本文档用于说明当前 Vision Service 的系统链路、核心逻辑、模型功能分工和整体设计思路。它面向项目负责人、联调人员和后续开发人员，重点回答四个问题：

1. 系统从摄像头到主系统告警的链路是什么？
2. 每个模型分别做什么？
3. 跌倒是如何被判定并推送给主系统的？
4. 当前架构的核心思路和后续优化方向是什么？

## 1. 当前运行配置

当前 Vision Service 是一个独立的实时视觉服务，运行在本机 `192.168.8.249:8000`，接入摄像头和主系统。

关键运行配置如下：

```text
Vision Service:
  http://192.168.8.249:8000

摄像头:
  rtsp://admin:***@192.168.8.250:10554/tcp/av0_0

主系统:
  http://192.168.8.248:8000/api/v1

主要模型:
  人体检测: yolov8n.pt
  跌倒提示检测: models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt
  姿态估计: yolo11n-pose.pt
  时序跌倒模型: models/fall_lstm_v5.onnx
```

当前启用能力：

```text
DETECTION_ENABLED=true
FALL_DETECTOR_ENABLED=true
ENABLE_TRACKING=true
ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=onnx_lstm
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_REPORT_DRY_RUN=false
```

## 2. 总体架构

系统整体采用“摄像头采集 + 多 worker 处理 + 最新结果仓库 + 结果融合发布”的结构。

核心链路：

```text
RTSP Camera
  -> Capture Worker
  -> FrameBuffer 最新帧缓存
  -> Person Detection Worker
  -> RealtimeResultStore.latest_detection
  -> Tracking Worker
  -> RealtimeResultStore.latest_tracking
  -> Pose Worker
  -> RealtimeResultStore.latest_pose
  -> Result Publisher Worker
  -> Temporal Model / Fall Fusion
  -> RealtimeResultStore.latest_published
  -> WebSocket / HTTP API / Main System Alert
```

其中 `RealtimeResultStore` 是系统内部的数据交换中心。它不保存完整长队列，而是保存每类处理结果的“最新快照”：

```text
latest_detection
latest_fall_detection
latest_tracking
latest_pose
latest_behavior
latest_published_result
```

这种设计适合实时系统：系统优先处理最新画面，而不是追求处理每一帧历史画面。

## 3. 摄像头采集链路

摄像头通过 RTSP 接入。采集模块负责从摄像头读取视频帧，并把最新帧写入 `FrameBuffer`。

当前采用单源模式：

```text
一个 RTSP 源同时服务：
  - 前端实时画面
  - 人体检测
  - 跌倒检测
  - 跟踪
  - 姿态估计
  - 告警截图
```

这样可以避免多个模块重复拉取 RTSP，降低摄像头和网络负担。

摄像头状态主要通过以下字段观察：

```text
connected: 是否连接
stream_state: connected / connecting / stale / reconnecting / disconnected
frame_age_ms: 最新帧年龄
capture_fps: 摄像头采集帧率
reconnect_count: 重连次数
capture_process_alive: 采集子进程是否存活
```

当前运行状态中，摄像头正常时通常表现为：

```text
connected=true
stream_state=connected
frame_age_ms < 200ms
capture_fps ≈ 10fps
```

## 4. 模型功能分工

当前系统并不是依赖单一跌倒模型，而是多模型、多证据融合。

### 4.1 人体检测模型

模型：

```text
yolov8n.pt
```

职责：

```text
输入: 摄像头帧
输出: person 框、置信度
```

作用：

1. 找到画面中的人。
2. 为跟踪模块提供基础检测框。
3. 为后续姿态、时序、跌倒融合提供目标对象。

人体检测是整条 AI 链路的基础。如果人体检测异常，后续 tracking、pose、temporal 都会受到影响。

### 4.2 跌倒提示检测模型

模型：

```text
models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt
```

职责：

```text
输入: 摄像头帧
输出: fall / falling / fallen / lying 等跌倒相关候选框
```

作用：

1. 给系统提供“画面中可能有跌倒姿态”的直接视觉证据。
2. 为融合逻辑提供强提示。
3. 在时序模型证据不足时，辅助触发候选跌倒状态。

它不单独决定最终告警，而是作为 `fall_hint` 参与融合。

### 4.3 跟踪模块

模块：

```text
ByteTrack-based tracking
```

职责：

```text
输入: person 检测框
输出: track_id、稳定跟踪目标
```

作用：

1. 给每个人分配稳定的 `track_id`。
2. 支撑时序窗口构建。
3. 避免每一帧都把同一个人当成新对象。
4. 支撑跌倒事件去重和 incident_id 生成。

当前 tracking worker 不只是被动等待新检测。当检测没有新帧时，它会短时间 hold/predict 已有目标，避免结果突然消失。

### 4.4 姿态估计模型

模型：

```text
yolo11n-pose.pt
```

Provider：

```text
yolo11_legacy
```

职责：

```text
输入: 跟踪目标及对应帧
输出: 关键点、骨架置信度、姿态质量
```

作用：

1. 判断人体姿态是否低姿态、横向、倒地。
2. 给时序特征提供 pose_available、pose_confidence、head/hip 高度比例等信息。
3. 辅助区分跌倒、蹲下、坐下、弯腰、躺卧等动作。

姿态不是强制依赖项。当前系统在 pose 缺失时仍可运行，只是融合证据会减少。

### 4.5 时序跌倒模型

模型：

```text
models/fall_lstm_v5.onnx
```

Provider：

```text
onnx_lstm
```

职责：

```text
输入: 连续多帧目标特征窗口
输出: fall_probability、window_ready、时序动作状态
```

使用的关键特征包括：

```text
bbox 中心点变化
bbox 宽高比
速度/位移
低姿态状态
姿态可用性
姿态置信度
头部/髋部高度比例
```

作用：

1. 识别连续动作变化，而不是只看单帧。
2. 减少单帧误检。
3. 支持慢跌倒、倒地后静止等场景。

当前时序窗口大小为：

```text
FEATURE_WINDOW_SIZE=32
TEMPORAL_MODEL_WINDOW_SIZE=32
```

### 4.6 跌倒融合模块

模块：

```text
FallFusionService
FallFeatureBuilder
FallStateMachine
ADLSuppressor
FallEvidenceScorer
```

职责：

```text
综合 person / tracking / fall_hint / pose / temporal / motion evidence
输出最终 fall_decision 和 alarm_preview
```

它解决的问题是：

1. 单一模型容易误判。
2. 单帧检测无法理解动作过程。
3. 日常动作如坐下、弯腰、蹲下、躺下容易与跌倒相似。
4. 需要区分“疑似跌倒”和“确认跌倒”。

## 5. 实时结果发布逻辑

`ResultPublisherService` 是最终结果组装和发布的核心模块。

它从 `RealtimeResultStore` 获取最新快照：

```text
latest_detection
latest_fall_detection
latest_tracking
latest_pose
latest_behavior
```

然后执行：

```text
1. 选择基础对象：优先 tracking，其次 detection
2. 合并 pose 结果
3. 合并 behavior 结果
4. 合并 fall hint 结果
5. 构建 fall feature
6. 调用 temporal service
7. 再次构建 fall feature
8. 调用 fall fusion
9. 生成 VisionResult
10. 写入 latest_published_result
11. 推送 WebSocket
12. 检查是否需要上报告警
```

最终发布对象是 `VisionResult`，主要被以下接口消费：

```text
GET /status
GET /integration/results/{camera_id}/latest
GET /integration/fall-alerts/{camera_id}/poll
WS  /ws/results?camera_id=camera_01
```

前端演示页通过：

```text
http://127.0.0.1:8000/demo
http://192.168.8.249:8000/demo
```

访问实时画面和算法结果。

## 6. 跌倒判定逻辑

当前系统不是简单地看到 `fallen` 就报警，而是分阶段确认。

### 6.1 候选阶段

系统可能进入候选跌倒的条件包括：

```text
fall hint 检测到跌倒相关框
目标 bbox 变矮或变横
目标中心点靠近画面下部
目标速度和姿态符合跌倒/倒地特征
时序模型 fall_probability 较高
```

候选阶段通常表现为：

```text
fall_state=fallen_candidate
risk_level=medium/high
alarm_confirmed=false
```

### 6.2 确认阶段

确认跌倒需要更多证据组合，例如：

```text
fall_hint 强阳性
tracking 稳定
temporal probability 达到阈值
低姿态持续
倒地后静止
pose 或 motion 支持
ADL 抑制分数未阻断
```

确认后结果通常表现为：

```text
fall_state=fallen_confirmed 或 confirmed_fall
risk_level=critical
alarm_confirmed=true
incident_id=vision-fall-...
snapshot_url=http://192.168.8.249:8000/fall-events/snapshots/...
```

### 6.3 ADL 抑制

ADL 指日常活动，例如：

```text
坐下
蹲下
弯腰
正常躺卧
受控下降
```

这些动作可能与跌倒相似，所以系统会计算 ADL suppression score。

如果更像日常动作，系统会抑制告警：

```text
fall_state=suppressed
alarm_confirmed=false
suppressed_reason=...
```

### 6.4 事件去重

确认跌倒后，系统会生成 `incident_id`。它通常包含：

```text
camera_id
track_id
timestamp
```

示例：

```text
vision-fall-camera_01_track_29-20260706065211642379
```

去重逻辑用于避免同一次跌倒在短时间内反复弹窗。

## 7. 主系统告警闭环

当前 Vision Service 会把确认跌倒事件推送到主系统：

```text
POST http://192.168.8.248:8000/api/v1/video-bridge/fall-events
```

推送 payload 包含：

```text
camera_id
event_type=fall_confirmed
state=confirmed_fall
risk_level
fall_prob
track_id
incident_id
bbox
snapshot_url
timestamp
injury advice
metadata
```

主系统收到后创建告警，并触发前端弹窗。

Vision 侧还提供轮询接口：

```text
GET /integration/fall-alerts/camera_01/poll
```

该接口用于前端或主系统判断当前是否应该弹窗。

## 8. 当前链路中的串联点

虽然系统已经有多个 worker，但当前仍存在几个重要串联点。

### 8.1 Person YOLO 与 Fall YOLO 串联

当前 `DetectionService` 内部是：

```text
取最新帧
  -> person detector
  -> update latest_detection
  -> fall detector
  -> update latest_fall_detection
```

问题：

```text
fall detector 如果变慢，会拖慢下一轮 person detector。
```

### 8.2 多个 Ultralytics 模型共享推理锁

当前为了避免 Ultralytics/GPU 并发问题，fall detector 和 pose detector 使用共享推理锁。

优点：

```text
降低模型并发崩溃风险
```

缺点：

```text
fall / pose / person 之间可能互相等待
某个模型慢会影响其他模型调度
```

### 8.3 Result Publisher 同时承担融合和告警检查

当前 result publisher 不只是发布结果，还执行 temporal、fusion、reporter inspect。

问题：

```text
如果 temporal/fusion/reporter 变慢，最终 published result 会延迟。
```

## 9. 当前核心设计思路

当前系统的核心思路可以总结为：

```text
实时画面优先
单 RTSP 源避免重复拉流
多模型提供不同证据
最新快照而非完整帧队列
tracking 维持目标连续性
temporal 负责动作过程理解
fusion 负责最终跌倒决策
reporter 负责主系统告警闭环
```

更具体地说：

1. 摄像头采集必须稳定，不能被模型推理拖死。
2. person detection 是基础目标入口。
3. tracking 把单帧检测变成连续对象。
4. pose 和 fall hint 是增强证据。
5. temporal 模型理解连续动作。
6. fusion 统一判断跌倒、抑制日常动作误报。
7. confirmed fall 才进入主系统告警。

## 10. 建议的后续架构优化方向

领导提出的“多个模型串联导致一个模型卡顿拖慢整体”是当前系统下一阶段最需要解决的问题。

建议目标架构：

```text
FrameBuffer
  -> PersonDetectorWorker
  -> FallHintWorker
  -> TrackingWorker
  -> PoseWorker
  -> TemporalWorker
  -> FusionWorker
  -> PublisherWorker
```

核心原则：

```text
每个模型独立 worker
每个 worker 只处理最新帧
队列长度固定为 1
过期结果直接丢弃
模型超时自动降级
融合逻辑不等待所有模型齐全
```

第一优先级改造：

```text
把 fall detector 从 DetectionService 拆成独立 FallHintWorkerService
```

改造前：

```text
person YOLO -> fall YOLO -> result
```

改造后：

```text
person YOLO -> latest_detection
fall YOLO   -> latest_fall_detection
publisher   -> 按 TTL 合并两者
```

这样即使跌倒提示模型卡顿，人体检测、跟踪、基础状态和实时画面仍能正常刷新。

第二优先级改造：

```text
给每个模型结果增加 TTL 和健康状态
```

建议 TTL：

```text
person detection: 800ms
fall hint: 1500ms
pose: 800ms
temporal: 2000ms
```

状态示例：

```text
person_detector: ok / stale / slow / error
fall_hint: ok / stale / slow / error
pose: ok / stale / slow / error
temporal: ok / stale / slow / error
fusion: normal / degraded
```

第三优先级改造：

```text
模型级 circuit breaker
```

规则示例：

```text
连续 3 次超时 -> 暂停该模型 10 秒
暂停期间 fusion 使用降级逻辑
冷却后自动恢复
```

## 11. 一句话总结

当前系统已经具备实时视觉服务的核心能力：摄像头采集、人体检测、跌倒提示、跟踪、姿态、时序模型、融合判定和主系统告警闭环。

当前最大架构风险是：部分模型仍在局部串联链路和共享推理锁下运行，一个模型变慢时可能拖慢 AI 结果刷新。

后续优化的主线应是：

```text
从“串联推理链路”升级为“可降级的异步多模型融合链路”。
```

