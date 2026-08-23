# 跌倒时序逻辑 v6 实施计划

日期：2026-07-03  
依据文档：`docs/fall_state_machine_v6_logic_review_20260703.md`  
目标：在不立即重训 LSTM、不改变 ONNX 输入维度的前提下，先完善状态机逻辑、补充 ADL 反证据分支、加入慢速跌倒兜底路径，并建立可回放的误报/漏报评估闭环。

## 1. 总体策略

当前优先级不是直接修改 LSTM 网络结构，而是先增强时序融合逻辑：

```text
第一阶段：可观测化，把关键证据分数和原因输出出来。
第二阶段：增加 fall_evidence_score 与 adl_suppression_score。
第三阶段：升级状态机，加入快速跌倒路径、慢速跌倒路径、ADL 抑制路径。
第四阶段：建立 fp_regression 和 slow_fall 专项回归集。
第五阶段：评估是否需要训练 LSTM v6。
```

这样做的好处：

```text
不破坏当前 ONNX LSTM v5 路径。
可以快速验证误报是否下降。
每次误判都能解释原因。
教授审核重点可以落在逻辑和数据上，而不是先陷入模型结构争论。
```

## 2. 当前代码改造边界

### 2.1 保持不变

短期不修改：

```text
models/fall_lstm_v5.onnx
models/fall_lstm_v5_features.json
app/temporal/feature_vectorizer.py 的 15 维 ONNX 输入
scripts/train_fall_lstm.py 的模型结构
```

### 2.2 重点修改

建议修改或新增：

```text
app/temporal/fall_state_machine.py
app/services/temporal_service.py
app/temporal/schemas.py
app/core/config.py
tests/test_fall_state_machine_debug.py
tests/test_temporal_service.py
tests/test_fall_fusion.py 或新增 v6 专项测试
```

建议新增：

```text
app/temporal/fall_evidence_scorer.py
app/temporal/adl_suppressor.py
app/temporal/scene_context.py
app/temporal/temporal_motion_features.py
tests/test_fall_evidence_scorer.py
tests/test_adl_suppressor.py
tests/test_fall_state_machine_v6.py
```

## 3. 阶段 0：基线冻结与风险控制

### 3.1 目的

在改动之前记录当前行为，避免修改后无法判断效果是变好还是变差。

### 3.2 任务

1. 记录当前 `.env` 时序配置：

```text
ENABLE_TEMPORAL=true
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v5.onnx
FALLING_PROB_THRESHOLD=0.65
FALL_CONFIRM_FRAMES=5
FALL_STILL_MS=1500
```

2. 用当前逻辑跑一遍已有评估集：

```text
evaluations/phase6e_provider_eval
evaluations/phase9_e2e_acceptance_001.json
evaluations/phase9_state_machine_sweep_001.json
```

3. 保存一份 baseline 报告：

```text
evaluations/fall_temporal_v6/baseline_before_v6.json
```

### 3.3 验收

必须拿到：

```text
当前误报视频清单
当前漏报视频清单
当前 first_falling_delay_ms
当前 first_confirmed_delay_ms
当前各类状态分布
```

## 4. 阶段 1：新增可观测字段，不改变决策

### 4.1 目的

先计算证据，但暂时不改变 `fallen_confirmed` 逻辑。这样可以确认新特征是否稳定。

### 4.2 新增模块

新增 `app/temporal/temporal_motion_features.py`。

职责：

```text
从 FeatureWindow 中提取最近 8/16/32 帧统计特征。
```

建议输出：

```text
cumulative_drop_8f
cumulative_drop_16f
cumulative_drop_32f
max_downward_delta_16f
max_downward_velocity_16f
center_y_trend_score
aspect_ratio_change_16f
bbox_bottom_stability_16f
low_posture_duration_ms
horizontal_posture_duration_ms
recovery_upward_score_16f
post_drop_speed_min_16f
```

### 4.3 修改 TemporalService

在 `TemporalService._enrich_one()` 中：

```text
feature = extract current frame
window = FeatureWindow.get_window(key)
motion_features = TemporalMotionFeatureBuilder.build(window)
```

然后先将这些字段放进 `temporal` payload：

```json
{
  "motion_features": {
    "cumulative_drop_16f": 0.42,
    "bbox_bottom_stability_16f": 0.83,
    "recovery_upward_score_16f": 0.12
  }
}
```

### 4.4 验收

新增字段必须满足：

```text
线上/离线均不报错。
窗口不足时能返回默认值。
字段数值在 0~1 或明确单位范围内。
不影响现有 fallen_confirmed 结果。
```

## 5. 阶段 2：新增 fall_evidence_score

### 5.1 新增模块

新增 `app/temporal/fall_evidence_scorer.py`。

职责：

```text
把 LSTM 概率、运动特征、姿态特征组合成跌倒正证据评分。
```

### 5.2 输入

```text
SequencePrediction
TargetFeature
FeatureWindow
TemporalMotionFeatures
Settings
```

### 5.3 输出

建议新增 Pydantic schema：

```text
FallEvidenceScores
```

字段：

```text
fall_evidence_score
vertical_drop_score
aspect_ratio_change_score
low_posture_score
impact_proxy_score
post_fall_stillness_score
floor_contact_score
reasons
```

### 5.4 初始评分逻辑

```text
fall_evidence_score =
  0.30 * fall_probability
+ 0.18 * vertical_drop_score
+ 0.14 * aspect_ratio_change_score
+ 0.12 * low_posture_score
+ 0.10 * impact_proxy_score
+ 0.10 * post_fall_stillness_score
+ 0.06 * floor_contact_score
```

所有子分数先控制在 0~1。

### 5.5 验收

测试用例：

```text
快速下坠 + 横向 + 静止 -> fall_evidence_score 高
站立不动 -> fall_evidence_score 低
弯腰但无髋部下降 -> 中低
坐下但 bbox_bottom 稳定 -> 中低
慢速倒地无恢复 -> 中高，但不走 fast path
```

## 6. 阶段 3：新增 ADL 反证据评分

### 6.1 新增模块

新增 `app/temporal/adl_suppressor.py`。

职责：

```text
识别“像跌倒但更像日常动作”的反证据。
```

### 6.2 输出

建议新增 Pydantic schema：

```text
ADLSuppressionScores
```

字段：

```text
adl_suppression_score
sitting_score
bending_score
normal_lying_score
squatting_score
controlled_descent_score
support_surface_score
recovery_score
track_instability_score
reasons
```

### 6.3 初始评分逻辑

```text
adl_suppression_score =
  0.18 * sitting_score
+ 0.18 * bending_score
+ 0.16 * normal_lying_score
+ 0.12 * squatting_score
+ 0.14 * controlled_descent_score
+ 0.10 * support_surface_score
+ 0.08 * recovery_score
+ 0.04 * track_instability_score
```

### 6.4 四类重点 ADL 分支

1. 弯腰：

```text
head 下降明显
hip 下降不明显
bbox_bottom 稳定
aspect_ratio 不持续横向
短时间恢复
```

2. 坐下：

```text
center_y 缓慢下降
bbox_bottom 稳定
最终非横躺
support_surface_score 高
```

3. 主动躺卧：

```text
transition_duration_ms > 2500
max_downward_speed 不高
impact_proxy_score 低
support_surface_score 高
```

4. 蹲下/跪下：

```text
bbox_height 变短
bbox_bottom 稳定
aspect_ratio 不横向
后续恢复
```

### 6.5 验收

必须覆盖测试：

```text
弯腰捡东西不 confirmed
坐下后静止 10 秒不 confirmed
主动躺床不 confirmed
蹲下后站起不 confirmed
track 丢失不直接 confirmed
```

## 7. 阶段 4：升级状态机 v6

### 7.1 状态扩展

在 `FallState` 中增加或内部运行时增加：

```text
MOTION_OBSERVE
SLOW_FALL_CANDIDATE
SLOW_LOW_POSTURE_HOLD
ADL_SUPPRESSED
RECOVERY_OBSERVED
UNCERTAIN_REVIEW
LOW_RISK_OBSERVE
```

如果担心前端兼容，可以先不改变公开 `fall_state` 枚举，只在 debug 字段中输出 `motion_path`：

```text
fall_state 仍使用 normal/unstable/falling/fallen_candidate/fallen_confirmed/cooldown
motion_path 输出 fast_fall_path/slow_fall_path/adl_suppressed/uncertain_review
```

推荐先采用兼容方案。

### 7.2 快速跌倒路径

进入快速路径：

```text
fall_probability >= 0.55
vertical_drop_score 高
fall_evidence_score >= 0.65
adl_suppression_score < 0.60
track_quality_score >= 0.70
```

确认快速跌倒：

```text
fall_evidence_score >= 0.75
adl_suppression_score < 0.45
post_fall_hold_ms >= 1500
candidate_frames >= 5
recovery_score < 0.40
track_quality_score >= 0.70
```

### 7.3 慢速跌倒路径

进入慢速候选：

```text
cumulative_drop_32f 中高
continuous_descent_score 高
low_posture_score 逐步升高
recovery_score 低
adl_suppression_score < 0.65
```

确认慢速跌倒：

```text
low_posture_hold_ms >= 5000
recovery_score < 0.30
support_surface_score < 0.40
floor_contact_score >= 0.60
track_quality_score >= 0.70
adl_suppression_score < 0.55
```

### 7.4 ADL 抑制

如果满足：

```text
adl_suppression_score >= 0.65
且 fall_evidence_score < 0.80
且 impact_proxy_score 低
```

则：

```text
motion_path = adl_suppressed
fall_state 不进入 fallen_confirmed
rejected_reason = adl_suppression
```

### 7.5 不确定分支

如果：

```text
track_quality_score < 0.50
或 bbox_jump_score 高
或 heavy occlusion
```

则：

```text
motion_path = uncertain_review
不允许直接 fallen_confirmed
```

### 7.6 事件锁

新增运行时字段：

```text
fall_latched
fall_session_id
last_confirmed_at
```

触发后：

```text
同一 key 在 cooldown 期间不重复 confirmed。
只有 recovery_observed 或目标离开后重置。
```

## 8. 阶段 5：配置项设计

在 `app/core/config.py` 中新增配置，默认先保守开启 debug，决策可灰度：

```text
FALL_V6_SCORING_ENABLED=true
FALL_V6_DECISION_ENABLED=false
FALL_V6_DEBUG_PAYLOAD=true

FALL_EVIDENCE_CONFIRM_THRESHOLD=0.75
ADL_SUPPRESSION_CONFIRM_MAX=0.45
ADL_SUPPRESSION_SLOW_MAX=0.55
TRACK_QUALITY_MIN_CONFIRM=0.70

SLOW_FALL_ENABLED=true
SLOW_FALL_HOLD_MS=5000
SLOW_FALL_FLOOR_CONTACT_MIN=0.60
SLOW_FALL_SUPPORT_SURFACE_MAX=0.40

RECOVERY_CANCEL_THRESHOLD=0.60
UNCERTAIN_TRACK_QUALITY_MIN=0.50
```

灰度策略：

```text
先 FALL_V6_SCORING_ENABLED=true，FALL_V6_DECISION_ENABLED=false。
确认评分合理后，再切 FALL_V6_DECISION_ENABLED=true。
```

## 9. 阶段 6：前端与接口可解释性

### 9.1 Temporal payload

建议 `temporal` 中新增：

```json
{
  "fall_evidence_score": 0.82,
  "adl_suppression_score": 0.21,
  "motion_path": "fast_fall_path",
  "decision_reason": [
    "high_lstm_probability",
    "fast_vertical_drop",
    "low_posture_persisted",
    "post_fall_stillness"
  ]
}
```

### 9.2 Fall decision payload

建议 `fall_decision` 中新增：

```text
motion_path
suppressed_by_adl
uncertain_review
fall_latched
incident_dedup_key
```

### 9.3 目标

每一次误报/漏报都能回答：

```text
为什么报警？
为什么没有报警？
是 LSTM 概率问题，还是状态机判断问题？
是 ADL 抑制过强，还是跌倒正证据不足？
```

## 10. 阶段 7：测试计划

### 10.1 单元测试

新增测试：

```text
tests/test_fall_evidence_scorer.py
tests/test_adl_suppressor.py
tests/test_fall_state_machine_v6.py
```

核心用例：

```text
快速跌倒 -> fast_fall_path -> fallen_confirmed
慢速倒地 5 秒 -> slow_fall_path -> fallen_confirmed
慢速倒地 2 秒 -> slow_fall_candidate，但不 confirmed
弯腰后站起 -> bending_suppressed
坐下保持静止 -> sitting_down_suppressed
主动躺床 -> normal_lying_suppressed
蹲下后站起 -> squat_kneel_suppressed
track 跳变 -> uncertain_review
confirmed 后 10 秒内不重复报警
recovery 后允许新一轮事件
```

### 10.2 服务级测试

扩展：

```text
tests/test_temporal_service.py
tests/test_fall_state_machine_debug.py
tests/test_end_to_end_pipeline.py
```

验证：

```text
temporal payload 包含新评分字段
旧字段仍兼容前端
FALL_V6_DECISION_ENABLED=false 时不改变旧决策
FALL_V6_DECISION_ENABLED=true 时启用新状态机
```

### 10.3 离线回放测试

建立：

```text
evaluations/fall_temporal_v6/
  baseline_before_v6.json
  scoring_shadow_eval.json
  decision_enabled_eval.json
  fp_regression_summary.json
  slow_fall_summary.json
```

## 11. 阶段 8：数据集与人工审核计划

### 11.1 fp_regression

目录：

```text
datasets/fp_regression/
  sitting_down_fast/
  sitting_down_slow/
  bending_pick_object/
  squatting/
  kneeling/
  lying_down_bed/
  lying_down_floor_normal/
  half_body/
  occlusion/
  multi_person_crossing/
```

每类先 5 到 10 段。

### 11.2 slow_fall

目录：

```text
datasets/slow_fall_review/
  slow_fall_floor/
  wall_supported_slow_fall/
  chair_edge_slide_to_floor/
  bed_edge_slide_to_floor/
  weak_kneel_then_cannot_recover/
```

### 11.3 审核字段

```text
video_id
expected_decision
expected_path
fall_start_frame
fall_end_frame
scene_zone
support_surface_type
non_fall_subtype
hard_negative
review_status
notes
```

## 12. 阶段 9：验收指标

v6 启用前必须满足：

```text
快速跌倒 confirmed recall 不低于 v5 baseline。
慢速跌倒地面风险区 5~10 秒样本能触发一次告警。
坐下、弯腰、主动躺卧、蹲跪 confirmed FP 明显下降。
confirmed 后同一 track 不重复报警。
uncertain_review 不被误当作 normal 成功。
debug reason 可解释每个关键判断。
```

建议量化目标：

```text
fp_regression confirmed_false_positive_count 下降 >= 50%
slow_fall confirmed_recall >= 80%
fast_fall confirmed_recall 下降不超过 5%
重复报警率 = 0
状态机异常错误 = 0
```

## 13. 阶段 10：是否训练 LSTM v6 的决策门槛

只有满足以下情况，才进入 LSTM v6 训练：

```text
状态机 v6 已经降低明显误报，但仍存在系统性混淆。
回归集显示 LSTM probability 本身对 ADL/fall 区分不足。
已经有足够人工审核的时序数据。
已经修复离线速度特征 time.monotonic 问题。
已经改进窗口标签，不再“任意帧 fall 即正样本”。
```

如果进入 LSTM v6，再做：

```text
phase-aware labels
video-fps-based velocity
hard negative balance
window-level validation metrics
ONNX export and schema v2
shadow mode comparison
```

## 14. 推荐实施顺序

最稳妥的施工顺序：

```text
1. 新增 motion feature builder，只输出 debug，不改决策。
2. 新增 fall_evidence_scorer，只输出 debug，不改决策。
3. 新增 adl_suppressor，只输出 debug，不改决策。
4. 加配置开关 FALL_V6_DECISION_ENABLED=false。
5. 扩展状态机 v6，但默认 shadow。
6. 编写单元测试和场景测试。
7. 建 fp_regression 和 slow_fall 回归集。
8. 回放 baseline vs v6 shadow。
9. 审核通过后启用 v6 decision。
10. 根据效果决定是否训练 LSTM v6。
```

## 15. 风险与回滚

### 15.1 主要风险

```text
ADL 抑制过强导致真实跌倒漏报。
慢速跌倒路径过宽导致主动躺卧误报。
track_quality 误判导致真实跌倒进入 uncertain_review。
场景区域未配置时 support_surface_score 不可靠。
前端/接口不兼容新增状态。
```

### 15.2 回滚方案

必须保留配置回滚：

```text
FALL_V6_DECISION_ENABLED=false
```

这样即使评分模块存在，也不会影响旧状态机确认逻辑。

### 15.3 灰度建议

```text
先在 shadow 模式跑 1 到 3 天。
记录 v5 决策与 v6 决策差异。
只人工审核差异样本。
教授确认后再切主动决策。
```

## 16. 最终结论

当前系统的下一步优化应以状态机和时序融合逻辑为主，不应直接跳到重训 LSTM 或更换模型结构。

本计划推荐：

```text
先补可解释评分。
再补 ADL 反证据。
再补慢速跌倒兜底。
再建立回归集。
最后再决定是否训练 LSTM v6。
```

这样可以在最小工程风险下解决当前最核心的问题：真实跌倒与弯腰、坐下、主动躺卧等相似动作之间的误判。

