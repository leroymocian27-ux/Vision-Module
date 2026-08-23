# 姿态检测接入后效果不佳的问题分析

生成日期：2026-07-05  
工作区：`D:\Program\vision_service`

## 结论摘要

当前系统中姿态检测效果不佳，不应简单归因为“姿态模型不够好”。更准确的判断是：

```text
姿态模型本身有质量边界；
姿态服务运行时有效率偏低；
姿态结果与 detection/tracking 同步和绑定不稳定；
LSTM 训练数据实际上没有姿态特征；
最终 Fusion/状态机对姿态证据的使用不够闭环；
前端展示又会放大 stale/mismatch 带来的观感问题。
```

一句话：现在的问题不是“换一个 pose 权重就好”，而是“姿态作为证据源没有稳定、完整、同分布地进入整条跌倒判断链路”。

## 当前运行现状

当前 `.env`：

```env
ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
POSE_FPS=3
YOLO11_POSE_MODEL_PATH=models/pose_yolo_batch001_003_yolo11s_best.pt
YOLO_POSE_DEVICE=cuda:0
POSE_WORKER_FPS=2
POSE_RESULT_TTL_MS=500
POSE_MAX_TRACKING_FRAME_DELTA=2
POSE_MAX_FRAME_AGE_MS=500
POSE_SKIP_WHEN_INFERENCE_BUSY=true
```

核心事实：

- 当前使用 `yolo11_legacy` provider。
- 当前权重是 `models/pose_yolo_batch001_003_yolo11s_best.pt`。
- `yolo11_legacy` 是全帧 pose，再把 pose candidate 匹配回 track。
- 姿态 worker 每秒最多跑约 2 次，pose 结果 TTL 只有 500ms。
- 如果推理锁忙，会跳过本轮姿态。
- 如果 detection frame 和 tracking frame 差超过 2 帧，或 frame 年龄超过 500ms，直接拒绝姿态。

这些设计不是错，但它们会让姿态在实际系统里变得很脆：只要检测、跟踪、GPU 推理、帧缓存任一环节抖动，姿态就会缺席。

## 证据 1：端到端验收中姿态有效率很低

`evaluations/phase9_e2e_acceptance_001.json`：

```text
pose_valid = 0.3
pose_fps = 0.67
last_inference_latency_ms = 31.0
skipped_due_to_busy = 137
```

解读：

- 30% 的姿态有效率意味着大多数时刻姿态没有成为可靠证据。
- 单次推理延迟 31ms 并不差，但系统实际 pose_fps 只有 0.67。
- `skipped_due_to_busy=137` 是非常关键的信号：姿态不是一直“识别错”，而是经常根本没跑、没更新、没进入结果。

这说明主要矛盾之一在运行调度和资源争用，不只是模型权重。

## 证据 2：当前 LSTM 训练数据没有姿态特征

对 `data/temporal_sequences_phase6d` 重新统计：

```text
jsonl files = 167
rows = 6659
pose field rows = 0
pose_available true = 0
pose_available ratio = 0.0
```

但 LSTM 的输入 schema 明明包含 5 个姿态维度：

```text
pose_available
pose_confidence
torso_angle_norm
head_height_ratio_filled
hip_height_ratio_filled
```

这意味着：

- 训练时模型没有真正学会使用姿态区分坐下、弯腰、蹲跪、躺卧、跌倒。
- 线上接入姿态后，输入分布可能和训练时不同。
- 如果线上姿态经常缺失，LSTM 实际上仍接近 bbox + motion 模型。
- 如果线上偶尔有姿态，模型也未必知道如何稳定利用，因为训练阶段没吃过这样的有效姿态信号。

这是当前“接入姿态但效果不佳”的核心原因之一。

## 证据 3：当前姿态模型并非全面优于基线

`models/pose_yolo_batch001_003_yolo11s_metrics.json`：

| 指标 | 基线 `yolo11n-pose.pt` | 当前模型 | 差值 |
|---|---:|---:|---:|
| pose mAP50 | 0.980476 | 0.995 | +0.014524 |
| pose mAP50-95 | 0.883491 | 0.848643 | -0.034848 |
| inference | 16.36ms | 11.75ms | 更快 |

当前模型优点：

- 更快。
- bbox 指标更好。
- 粗粒度 pose mAP50 更好。
- link-match 小测试集上绑定表现不错。

当前模型问题：

- 细粒度关键点质量 `pose mAP50-95` 低于基线。
- 评估集规模很小，link-match 只有 40 张图。
- 对真实线上问题，如多人遮挡、边缘半身、老人低姿态、小目标、坐姿/蹲跪/躺卧，没有足够强的证明。

所以当前权重不是垃圾，但也不是救命稻草。它最多是一个“速度不错、局部适配还行、细粒度点位有损失”的模型。

## 证据 4：历史问题已经指向 stale/mismatch/offset

历史 handoff 文档记录过这些问题：

- bbox 正常但骨架偏移。
- stale pose reuse。
- pose 绑定到错误 `track_id`。
- full-frame pose candidate matching 比 target-only crop pose 观感更差。
- 低置信度腿部点和边缘点污染 `pose_bounds`。

当前 provider 是 `yolo11_legacy`，它采用全帧 pose + candidate-to-track matching。这个方案理论上能支持多人，但它对 track、bbox、候选匹配特别敏感。

如果现场是单目标、目标人物明确，历史上更稳定的方向可能是：

```text
target-only ROI crop pose
per-track smoothing
低置信度腿部点过滤
边缘点过滤
严格 frame freshness
```

当前全帧匹配方案一旦遇到多人、遮挡、近距离肢体交错，骨架错绑概率会上升。

## 根因分析

### 1. 模型层：当前姿态权重解决了部分问题，但不是高质量通用姿态模型

当前模型训练目标更偏项目数据，速度也更好，但细粒度关键点指标低于基线。系统需要的不是“能输出 17 个点”，而是：

- 坐姿时肩髋位置不能乱。
- 蹲跪时髋膝踝不能胡乱补点。
- 躺卧时头髋高度比例要稳定。
- 半身出画时不能把缺失点当真实点。
- 多人重叠时不能错绑骨架。

这些正是当前测试集覆盖不足的地方。

### 2. Provider 层：`yolo11_legacy` 全帧匹配对 track 质量高度敏感

`yolo11_legacy` 工作方式：

```text
整帧 YOLO pose
收集多个 pose candidate
按 IoU、中心距离、关键点落框比例、躯干是否在框内匹配 track
通过阈值后挂到 track
```

问题：

- 如果 person bbox 偏，pose 可能被拒绝。
- 如果 track ID 切换，pose 平滑历史会断。
- 如果多人靠近，candidate 可能匹配错。
- 如果低姿态人体 bbox 本身不准，关键点落框比例会失真。
- 如果目标很小，pose candidate 的关键点置信度和位置更不稳。

这类问题不是简单调 `YOLO11_POSE_CONF` 就能解决。

### 3. 调度层：姿态服务在系统里经常缺席

当前姿态 worker：

```text
POSE_WORKER_FPS=2
POSE_FPS=3
POSE_RESULT_TTL_MS=500
POSE_SKIP_WHEN_INFERENCE_BUSY=true
```

这组参数组合比较尴尬：

- worker 只有 2 FPS，理论上 500ms 一次。
- TTL 也是 500ms，刚好等于 worker 间隔。
- 只要某次跳过、某次推理慢、某次帧不同步，前端和下游就可能立刻认为姿态过期。
- 检测和 fall detector 也在抢 YOLO/Ultralytics 推理锁，busy skip 会快速累积。

所以用户看到的效果可能是：

```text
骨架一卡一卡
骨架突然消失
骨架跟不上框
有时有 pose，有时没有 pose
LSTM/fusion 多数帧吃不到 pose
```

这不是模型单帧能力低，而是“姿态证据供应链断断续续”。

### 4. 数据层：训练和线上不一致

当前 LSTM 训练序列中姿态特征为 0。线上却接入了姿态模型。

这会造成两种坏情况：

1. 线上姿态多数时候也缺失  
   那 LSTM 仍然靠 bbox/motion 判断，坐姿、蹲跪、躺卧误报不会明显下降。

2. 线上姿态偶尔有效  
   模型训练时没学过有效姿态模式，未必能正确使用这些维度。

因此，“接入姿态模型”并不等于“时序模型已经具备姿态理解能力”。当前更像是把姿态字段接到了系统里，但训练闭环没补上。

### 5. 融合层：姿态是证据之一，不是最终裁判

Fusion 使用姿态的主要方式：

- `pose_available`
- `pose_confidence`
- `low_posture`
- `head_height_ratio`
- `hip_height_ratio`
- `torso_angle`
- evidence_sources 是否包含 `pose`

如果姿态不可用，系统会退回 bbox 低姿态：

```text
aspect_ratio >= 0.95
```

这会带来误报风险。坐着、躺着休息、弯腰、蹲跪，在 bbox 上都可能像低姿态。如果姿态缺席，系统少了区分 ADL 的关键证据；如果姿态错误，又会给错误低姿态背书。

### 6. 前端层：可视化会放大姿态不稳定

前端 overlay 会检查：

- pose 是否过期；
- pose frame 和当前 result frame 是否对齐；
- pose track 是否等于 object track；
- pose source bbox 和 object bbox 是否漂移；
- keypoint confidence 是否足够。

因此用户看到“姿态效果不好”，可能包含几类不同问题：

- 后端没输出姿态。
- 后端输出了但前端判定 stale。
- 后端输出了但 track 不匹配。
- 骨架点确实偏。
- 骨架点对，但 bbox/画布映射不一致。

需要把这些拆开，否则容易误把所有问题都归咎于模型。

## 问题优先级

### P0：姿态有效率低

这是最先要解决的。单帧模型质量再好，如果只有少数帧有效，系统效果一定差。

需要统计：

```text
pose_attempt_count
pose_success_count
pose_valid_ratio
skip_due_to_busy_count
no_tracking_count
frame_tracking_desync_count
pose_frame_stale_count
pose_track_match_low_score_count
no_keypoints_count
```

### P0：LSTM 训练数据没有姿态特征

这是“接入姿态但最终判断没改善”的核心解释。

需要重新导出带姿态的 temporal sequences，并重训/校准 LSTM。

### P1：全帧匹配 provider 对现场不一定最优

历史记录显示 target-only crop pose 观感可能更好。当前 `yolo11_legacy` 为多人全帧匹配方案，现场如果主要关注目标老人，可能应该重新 A/B：

```text
yolo11_legacy full-frame
yolo crop provider
branch4_legacy target crop
rtmpose_onnx top-down
```

不要只比较 keypoint mAP，要比较：

```text
pose_valid_ratio
pose_track_mismatch_count
keypoint_inside_bbox_ratio
torso_inside_bbox_rate
frontend_visible_skeleton_ratio
false alarm impact
```

### P1：配置不够清晰

当前 `.env` 显式写了 `YOLO_POSE_*`，但 provider 是 `yolo11_legacy`，实际关键配置是 `YOLO11_POSE_*`。默认值在代码里，不在 `.env` 里，工作人员容易调错参数。

应显式写入：

```env
YOLO11_POSE_CONF=0.12
YOLO11_POSE_IMGSZ=640
YOLO11_POSE_DEVICE=cuda:0
YOLO11_POSE_HALF=true
YOLO11_POSE_SMOOTHING=true
YOLO11_POSE_MAX_JUMP_RATIO=0.18
YOLO11_POSE_MIN_MATCH_IOU=0.12
YOLO11_POSE_MAX_CENTER_DISTANCE_RATIO=0.65
YOLO11_POSE_MATCH_SCORE_THRESHOLD=0.30
```

### P2：模型数据集覆盖不足

当前 pose 数据集指标看起来可用，但覆盖不足：

- 真实老人低姿态；
- 半身出画；
- 小目标；
- 多人遮挡；
- 靠床/靠椅；
- 夜间或弱光；
- 坐姿侧身；
- 蹲跪；
- 弯腰捡东西；
- 倒地后肢体部分遮挡。

这些才是系统现场最痛的样本。

## 推荐诊断步骤

### 第一步：先把姿态有效率量化

不要先重训。先跑 5-10 分钟当前摄像头或固定回放，输出：

```text
总帧数
有 tracking 的帧数
pose worker tick 数
pose 推理尝试数
pose 成功挂载数
pose 被拒绝原因分布
pose 前端可见比例
pose 进入 temporal 的比例
pose 进入 fusion evidence_sources 的比例
```

如果 pose 成功率低于 70%，先修调度和同步。

### 第二步：把 busy skip 降下来

可尝试：

- 降低检测/跌倒提示推理频率，释放 Ultralytics lock。
- 把 `POSE_WORKER_FPS` 和 TTL 配平，例如 worker 3 FPS、TTL 800-1000ms。
- 检查检测、fall detector、pose 是否共用同一 GPU 且互相阻塞。
- 对 pose 推理做队列合并，永远只处理最新帧。

目标不是盲目提高 pose FPS，而是减少“刚输出就过期”和“长期被 busy 跳过”。

### 第三步：确认 provider 是否适合现场

用同一批视频回放 A/B：

| Provider | 关注点 |
|---|---|
| `yolo11_legacy` | 全帧多人匹配，当前方案 |
| `yolo` | 目标框 crop，可能减少错绑 |
| `branch4_legacy` | 历史上 target-only crop 观感更好 |
| `rtmpose_onnx` | top-down 质量候选，但延迟高 |

必须输出：

```text
pose_valid_ratio
pose_latency_ms
rejected_reason_distribution
track_mismatch_rate
mean_keypoint_inside_bbox_ratio
mean_skeleton_confidence
impact_on_fall_false_positive
impact_on_fall_miss
```

### 第四步：重新导出带姿态的 LSTM 训练序列

当前 LSTM 训练数据没有姿态，必须补。

要求：

- 对同一批 fall/ADL 视频跑当前 pose provider。
- 导出 `pose_available`、`pose_confidence`、`torso_angle`、`head_height_ratio`、`hip_height_ratio`。
- 保留 rejected reason 和 pose quality 字段，便于分析。
- 重新训练 LSTM。
- 做阈值校准和固定回放集评估。

### 第五步：建立 pose hard set

从现场收集这些帧：

- 骨架明显偏移。
- 骨架挂到错误人。
- 坐姿被认为低姿态。
- 蹲跪腿部点错误。
- 躺卧头髋点错误。
- 画面边缘半身人体。
- 多人遮挡。
- 小目标。

每帧要记录：

```text
image
person bbox
correct keypoints
current model keypoints
track_id
rejected_reason
是否影响告警
```

只收“好看”的姿态样本没用，要收最难、最脏、最影响告警的样本。

## 短期修复建议

不改模型权重，先做这些：

1. 显式补齐 `YOLO11_POSE_*` 配置，避免调错 provider 参数。
2. 把 `POSE_RESULT_TTL_MS` 从 500 提高到 800-1000 做对比测试。
3. 将 `POSE_WORKER_FPS` 从 2 调到 3 做压测，但必须观察 busy skip 是否上升。
4. 在状态接口增加或导出 `rejected_reason` 计数分布。
5. 在最终结果里记录 `pose_entered_temporal`、`pose_entered_fusion`。
6. 对 pose 不可用时的 confirmed fall 提高门槛，防止 bbox-only 低姿态过度确认。

## 中期修复建议

1. 做 provider A/B 回放，不要凭视觉印象选 provider。
2. 重新导出带姿态的 LSTM 训练集。
3. 重训 LSTM，并比较 bbox-only 与 bbox+pose 两套模型。
4. 建立姿态 hard set，重点补 ADL 和失败帧。
5. 清理 RTMPose ONNX 路径，将 zip 内模型解压到可运行路径后再测试。
6. 把前端 overlay 的拒绝原因可视化，区分“没姿态”“姿态过期”“姿态错绑”“姿态低质量”。

## 最可能的原因排序

1. **姿态有效率低**：busy skip、worker FPS、TTL、frame stale/desync 导致姿态经常缺席。
2. **训练闭环缺失**：LSTM 训练数据没有姿态特征，导致最终判断不会稳定受益于 pose。
3. **provider 不适配现场**：当前全帧匹配方案可能不如 target-only crop 稳。
4. **测试集太小**：当前 pose 指标无法覆盖现场脏场景。
5. **配置误导**：工作人员可能调整了 `YOLO_POSE_*`，但当前 provider 走的是 `YOLO11_POSE_*`。
6. **模型细粒度关键点质量有限**：当前模型 `pose mAP50-95` 低于基线。

## 最终判断

当前姿态检测接入系统后效果不佳，是一个系统工程问题，不是单点模型问题。真正要解决，必须按下面顺序：

```text
先量化姿态有效率
再修调度和同步
再 A/B provider
再导出带姿态的时序训练集
再重训/校准 LSTM
最后补 pose hard set 和重训 pose
```

如果跳过前四步直接重训姿态模型，很可能会得到一个离线指标更漂亮、线上效果仍然不稳定的新权重。

## 参考文件

- `.env`
- `app/services/pose_service.py`
- `app/services/pose_worker_service.py`
- `app/pose/yolo11_legacy_pose_estimator.py`
- `app/pose/yolo_pose_estimator.py`
- `app/temporal/target_feature_extractor.py`
- `app/temporal/feature_vectorizer.py`
- `app/fall/feature_builder.py`
- `app/fall/fusion.py`
- `models/pose_yolo_batch001_003_yolo11s_metrics.json`
- `models/pose_yolo_batch001_003_yolo11s_link_match_metrics.json`
- `evaluations/phase9_e2e_acceptance_001.json`
- `evaluations/phase10_pose_provider_comparison_001.json`
- `docs/current_model_training_failure_analysis_20260704.md`
