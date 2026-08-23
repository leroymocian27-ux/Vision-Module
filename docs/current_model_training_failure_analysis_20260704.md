# 当前模型准确率与误判率问题原因分析

日期：2026-07-04  
项目：`D:\Program\vision_service`  
目的：分析当前跌倒检测模型训练与评估流程中可能导致准确率、误判率达不到预期的原因，并给出下一步操作优先级。

## 1. 结论摘要

当前系统效果不稳定，不是单个阈值或单个模型文件的问题，而是以下问题叠加造成的：

```text
训练数据不足且不贴近真实误报
测试集/回放集不够冻结、不够覆盖真实场景
LSTM 训练数据实际没有姿态特征
LSTM 窗口标签过粗，没有使用跌倒阶段时间
离线速度特征可能受处理速度影响
YOLO fall-hint 测试集不足以证明线上泛化
Fusion/状态机缺少 ADL 反证据分支
线上配置与历史评估推荐存在漂移
```

一句话判断：

```text
当前不是“模型没训练够”，而是训练、评估、融合确认三者没有形成可靠闭环。
```

## 2. 当前实际运行模型

当前 `.env` 中实际接入：

```text
YOLO_FALL_MODEL_PATH=models/yolo_fall_hint_v2_plus_b012_best.pt
POSE_PROVIDER=yolo11_legacy
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
TEMPORAL_MODEL_WINDOW_SIZE=32
TEMPORAL_MODEL_INPUT_DIM=15
FALLING_PROB_THRESHOLD=0.65
FALL_CONFIRM_FRAMES=5
FALL_STILL_MS=1500
```

这意味着当前最终跌倒判断不是单一 YOLO 或单一 LSTM 决定，而是：

```text
person detection
fall hint detection
pose
tracking
LSTM temporal probability
fusion/state machine
```

共同决定。

## 3. LSTM 训练数据存在的核心问题

### 3.1 数据规模偏小

`models/fall_lstm_v5_metrics.json` 显示：

```text
train windows: 384
positive fall windows: 51
negative windows: 333
all windows: 548
val windows: 74
test windows: 90
```

这个规模对 LSTM 来说偏小，尤其是正样本只有 51 个训练窗口。模型很容易学到“低姿态、横向框、静止”这些粗特征，而不是学会区分：

```text
真实跌倒
坐下
弯腰
主动躺卧
蹲下
半身入画
遮挡
```

### 3.2 ADL hard negative 覆盖不足

当前 LSTM v5 子类型窗口计数：

```text
lying_down_normal: 161
sitting: 62
walking: 111
standing: 43
fall: 90
bending: 35
squatting: 29
picking_object: 17
```

这说明虽然有 ADL 负样本，但数量仍然太薄。真实误报往往来自更复杂的现场动作：

```text
坐在画面边缘
半身入画
低头弯腰停很久
靠床/靠椅
多人遮挡
小目标
镜头角度压缩身体高度
bbox 抖动导致速度异常
pose 丢点
```

这些比“干净的 sitting/bending/squatting 数据”更重要。

### 3.3 LSTM 训练数据实际没有姿态特征

对 `data/temporal_sequences_phase6d` 的统计：

```text
jsonl files: 167
rows: 6659
pose_available: 0
pose_available_ratio: 0.0
labels: fall=2220, non_fall=4439
splits: unassigned=6659
```

也就是说，虽然 LSTM schema 包含：

```text
pose_available
pose_confidence
torso_angle_norm
head_height_ratio_filled
hip_height_ratio_filled
```

但当前训练数据中这些姿态信息全部不可用，实际训练更接近：

```text
bbox + motion only
```

这会削弱模型区分弯腰、坐下、蹲下、躺卧的能力。因为这些动作的差异常常需要头、肩、髋、躯干角度来辅助判断。

### 3.4 split 没有人为冻结

统计显示 JSONL 原始行全部是：

```text
split=unassigned
```

训练脚本会按 `split_group` 自动分配 train/val/test，因此不是完全随机帧切分，但这仍然不等于人工冻结测试集。

问题是：

```text
没有稳定的 test_frozen
没有 fp_regression
每次新增数据或重训后，很难判断模型是否真的变好
```

如果没有固定回放集，训练指标提升可能只是数据分布变了，不代表线上误报下降。

### 3.5 窗口标签过粗

当前 `scripts/train_fall_lstm.py` 的窗口标签逻辑是：

```text
一个 32 帧窗口中，只要任意帧 label == fall，则该窗口 label = 1。
```

问题：

```text
窗口只擦到跌倒边界也会变成正样本
pre_fall 可能被混入正样本
recovery 可能被混入正样本
fallen_hold 和 falling 被合成一个类别
无法区分快速跌倒与慢速跌倒
```

这会让 LSTM 学到模糊概念：只要一段动作里曾经低姿态/横向/静止，就可能倾向 fall。

### 3.6 event_start_frame / event_end_frame 没有真正用于训练标签

导出数据里有：

```text
event_start_frame
event_end_frame
```

但当前训练脚本并没有使用这些字段去构造 phase-aware 标签。也就是说，跌倒阶段信息没有真正进入训练过程。

建议后续改成：

```text
pre_fall: negative 或 ignore
falling: positive
impact: positive
fallen_hold: positive 或单独类别
recovery: ignore 或 negative
```

### 3.7 离线速度特征可能不可靠

当前特征提取中速度使用 `time.monotonic()` 计算。在线实时运行时还算合理，但离线导出视频时，处理速度取决于机器推理速度，而不是视频真实 FPS。

这意味着：

```text
velocity_x
velocity_y
speed
```

可能受离线处理速度影响，训练时的速度分布和真实运行时的速度分布不一致。

后续应改为：

```text
dt = frame_stride / video_fps
velocity = delta / dt
```

否则 LSTM 会学到带偏差的速度特征。

## 4. YOLO fall-hint 训练与测试问题

当前接入模型：

```text
models/yolo_fall_hint_v2_plus_b012_best.pt
```

指标：

```text
dataset_item_count: 1334
val images: 207
test images: 52
val precision: 0.749
val recall: 0.710
val mAP50: 0.761
test precision: 0.586
test recall: 0.667
test mAP50: 0.695
```

关键问题是 metrics 文件自己已经说明：

```text
Test split has no fallen or kneeling samples and only one falling sample,
so it is not reliable for fall-hint model selection.
```

也就是说，当前 test split 无法证明 fall-hint 模型对真实跌倒/跪地/倒地场景的泛化能力。

另外，fall-hint 的定位应该是：

```text
候选证据模型
不是最终裁决模型
```

如果它识别出 sitting / bending / kneeling，这些标签应该帮助抑制误报，而不是被下游当作低姿态危险证据继续放大。

## 5. 端到端评估不足

`evaluations/phase9_full_accuracy_closure_001.json` 中：

```text
e2e_fall_count: 1
e2e_adl_count: 3
decision: live_loop_passed_but_not_certified_80_percent
```

这说明当时闭环测试只是证明“链路能跑通”，不是证明“模型达到可上线准确率”。

同时端到端报告中有一处非常重要的现象：

```text
shadow_onnx_lstm fall_probability = 0.0679
final fall_prob = 0.72
confirm_source = field_low_posture_recent_fall_hint
```

这说明当时一次确认并不是 ONNX LSTM 真的判断为高风险，而是其他融合逻辑放行了告警。

因此如果只盯着 LSTM loss 或 YOLO mAP，会错过真正问题：

```text
最终误报/漏报可能发生在 Fusion confirmed 逻辑。
```

## 6. Fusion/状态机问题

当前状态机主要检查：

```text
LSTM 概率
快速下坠
低姿态
静止
持续帧数
持续时间
```

但真实误报需要反向判断：

```text
是否更像坐下？
是否更像弯腰？
是否更像主动躺卧？
是否更像蹲跪？
是否有恢复趋势？
是否位于床/沙发/椅子等支撑区域？
是否 track 不稳定？
```

如果只堆正证据，坐下、弯腰、短暂躺卧很容易满足：

```text
低姿态
静止
横向 bbox
持续
```

因此误报率下不来。

建议优先执行已整理的 v6 方案：

```text
fall_evidence_score
adl_suppression_score
sitting_score
bending_score
normal_lying_score
squatting_score
recovery_score
track_quality_score
slow_fall_candidate
```

参考文档：

```text
docs/fall_state_machine_v6_logic_review_20260703.md
```

## 7. 上游模型也会放大问题，但不是第一优先级

### 7.1 Person detection

当前 `.env` 仍然使用通用 person 检测路径。历史审计中提到，新训练 person 模型离线指标看起来好，但线上不稳定，说明它可能存在：

```text
数据同质化
视频级隔离不足
hard negative 不足
接入后 bbox 抖动或漏检增加
```

person 检测错误会传导给：

```text
tracking
pose
LSTM feature
fall_state_machine
```

但“坐下误报跌倒”的第一责任通常仍是 LSTM/Fusion 对 ADL 的理解不足。

### 7.2 Pose

当前 LSTM 训练数据中姿态可用率为 0，因此不能指望当前 LSTM 真正利用 pose 区分坐下/弯腰。

线上 pose 又可能因为：

```text
目标小
遮挡
半身入画
person bbox 错误
pose worker busy
```

导致缺点或错点。

因此下一步要明确：

```text
训练 bbox-only temporal model
还是训练 bbox + pose temporal model
```

二者要分开评估，不能混在一起说模型好坏。

## 8. 当前最可能的问题原因排序

### P0：没有足够可靠的冻结回放评估集

没有 `test_frozen` 和 `fp_regression`，就无法判断每次训练、调阈值、改状态机到底是否变好。

必须优先建立：

```text
真实跌倒回放集
慢速跌倒回放集
坐下/弯腰/蹲跪/主动躺卧误报回归集
遮挡/半身/多人/空镜头回归集
```

### P1：Fusion confirmed 逻辑过于依赖正证据，缺少 ADL 反证据

只看“像不像跌倒”不够，还要看“是不是更像 ADL”。

### P1：LSTM hard negative 不足，且没有 pose 信息

当前 LSTM 很难区分复杂 ADL，因为训练数据不够贴近现场误报，而且 pose 特征实际全空。

### P1：LSTM 标签策略粗糙

当前窗口标签会污染正样本边界，必须升级为 phase-aware 标签。

### P2：YOLO fall-hint 测试集不足

test split 太小且类别缺失，不能证明泛化能力。

### P2：离线速度特征与线上速度特征可能分布不一致

速度用 `time.monotonic()` 会引入离线处理速度偏差。

### P2：上游检测/姿态/跟踪不稳定会放大误判

这需要通过回放归因来判断，不应直接盲目重训 pose 或 person。

## 9. 下一步操作建议

### 第一步：建立冻结回放集

先不要急着重训。

至少建立：

```text
test_frozen/fall_fast
test_frozen/fall_slow
fp_regression/sitting_down
fp_regression/bending
fp_regression/kneeling
fp_regression/lying_down_normal
fp_regression/half_body
fp_regression/occlusion
fp_regression/multi_person
```

每类先 5 到 10 段也有价值。

### 第二步：做错误归因表

每个失败样本标注：

```text
bbox 错
track 错
pose 错
LSTM 概率错
fall-hint 错
fusion 放行错
通信/告警链路错
```

没有归因表，不要重训。

### 第三步：先改 Fusion v6，不急着改 ONNX

优先实现：

```text
ADL suppression
recovery detection
track quality gate
slow fall fallback
event latch / dedup
decision_reason 输出
```

这会比直接训练 LSTM v6 更快看到误报下降。

### 第四步：修正 LSTM 数据导出和标签

训练 LSTM v6 前必须做：

```text
使用 video_fps/frame_seq 计算速度
使用 event_start/end 构造 phase-aware 窗口标签
引入现场 hard negative
明确 bbox-only 与 bbox+pose 两套训练策略
冻结 train/val/test
```

### 第五步：重新校准阈值

阈值不能靠感觉定。

需要在 val 上校准：

```text
fall_probability
fall_evidence_score
adl_suppression_score
low_posture_hold_ms
slow_fall_hold_ms
recovery_score
```

然后只在 test_frozen 上做最终验收。

## 10. 建议验收指标

不要只看 mAP、loss、accuracy。

建议看：

```text
confirmed_fall_recall
confirmed_false_positive_count
confirmed_false_positive_rate
candidate_false_positive_count
missed_fall_count
first_confirm_delay_ms
sitting_as_fall_count
bending_as_fall_count
kneeling_as_fall_count
lying_adl_as_fall_count
slow_fall_recall
decision_reason_distribution
```

只有这些指标稳定，才说明系统真的变好了。

## 11. 最终判断

当前准确率和误判率达不到要求，最可能不是因为某一个模型“完全不行”，而是因为：

```text
训练数据没有覆盖真实现场误报
LSTM 实际没有用上姿态信息
窗口标签粗糙
离线/线上特征分布不一致
测试集不能证明泛化
状态机缺少 ADL 反证据
最终 confirmed 逻辑不够保守
```

下一步最应该做：

```text
冻结回放评估集
错误归因
Fusion v6 ADL 反证据
LSTM 数据修复与 hard negative 重训
```

不建议现在直接盲目继续训练更多 epoch，也不建议只靠调 `fall_probability >= 0.65` 这类单阈值解决问题。

