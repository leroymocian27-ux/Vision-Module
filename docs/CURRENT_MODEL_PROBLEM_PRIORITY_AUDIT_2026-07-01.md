# 当前模型问题优先级审计清单（2026-07-01）

这份文档只讲当前系统真实问题，不给模型滤镜，也不把“训练过”包装成“已经可靠”。结论先放前面：现在效果达不到预期，不是因为少按了某个神奇按钮，而是因为数据、评估、时序判断、融合策略和现场验证还没有形成闭环。

## 0. 当前真实运行状态

当前 `.env` 中实际接入链路的模型是：

```text
YOLO_MODEL_PATH=yolov8n.pt
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_v2_plus_b012_best.pt
POSE_PROVIDER=yolo11_legacy
YOLO11_POSE_MODEL_PATH=models/pose_yolo_batch001_003_yolo11s_best.pt
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
```

也就是说：

- 新训练的 YOLO person 模型没有接入，当前人体检测仍是通用 `yolov8n.pt`。
- Fall Hint 模型已经接入，用来提供 `falling / fallen / lying / sitting / bending / kneeling / standing` 这类候选证据。
- Pose 模型已经替换成新训练的 `pose_yolo_batch001_003_yolo11s_best.pt`。
- LSTM 时序模型仍是 `fall_lstm_v5.onnx`。
- 最终告警不是任何单个模型直接决定，而是 Detection + Tracking + Pose + Fall Hint + LSTM + Fusion 状态机共同决定。

## P0 - 没有冻结回放评估集，所有“模型变好”都只是自我安慰

这是当前最大的问题。

你现在有训练指标，有人工标注，有模型文件，但缺少一个真正能回答问题的东西：固定的现场回放评估集。

现在的情况很尴尬：

- person 模型训练曲线看起来很好。
- 训练后的线上效果却不好。
- LSTM 有指标。
- 现场仍然把坐姿、低姿态、静止姿势推高成跌倒风险。
- Fall Hint 指标可接受。
- 但最终误报仍会发生。

这说明指标没有打到系统真正痛点。不是指标没用，是当前指标太温柔，没把模型往真实现场里按着测。

必须先建立：

- 固定正样本回放集：真实跌倒、模拟跌倒、跌倒后静止、滑落、缓慢倒地。
- 固定负样本回放集：坐着、弯腰、跪地、躺着休息、捡东西、靠墙、多人遮挡、空画面、半身入画。
- 每段视频要有人工标注的事件级标签：是否跌倒、跌倒开始时间、倒地确认时间、是否应告警。
- 每次换模型或阈值，都跑同一套回放，输出同一套指标。

必须看的指标：

```text
confirmed_fall_recall
confirmed_false_positive_count
confirmed_false_positive_rate
candidate_false_positive_count
missed_fall_count
first_confirm_delay_ms
sitting_as_fall_count
kneeling_as_fall_count
lying_adl_as_fall_count
```

没有这套评估集，继续训练就是蒙眼开车。

## P1 - 当前最该优先调整的是 LSTM + Fusion，不是先重训 Pose

你提到“会将坐姿判断为跌倒”。这类问题优先怀疑的是：

1. LSTM 时序模型对 ADL 负样本的区分不够硬。
2. Fusion 状态机对低姿态、静止、横向 bbox 的确认条件仍然偏激进。
3. Fall Hint 或 person bbox 给了某些弱证据后，下游没有足够强地压住误报。

Pose 模型当然会影响结果，但坐姿误判跌倒通常不是“骨架点歪一点”这么简单。当前链路里最终确认跌倒主要依赖：

- bbox 形态；
- 运动速度；
- 低姿态；
- 静止持续时间；
- fall hint；
- LSTM 概率；
- Fusion 多证据规则。

如果一个人坐着不动，bbox 可能横向、低姿态、速度低。糟糕一点的时序模型会说“像跌倒后静止”，糟糕一点的融合规则会说“证据够了”。这就是误报的温床。

所以当前优化顺序应该是：

```text
1. 先修 LSTM 训练数据和阈值校准
2. 再修 Fusion 对 sitting / kneeling / bending / lying ADL 的抑制规则
3. 再检查 Pose 是否真的提供了错误低姿态证据
4. 最后才考虑重新训练 Pose
```

## P1 - LSTM 可以继续训练，而且它才是提升跌倒判断精度的关键之一

当前 LSTM 不是摆设。它接收的是连续帧特征，而不是单张图片：

```text
bbox 宽高比
bbox 中心点
速度
静止状态
pose_available
pose_confidence
torso_angle
hip_height_ratio
head_height_ratio
person confidence
```

这意味着 LSTM 理论上正适合解决“坐下 vs 跌倒”“躺着休息 vs 跌倒后静止”这种单帧模型不擅长的问题。

但现在的问题是：当前 LSTM 训练集虽然包含 ADL，但仍然不够贴近你现场的误报分布。

现有 `fall_lstm_v5_metrics.json` 显示训练数据包括：

- fall: 90
- sitting: 62
- lying_down_normal: 161
- walking: 111
- standing: 43
- bending: 35
- squatting: 29
- picking_object: 17

这看起来像有负样本，但还不够。因为真正误报往往来自现场的“脏姿态”：

- 人坐在画面边缘；
- 人半身入画；
- 人低头弯腰停很久；
- 人靠着椅子或床；
- 多人遮挡；
- 小目标；
- 摄像头角度压缩人体高度；
- bbox 抖动导致速度异常；
- pose 丢点导致姿态特征空缺。

LSTM 要提升，不能只继续喂“干净动作样本”。要喂现场误报片段，而且要按时间序列标注。

建议下一步：

- 从线上误报中截取前后 10-20 秒视频。
- 保留模型输出的 jsonl 特征序列。
- 人工给每段标注：`fall / no_fall / sitting / bending / kneeling / lying_adl / occlusion / uncertain`。
- 特别增加“坐着不动”“弯腰不动”“躺着休息不告警”的 hard negative。
- 重新训练 LSTM，并做阈值校准，而不是只看 loss。

## P1 - Fusion 现在要更保守，特别是 confirmed fall

当前系统已经有 ADL 抑制逻辑，但现场效果说明它还不够狠。

应该明确一条产品级原则：

```text
候选可以敏感，确认必须保守。
```

也就是说：

- `fallen_candidate` 可以多一点，用于前端提示。
- `fallen_confirmed` 必须非常谨慎，因为它会触发主系统告警。

坐姿误判跌倒时，优先检查这些规则：

- 是否允许仅凭 LSTM 高概率 + 低姿态进入 confirmed。
- 是否要求 recent strong fall hint。
- 是否要求姿态证据和 bbox 形态同时成立。
- 是否对 `sitting / kneeling / bending` 做了足够强的 veto。
- 是否对短时间 track 切换、bbox 瞬移、速度异常做了防抖。
- 是否要求 confirmed 之前持续满足条件，而不是瞬时满足。

建议短期策略：

- `sitting / bending / kneeling` 当前帧如果由 Fall Hint 明确识别，应直接阻断 confirmed。
- 没有 strong hint 时，单靠 LSTM 不应直接 confirmed。
- pose 不可用时，confirmed 门槛应提高。
- bbox 高度仍然较高、中心点不够低时，不应 confirmed。
- 对多人和遮挡场景，confirmed 应更保守。

## P2 - 新 YOLO person 模型需要继续提升，但它不是当前“坐姿误报跌倒”的第一责任人

新训练 person 模型的问题是另一个层面的。

当前已有数据：

- `datasets/person_yolo` 约 952 张图片和 952 个标签文件。
- 候选权重包括 `models/person_yolo_batch001_008_yolov8n_best.pt`。
- 训练曲线最后一轮看起来很好：mAP50 接近 0.994，mAP50-95 约 0.732。
- 但接入后线上检测不稳定，所以已回退到 `yolov8n.pt`。

刺耳一点说：这个模型不是“训练失败”，而是“验收失败”。

原因大概率不是 1000 张太少这么简单，而是：

- 数据相似度太高，模型记住了场景，不是学会了泛化。
- 负样本不够狠，容易把家具、阴影、局部人体、背景结构当人。
- 多人、遮挡、小目标、边缘人体比例不够。
- 训练/验证/测试可能来自同类视频相邻帧，指标会虚高。
- 只用单一现场数据微调，可能损伤了 YOLO 原本的通用 person 能力。
- 没有用“视频级分组”切分 train/val/test，导致评估集太像训练集。

person 模型要继续提升，但方向不是盲目继续标 1000 张类似图。

正确提升方式：

- 从误检截图中建立 hard negative 集。
- 从漏检场景中建立 hard positive 集。
- 按视频源切分，不允许同一段视频的相邻帧同时进入 train 和 val/test。
- 加入更多不同光照、距离、角度、遮挡、多人、空房间、家具干扰。
- 对新 person 模型做离线回放比较：不能只看 mAP，要看 bbox 稳定性、误检数、漏检数、track ID 抖动。
- 如果新模型不能明显优于 `yolov8n.pt`，就继续不要接入。

结论：

```text
person 模型需要提升，但它解决的是“人框准不准”。
坐姿误判跌倒，主要不是 person 模型能单独解决的。
```

## P2 - Pose 模型还要检查，但不要把它当万能背锅位

当前 Pose 模型已经接入：

```text
models/pose_yolo_batch001_003_yolo11s_best.pt
```

指标显示：

- candidate box mAP50: 0.995
- candidate pose mAP50: 0.995
- candidate pose mAP50-95: 0.849
- link-match detached rate: 0.0

这说明在当前测试集上，Pose 模型不算烂。

但它仍可能在线上出问题：

- person bbox 错了，pose 会跟着错。
- 人太小或遮挡，pose 会丢点。
- 坐姿、半身、画面边缘会让关键点不完整。
- 姿态模型指标来自 400 张左右数据，覆盖仍然有限。
- 如果人工预标注来自旧姿态模型，标注本身可能继承了旧模型偏差。

Pose 应该怎么优化：

- 先收集“骨架脱离身体”的真实帧。
- 分清是 person bbox 错、pose 预测错、还是前端 overlay 坐标映射错。
- 对错误帧做人工修正，加入 pose hard set。
- 用回放评估 `keypoint_inside_bbox_ratio`、`torso_inside_bbox`、`pose_track_match_score`。

但如果目标是减少坐姿误报跌倒，Pose 不是第一刀。第一刀仍然是 LSTM/Fusion。

## P2 - Fall Hint 模型目前合格，但它不是最终裁判

Fall Hint 当前模型：

```text
models/yolo_fall_hint_v2_plus_b012_best.pt
```

指标：

- val mAP50: 0.761
- val mAP50-95: 0.579
- fallen recall: 0.890
- falling recall: 0.700
- kneeling targeted recall 从 0/74 提升到 74/74

它的定位应该保持为：

```text
候选证据模型，不是最终确认模型。
```

如果它把 `sitting / bending / kneeling` 识别出来，这些标签应该压制告警，而不是帮忙告警。

后续提升重点：

- 增加 sitting / kneeling / bending / lying_adl 的现场 hard negative。
- 不追求把所有状态都强行分类得漂亮，重点是别把 ADL 当 falling/fallen。
- 对 `falling` 召回仍可提升，但不能用牺牲误报来换。

## P3 - 主系统告警链路不是模型问题，但会放大“系统不可用”的观感

最近运行状态里已经出现过 `fallen_confirmed` payload，但推送主系统失败，原因是连接 `192.168.8.253:8000` 超时。

这不是模型精度问题，但用户体验上会表现为：

```text
检测到了也没弹窗。
```

所以它必须单独验收：

- Vision Service 到主系统 HTTP 可达。
- `/api/v1/video-bridge/fall-events` 返回 200。
- 主系统弹窗确认出现。
- 告警 payload 里 camera_id、incident_id、snapshot_url、risk_level 正确。

模型再好，主系统收不到，也只是一个本地玩具。

## 当前最应该做的顺序

### 第一步：建立冻结回放评估集

先别急着重训。先把现有系统拿到固定视频上跑出一张丑陋但真实的表。

输出：

- 哪些坐姿误报；
- 哪些跌倒漏报；
- 哪些是 bbox 错；
- 哪些是 pose 错；
- 哪些是 LSTM 概率错；
- 哪些是 Fusion 放行错；
- 哪些是主系统没收到。

### 第二步：先调 Fusion confirmed 门槛

目标不是让 candidate 变少，而是让 confirmed 更可靠。

优先做：

- sitting / kneeling / bending veto；
- pose unavailable 时提高 confirmed 门槛；
- 无 strong hint 时禁止快速 confirmed；
- track 切换后增加冷却；
- 多人遮挡时提高门槛。

### 第三步：采集 LSTM hard negative 并重训

重点采：

- 坐着不动；
- 弯腰不动；
- 跪地不动；
- 躺着休息；
- 靠床靠椅；
- 半身入画；
- 多人遮挡；
- bbox 抖动。

这些比再标一堆正常站立的人更值钱。

### 第四步：重新评估 person 模型，不合格就继续用 `yolov8n.pt`

person 模型的目标是稳定检测人体，不是判断跌倒。

新模型要接入必须满足：

- 漏检少于 `yolov8n.pt`；
- 误检少于或不高于 `yolov8n.pt`；
- bbox 抖动更小；
- 小目标和横躺人体不能更差；
- 不制造更多 track_id 抖动。

做不到就别接。强接只会让后面的 pose、LSTM、fusion 一起陪葬。

### 第五步：再扩 Pose hard set

只针对真实失败帧补，不要泛泛重训。

## 一句话结论

当前系统达不到预期，不是因为某一个模型没训练够，而是因为“训练指标”和“现场误报/漏报”之间还隔着一条很宽的沟。

最优先要解决的是：

```text
冻结回放评估集 + Fusion confirmed 保守化 + LSTM hard negative 重训
```

person 模型要继续提升，但它不是坐姿误报跌倒的第一责任人。Pose 模型要继续查，但它也不是万能背锅位。真正决定“坐着会不会被报跌倒”的，是 LSTM 和 Fusion 怎么理解连续动作证据。

