# LSTM 时序跌倒模型交接与研究升级说明

日期：2026-07-03  
项目：`D:\Program\vision_service`  
交接对象：协助研究与升级跌倒检测时序模型的教授/研究合作者

## 1. 文档目的

本文档用于交接当前跌倒检测系统中的 LSTM 时序模型部分，说明它在系统中的位置、当前逻辑、训练方式、数据集形态、人工审核要求、已知问题，以及后续研究升级路线。

请特别注意：当前系统中的 LSTM 不是直接识别图片的视觉模型，而是一个基于检测框、运动轨迹和姿态摘要特征的时序二分类模型。它负责输出“最近一段连续时间内该目标是否像跌倒”的概率，最终是否报警仍由状态机融合逻辑决定。

## 2. 当前系统概览

### 2.1 总体链路

当前跌倒判断链路如下：

```text
视频帧
  -> 人体检测 YOLO
  -> 多目标跟踪 track_id/person_id
  -> 可选姿态估计 pose
  -> 提取每帧时序特征 TargetFeature
  -> 按同一个人累计 FeatureWindow
  -> LSTM/ONNX 输出 fall_probability
  -> FallStateMachine 融合概率、快速下坠、低姿态、静止时长
  -> fallen_confirmed
  -> 事件上报/前端告警
```

核心代码入口：

- 在线时序服务：`app/services/temporal_service.py`
- 每帧特征提取：`app/temporal/target_feature_extractor.py`
- 特征窗口缓存：`app/temporal/feature_window.py`
- 特征向量化：`app/temporal/feature_vectorizer.py`
- ONNX LSTM 推理：`app/temporal/onnx_sequence_model.py`
- 状态机融合确认：`app/temporal/fall_state_machine.py`
- LSTM 训练导出：`scripts/train_fall_lstm.py`
- 单视频特征导出：`scripts/export_temporal_sequences.py`
- 数据集批量导出：`scripts/export_dataset_temporal_sequences.py`

### 2.2 当前运行配置

当前 `.env` 中与时序模型相关的关键配置：

```text
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v5_features.json
TEMPORAL_MODEL_WINDOW_SIZE=32
TEMPORAL_MODEL_INPUT_DIM=15
TEMPORAL_WARMUP_MIN_SIZE=16
TEMPORAL_FALLBACK_TO_MOCK=true
TEMPORAL_ONNX_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider
UNSTABLE_FRAME_THRESHOLD=3
FALLING_PROB_THRESHOLD=0.65
FALL_CONFIRM_FRAMES=5
FALL_STILL_MS=1500
```

当前生产配置已经启用 `onnx_lstm`。如果模型文件缺失、ONNX Runtime 不可用、schema 不匹配或推理异常，系统会退回 mock 规则模型。

## 3. LSTM 模型当前逻辑

### 3.1 它判断的不是单帧，而是 32 帧窗口

LSTM 的输入是连续窗口：

```text
[batch, 32, 15]
```

含义是：每个样本包含同一目标最近 32 帧，每帧 15 个数值特征。

因此它不是回答“这一帧是不是跌倒”，而是回答：

```text
同一个人在最近 32 帧中的运动变化，是否符合跌倒过程？
```

32 帧对应的真实时间取决于分析帧率：

- 如果分析帧率约 10 FPS，窗口约 3.2 秒。
- 如果分析帧率约 5 FPS，窗口约 6.4 秒。
- 当前代码以帧数为窗口单位，不显式保证固定秒数。

当窗口未满 32 帧时，ONNX 模型返回 `warming_up`，不会给出真实 LSTM 判断。

### 3.2 每帧 15 维特征

当前特征 schema 为 `fall_lstm_features_v1`，输入维度 15，schema hash 为 `db4246cef1eb39a1`。

特征列表：

```text
1. bbox_center_x_norm
2. bbox_center_y_norm
3. bbox_width_norm
4. bbox_height_norm
5. aspect_ratio_clipped
6. delta_x_norm
7. delta_y_norm
8. velocity_x_norm
9. velocity_y_norm
10. speed_norm
11. pose_available
12. pose_confidence
13. torso_angle_norm
14. head_height_ratio_filled
15. hip_height_ratio_filled
```

这些特征主要表达：

- 人体框是否快速向下移动。
- 框的形状是否从竖向变为横向。
- 目标是否出现明显位移或速度变化。
- 姿态是否可用。
- 躯干是否倾斜。
- 头部和髋部是否进入低姿态。

缺失姿态时的填充值：

```text
pose_available = 0.0
pose_confidence = 0.0
torso_angle_norm = 0.0
head_height_ratio_filled = -1.0
hip_height_ratio_filled = -1.0
```

### 3.3 当前网络结构

训练脚本中的模型结构：

```text
LSTM(input_dim=15, hidden_dim=64, layers=1, batch_first=True)
Dropout(0.2)
Linear(64 -> 1)
Sigmoid -> fall_probability
```

模型输出一个概率：

```text
fall_probability in [0.0, 1.0]
```

训练时使用 `BCEWithLogitsLoss`，并根据正负样本比例设置 `pos_weight`，以缓解跌倒正样本少的问题。

### 3.4 LSTM 概率不会直接触发报警

LSTM 只是给出概率。最终是否进入 `fallen_confirmed` 由状态机判断。

状态机状态：

```text
normal
unstable
falling
fallen_candidate
fallen_confirmed
cooldown
```

当前确认条件大致包括：

```text
fall_probability >= 0.65
存在快速下坠证据，例如 delta_y > 40
进入低姿态，例如 bbox aspect_ratio 较大，或头/髋高度比例变低
动作后速度较低，表现为静止
候选状态持续至少 5 帧
候选状态持续至少 1500ms
```

因此，系统实际逻辑是：

```text
LSTM 判断“像不像跌倒”
状态机判断“证据是否足够确认报警”
```

这种架构是合理的，因为单纯依赖 LSTM 概率容易误报，单纯依赖规则又容易漏报复杂动作。

## 4. 当前模型资产和训练状态

当前主要模型文件：

```text
models/fall_lstm_v5.onnx
models/fall_lstm_v5_features.json
models/fall_lstm_v5_metrics.json
models/fall_lstm_v5_train_config.json
models/fall_lstm_v5_threshold_calibration.json
```

`fall_lstm_v5_train_config.json`：

```json
{
  "epochs": 30,
  "batch_size": 32,
  "learning_rate": 0.001,
  "stride": 4,
  "seed": 42,
  "model": {
    "input_dim": 15,
    "hidden_dim": 64,
    "layers": 1
  }
}
```

`fall_lstm_v5_metrics.json` 中的训练数据规模：

```text
train samples: 384
positive samples: 51
negative samples: 333
all window count: 548
train/val/test: 384 / 74 / 90
```

子类型分布：

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

重要判断：

```text
当前模型可运行、可加载、可推理，但训练样本量偏小。
尤其是 fall 正样本、坐下/弯腰/蹲下/遮挡/半身入画等 hard negative 不足。
因此当前最主要瓶颈不是网络结构，而是时序数据集质量与覆盖度。
```

## 5. 训练数据应该是什么样

### 5.1 它不是普通图片数据集

LSTM 时序模型训练数据不应该是：

```text
一张图片 -> fall/non_fall
```

而应该是：

```text
一段视频 -> 人工标注事件时间 -> 自动导出逐帧特征 -> 32 帧滑动窗口训练
```

推荐原始数据目录：

```text
datasets/temporal_fall_v1/
  videos/
    fall_001.mp4
    fall_002.mp4
    sit_001.mp4
    bend_001.mp4
    lie_down_001.mp4
  labels_temporal_v1.jsonl
```

### 5.2 推荐视频级标签格式

跌倒视频：

```json
{
  "video_id": "local/fall_001.mp4",
  "binary_label": "fall",
  "event_start_frame": 86,
  "event_impact_frame": 112,
  "event_end_frame": 146,
  "fall_phase_notes": "standing fall, clear impact, full body visible",
  "non_fall_subtype": null,
  "split_group": "local_fall_001",
  "split": "train",
  "usable_for_training": true,
  "review_status": "human_verified"
}
```

非跌倒视频：

```json
{
  "video_id": "local/sit_001.mp4",
  "binary_label": "non_fall",
  "event_start_frame": null,
  "event_impact_frame": null,
  "event_end_frame": null,
  "non_fall_subtype": "sitting_down",
  "split_group": "local_sit_001",
  "split": "train",
  "usable_for_training": true,
  "review_status": "human_verified",
  "notes": "controlled sitting, no fall"
}
```

### 5.3 推荐非跌倒子类型

请不要把所有非跌倒都标成 `non_fall` 后就结束。为了降低误报，必须细分：

```text
sitting_down
standing_up
bending
squatting
kneeling
lying_down_normal
walking
standing
picking_object
reaching_down
half_body
occlusion
multi_person_crossing
camera_motion
no_person
false_detector_box
```

其中最重要的是 hard negative：

```text
快速坐下
慢慢坐下
弯腰捡东西
蹲下/跪下
主动躺下
坐到地上
半身入画
被桌椅遮挡
检测框突然变横但不是跌倒
多人交叉导致 track 不稳定
```

如果这些样本不足，模型很容易把“姿态变低”学成“跌倒”。

## 6. 人工审核标准

### 6.1 审核目标

人工审核不是只看“视频是不是跌倒”。必须确认：

```text
动作类别是否正确
跌倒开始/结束时间是否准确
目标跟踪是否稳定
检测框是否覆盖正确的人
姿态点是否可信
该样本是否适合训练
该样本是否应该进入冻结测试集
```

### 6.2 跌倒视频审核

跌倒视频必须标注以下阶段：

```text
pre_fall
falling
impact
fallen_hold
recovery
```

建议定义：

- `pre_fall`：跌倒前的正常站立、行走、坐姿准备等。
- `falling`：明显失控、快速下坠、身体姿态从直立向低姿态转换。
- `impact`：接触地面、床、椅或其他支撑面的关键时刻。
- `fallen_hold`：跌倒后保持低姿态、移动很少。
- `recovery`：起身、坐起、被扶起或离开倒地姿态。

必须人工确认：

```text
fall_start_frame
fall_impact_frame
fall_end_frame
```

不要把整段 fall 视频都当作正样本。跌倒前正常行走、跌倒后恢复阶段如果粗暴标为 fall，会污染 LSTM。

### 6.3 非跌倒视频审核

非跌倒视频必须确认：

```text
确实没有跌倒事件
动作子类型正确
是否存在遮挡、半身入画、多人交叉、摄像头抖动
是否适合训练
```

非跌倒样本如果非常像跌倒，应该保留并标为 hard negative，而不是删除。

推荐字段：

```text
non_fall_subtype
hard_negative: true/false
occlusion_level: none/light/medium/heavy
body_visible: full/upper_only/lower_missing/partial
track_quality: good/acceptable/bad
bbox_quality: good/acceptable/bad
pose_quality: good/acceptable/bad/not_available
usable_for_training: true/false
reject_reason
```

### 6.4 跟踪质量审核

LSTM 依赖同一个人的连续轨迹，因此 track 质量非常关键。

必须剔除或标记：

```text
track_id 中途换人
目标框跳到另一个人
目标短时间丢失后重新接上但位置不连续
多人遮挡后身份错乱
检测框突然扩大到背景/家具
```

建议将这类样本设为：

```text
usable_for_training=false
reject_reason=track_switch 或 bad_bbox
```

但如果线上经常出现这类问题，也可以单独建立“鲁棒性评估集”，不要混入普通训练集。

### 6.5 姿态质量审核

当前 LSTM 特征中包含姿态可用性、姿态置信度、躯干角、头/髋高度比例。若姿态完全错位，会误导模型。

建议审核：

```text
pose_available 是否真实
头部点是否落在人头附近
肩/髋点是否大致合理
人体被遮挡时是否应标 pose_quality=bad
```

如果当前运行环境中姿态经常不可用，应明确区分两个训练方向：

```text
方向 A：bbox-only LSTM，依赖框与运动特征。
方向 B：bbox + pose LSTM，依赖更强姿态特征，但要求 pose 稳定。
```

二者不应混淆评估。

## 7. 当前训练脚本的关键问题

### 7.1 当前窗口标签偏粗

`scripts/train_fall_lstm.py` 当前构造窗口标签的逻辑是：

```text
一个 32 帧窗口中，只要任意帧 label == fall，则该窗口 label = 1
否则 label = 0
```

这在第一版工程验证中可以接受，但对精细训练不够。

潜在问题：

```text
窗口只擦到一点点 fall 边界，也会变成正样本。
pre_fall 或 recovery 容易被误混进正样本。
fallen_hold 和 falling 的动力学不同，却被合并为同一类。
```

建议升级为 phase-aware 窗口标签：

```text
positive_falling：窗口末端接近 falling/impact
positive_fallen_hold：窗口内包含 fall 后静止
negative_pre_fall：跌倒前正常阶段
negative_adl：普通日常动作
hard_negative：像跌倒但不是跌倒
ignore：边界不清、track 质量差、遮挡严重
```

如果暂时仍做二分类，也建议至少规定：

```text
窗口中 falling/fallen_hold 有足够覆盖比例才标正样本。
只碰到 1-2 帧边界的窗口设为 ignore。
recovery 默认不作为正样本。
```

### 7.2 离线导出速度特征可能有偏差

当前特征提取中的速度由 `time.monotonic()` 计算相邻帧时间差。在线实时运行时，这基本反映真实处理间隔；但离线批量导出视频时，处理速度可能快于或慢于真实视频 FPS，导致 `velocity_x/velocity_y/speed` 带有处理速度偏差。

建议研究升级：

```text
导出时使用视频 fps 和 frame_seq 计算时间差。
将 velocity 改成基于 frame interval 的稳定物理量。
保留 delta_y 等帧间位移作为不依赖 wall-clock 的特征。
```

这是一个较重要的工程修正点。

### 7.3 当前指标不足以证明泛化能力

当前 `fall_lstm_v5_metrics.json` 主要记录：

```text
样本数
正负样本数
loss
ONNX 导出一致性
```

它不能充分证明模型实际效果。

必须补充：

```text
视频级 fall recall
视频级 confirmed recall
ADL false positive rate
hard negative false positive rate
first_falling_delay_ms
first_confirmed_delay_ms
按 subtype 的误报/漏报统计
按 camera/viewpoint 的统计
```

## 8. 推荐训练流程

### 8.1 准备视频

最低建议规模：

```text
真实跌倒视频：至少 100-200 段
非跌倒日常视频：至少 300-500 段
hard negative：至少 200 段
```

若短期达不到，请优先收集：

```text
坐下/快速坐下
弯腰/蹲下/跪下
主动躺下
半身入画
遮挡
多人交叉
线上误报片段
```

### 8.2 人工审核标签

每段视频先写入 `labels_temporal_v1.jsonl`，要求：

```text
review_status=human_verified
split_group 固定为视频级或场景级
split 不允许随机帧切分
usable_for_training 明确 true/false
```

### 8.3 导出时序特征

单视频导出示例：

```powershell
python scripts\export_temporal_sequences.py `
  --video datasets\temporal_fall_v1\videos\fall_001.mp4 `
  --output data\temporal_sequences_v6\local\fall_001.jsonl `
  --camera-id local_fall_001 `
  --video-id local/fall_001.mp4 `
  --label fall `
  --event-start-frame 86 `
  --event-end-frame 146 `
  --split-group local_fall_001 `
  --split train `
  --enable-pose
```

批量导出可使用：

```powershell
python scripts\export_dataset_temporal_sequences.py `
  --manifest datasets\dataset_manifest.json `
  --dataset ur_fall `
  --output-dir data\temporal_sequences_v6 `
  --labels datasets\labels_temporal_v1.jsonl `
  --frame-stride 2
```

### 8.4 训练

```powershell
$files = Get-ChildItem -Path data\temporal_sequences_v6 -Recurse -Filter *.jsonl | ForEach-Object { $_.FullName }

python scripts\train_fall_lstm.py `
  --input $files `
  --output-dir models `
  --model-version v6 `
  --epochs 30 `
  --batch-size 32 `
  --stride 4
```

### 8.5 离线评估

训练后必须在冻结测试集上评估，不允许只看 loss。

推荐输出：

```text
overall:
  fall_video_recall
  fallen_confirmed_recall
  adl_video_fp_rate
  hard_negative_fp_rate
  mean_first_falling_delay_ms
  mean_first_confirmed_delay_ms

by_subtype:
  sitting_down
  bending
  squatting
  lying_down_normal
  occlusion
  half_body

by_dataset:
  local
  ur_fall
  gmdcsa24
```

## 9. 数据集划分原则

必须做视频级或场景级隔离：

```text
同一个原始视频不能同时出现在 train 和 val/test。
同一个连续拍摄场景的相邻片段尽量不要跨 split。
同一人物、同一房间、同一摄像机角度的连续切片要谨慎跨 split。
```

禁止：

```text
随机抽帧切分
同一视频滑窗后随机打散到 train/test
测试集参与阈值调参
线上误报回放集混入训练后仍用于评估
```

推荐：

```text
train：训练模型
val：选阈值、调状态机
test_frozen：最终验收，一旦冻结不得训练
fp_regression：线上误报回归集，只用于防止老问题复发
```

## 10. 建议教授重点研究的问题

### 10.1 第一优先级：数据与标签协议

请优先评审：

```text
跌倒事件阶段定义是否合理
fall_start / impact / fall_end 标注是否一致
非跌倒子类型是否覆盖真实误报
窗口标签策略是否科学
```

当前模型很可能不是被网络结构限制，而是被数据规模和标签粗糙度限制。

### 10.2 第二优先级：特征工程

建议研究：

```text
使用视频 fps 修正速度特征
增加 bbox 高度变化率、面积变化率
增加累计下降距离
增加低姿态持续时间
增加 pose 缺失连续帧数
增加 track 稳定性特征
```

但新增特征必须同步更新：

```text
feature_vectorizer.py
fall_lstm_features.json
训练数据导出脚本
ONNX 模型输入维度
运行时 schema 校验
```

### 10.3 第三优先级：模型结构

在数据增强后，可比较：

```text
当前单层 LSTM baseline
GRU
双层 LSTM
Temporal CNN
Transformer Encoder
轻量 TCN
```

但研究时请保持同一冻结测试集，否则无法判断结构改进是否真实。

### 10.4 第四优先级：融合逻辑

当前状态机对最终报警影响很大。建议把 LSTM 和状态机分开评估：

```text
只评估 LSTM window-level AUC/PR-AUC
再评估 LSTM + state machine 的视频级报警表现
```

如果 LSTM 分数好但最终确认差，问题可能在状态机阈值；如果 LSTM 分数本身差，问题在数据/特征/模型。

## 11. 推荐验收标准

在升级模型进入主动运行前，建议至少满足：

```text
冻结测试集 fall_video_recall >= 90%
冻结测试集 fallen_confirmed_recall >= 80%
ADL confirmed false positive rate <= 2%
hard negative confirmed false positive rate <= 5%
平均 first_falling_delay_ms <= 1500ms
平均 first_confirmed_delay_ms <= 3000ms
ONNX Runtime CPU/GPU 均可加载
schema_hash 完全匹配
fallback_active=false
```

若用于真实安防或养老场景，还应额外评估：

```text
夜间/低光
遮挡
多人
摄像头俯视/侧视
老人缓慢跌倒
从椅子/床边滑落
跌倒后仍有小幅动作
```

## 12. 最重要的结论

当前 LSTM 时序模型已经具备完整工程闭环：

```text
视频 -> 特征导出 -> LSTM 训练 -> ONNX 导出 -> 运行时推理 -> 状态机融合 -> 告警
```

它现在确实是在结合前后多帧情况判断当下是否可能跌倒。

但下一阶段升级的关键不是立刻更换模型结构，而是建立高质量、可审计、可复现的时序数据集：

```text
精确事件时间
清晰非跌倒子类型
足够 hard negative
稳定 track 审核
视频级 split 隔离
冻结测试集
线上误报回归集
```

如果这些基础不完成，继续训练只会让模型更自信地学习错误模式。若这些基础完成，当前 LSTM 可以作为强 baseline；之后再比较 GRU、TCN 或 Transformer 才有研究意义。

## 13. 建议近期行动清单

1. 冻结一版 `test_frozen` 和 `fp_regression`，禁止参与训练。
2. 制定并执行 `labels_temporal_v1.jsonl` 人工审核表。
3. 优先补充坐下、弯腰、蹲下、主动躺下、遮挡、半身入画等 hard negative。
4. 修正离线导出速度特征，改为基于视频 fps/frame_seq。
5. 改进训练窗口标签，从“任意帧 fall 即正样本”升级为 phase-aware 标签。
6. 训练 `fall_lstm_v6`，保留 v5 作为 baseline。
7. 分别评估 LSTM 原始概率和状态机最终确认效果。
8. 只有在冻结测试集和误报回归集均通过后，才将新模型切到 `TEMPORAL_MODEL_PROVIDER=onnx_lstm` 主路径。

