# 跌倒检测状态机 v6 逻辑审核与优化计划

日期：2026-07-03  
项目：`D:\Program\vision_service`  
审核主题：`fall_state_machine_v6_logic_review`  
目标：降低弯腰、坐下、主动躺卧、蹲跪、遮挡等 ADL 动作误报，同时补充慢速跌倒兜底路径。

## 1. 背景与核心判断

当前系统已经具备“YOLO/姿态/跟踪 -> LSTM 时序概率 -> 状态机确认 -> 告警”的完整闭环。现有确认逻辑大致是：

```text
fall_probability >= 0.65
最近有快速下坠
姿态足够低
动作后足够静止
候选状态持续至少 5 帧
候选状态持续至少 1500ms
```

这套逻辑能覆盖很多快速跌倒，但面对真实场景会出现两个方向的问题：

1. **误报**：弯腰、坐下、短暂躺卧、蹲下、跪下等 ADL 动作会产生“身体变低、框变宽、动作后静止”等相似特征。
2. **漏报**：老人虚弱滑倒、扶墙慢慢倒下、缓慢失去平衡等慢速跌倒可能没有明显快速下坠，无法满足“快速下坠”硬条件。

因此当前问题不是简单调高或调低阈值，而是状态机缺少两个关键能力：

```text
ADL 反证据分支：判断它是否更像正常日常动作。
慢速跌倒兜底路径：在无快速下坠时，仍能基于长期低姿态、无恢复、地面风险区域确认跌倒。
```

本方案建议短期先升级状态机，不立即重训 LSTM，也不立即改变 ONNX 输入维度。

## 2. 优化原则

### 2.1 不再只问“像不像跌倒”

当前系统主要在累积正证据：

```text
LSTM 概率高
下坠明显
低姿态
静止
持续
```

v6 应同时反向检查：

```text
它是否更像坐下？
它是否更像弯腰？
它是否更像主动躺卧？
它是否更像蹲下/跪下？
它是否出现了恢复趋势？
它是否发生在床/沙发/椅子等支撑区域？
它是否只是 track 丢失、遮挡或检测框异常？
```

最终确认不应是：

```text
fall_probability 高 -> 报警
```

而应是：

```text
跌倒正证据足够
ADL 反证据不足
目标跟踪质量可靠
没有恢复趋势
支撑区域证据不强
-> fallen_confirmed
```

### 2.2 快速跌倒和慢速跌倒分开处理

建议将跌倒分为两条确认路径：

```text
路径 A：fast_fall_path
路径 B：slow_fall_path
```

路径 A 处理突然摔倒，确认快。  
路径 B 处理缓慢滑倒、虚弱倒下、扶墙慢慢倒下，确认慢，但不能漏掉。

## 3. v6 新增核心评分

### 3.1 fall_evidence_score

表示“当前时序证据支持跌倒”的程度。

建议组成：

```text
fall_probability
vertical_drop_score
aspect_ratio_change_score
low_posture_score
impact_proxy_score
post_fall_stillness_score
floor_contact_score
```

初始权重建议：

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

说明：

- `fall_probability` 来自现有 LSTM。
- `vertical_drop_score` 不只看单帧 `delta_y > 40`，应看最近 8/16/32 帧累计下降、最大下降、下降突发性。
- `aspect_ratio_change_score` 看身体框是否从竖向转为横向。
- `low_posture_score` 看 bbox、头部、髋部是否进入低位。
- `impact_proxy_score` 不是检测真实撞击，而是用“快速下降后速度骤降、框形态突变、低姿态保持”近似判断。
- `floor_contact_score` 在没有场景区域标定时，可先用 bbox 下边缘、center_y、head/hip 高度比例近似。

### 3.2 adl_suppression_score

表示“当前动作更像非跌倒 ADL”的程度。

建议组成：

```text
sitting_score
bending_score
normal_lying_score
squatting_score
controlled_descent_score
support_surface_score
recovery_score
track_instability_score
```

初始权重建议：

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

注意：`track_instability_score` 高时，不应简单判定为正常，而应进入 `uncertain_review`。因为检测/跟踪不稳定时，既可能是假阳性，也可能是真跌倒被检测坏了。

### 3.3 recovery_score

表示目标是否出现恢复趋势。

建议证据：

```text
bbox_center_y 回升
bbox_height 恢复到站立/坐姿高度
aspect_ratio 从横向回到竖向
head_height_ratio / hip_height_ratio 恢复
速度从低姿态向上移动
```

如果在 1.5 到 3 秒内出现强恢复趋势，应撤销候选：

```text
fallen_candidate -> recovery_observed
```

### 3.4 track_quality_score

表示当前目标轨迹是否可信。

建议降低质量的情况：

```text
track_id 中途换人
bbox 突然跳变
多人交叉
遮挡严重
人体框忽然包含大量背景/家具
连续多帧检测缺失
pose 与 bbox 明显矛盾
```

建议：

```text
track_quality_score < 0.70 时，不允许直接 fallen_confirmed。
```

## 4. ADL 反证据分支

### 4.1 bending_suppressed：弯腰抑制

弯腰和跌倒相似点：

```text
头部下降
torso_angle 变化
bbox 高度变化
短时速度升高
```

弯腰区别点：

```text
髋部/下半身位置相对稳定
bbox_bottom 基本稳定
髋部高度下降不明显
身体不会长期横向贴近地面
动作后通常恢复站立
```

建议规则：

```text
如果 head_height_ratio 明显下降
且 hip_height_ratio 下降不明显
且 bbox_bottom 稳定
且 aspect_ratio 未持续 > 1.0
且 1.5s 到 3s 内出现恢复
则进入 bending_suppressed，不允许 fallen_confirmed
```

典型 decision_reason：

```text
bending_like_motion
bbox_bottom_stable
hip_not_low
quick_recovery
```

### 4.2 sitting_down_suppressed：坐下抑制

坐下和跌倒相似点：

```text
中心点下降
动作后静止
姿态变低
```

坐下区别点：

```text
下降过程更平滑
bbox_bottom 通常接近固定
最终仍是坐姿，不是横躺
位置常在椅子/床/沙发高度
aspect_ratio 不长期明显横向
```

建议规则：

```text
如果 bbox_center_y 缓慢下降
且 bbox_bottom 基本稳定
且 aspect_ratio 没有持续横向
且 low posture 不是 floor-level
且 support_surface_score 高
则进入 sitting_down_suppressed
```

典型 decision_reason：

```text
controlled_descent
bbox_bottom_stable
sitting_posture
support_surface_likely
```

### 4.3 normal_lying_suppressed：主动躺卧抑制

主动躺卧最容易与跌倒混淆，因为它同样可能出现：

```text
低姿态
横向 bbox
长时间静止
LSTM 概率升高
```

区别点：

```text
进入低姿态过程较慢
没有快速下坠或撞击代理证据
常发生在床/沙发/休息垫等支撑区
动作更平滑
```

建议规则：

```text
如果 transition_duration_ms > 2500ms
且 max_downward_speed 不高
且 impact_proxy_score 低
且 support_surface_score 高
则进入 normal_lying_suppressed 或 low_risk_observe
```

注意：如果没有场景区域信息，不能永久排除。老人缓慢滑落也可能是危险事件。因此如果目标处于地面风险区并持续低姿态无恢复，应走慢速跌倒兜底。

### 4.4 squat_kneel_suppressed：蹲下/跪下抑制

蹲跪和跌倒相似点：

```text
身体高度下降
中心点下移
短暂静止
```

区别点：

```text
bbox_bottom 稳定
身体没有横向倒地
aspect_ratio 通常不持续横向
髋部不会接近地面到倒地程度
常有恢复站立
```

建议规则：

```text
如果 bbox_height 变短
且 bbox_bottom 稳定
且 center_y 下降但 aspect_ratio 不横向
且之后出现恢复
则进入 squat_kneel_suppressed
```

## 5. 慢速跌倒兜底路径

### 5.1 适用场景

用户和教授讨论的关键场景：

```text
画面中一个人站在目标区域
缓慢倒下
在目标区域躺 5 到 10 秒
```

这个场景应该判断为跌倒一次，但不应该走快速跌倒路径，也不应该在 1.5 秒内快速确认。

建议判断为：

```text
疑似慢速跌倒 -> 低姿态保持 -> 无恢复 -> 触发一次跌倒告警
```

### 5.2 slow_fall_candidate 条件

进入 `slow_fall_candidate` 的建议条件：

```text
最近 2 到 5 秒内 bbox_center_y 持续下降
head_height_ratio / hip_height_ratio 持续变低
最终进入 low_posture
下降趋势连续存在
没有明显快速恢复
max_downward_speed 不一定高
adl_suppression_score 不能很高
track_quality_score 可靠
```

### 5.3 slow_low_posture_hold 条件

进入 `slow_low_posture_hold` 的建议条件：

```text
low_posture 持续
aspect_ratio 或 head/hip 高度表明接近躺卧/倒地
speed 较低
recovery_score 低
目标在 floor/risk zone，而非 bed/sofa/chair/support zone
```

### 5.4 慢速确认条件

慢速路径确认建议更保守：

```text
low_posture_hold_ms >= 5000
recovery_score < 0.30
support_surface_score < 0.40
floor_contact_score >= 0.60
track_quality_score >= 0.70
adl_suppression_score < 0.55
```

说明：

- 快速跌倒可在 1500ms 左右确认。
- 慢速跌倒建议至少 5000ms 才确认。
- 如果躺在床/沙发/椅子等正常支撑区域，不应直接确认，应进入 `normal_lying_suppressed` 或 `low_risk_observe`。

### 5.5 该场景最终结论

如果一个人在地面风险区域缓慢倒下，并躺 5 到 10 秒：

```text
应该触发一次 fallen_confirmed。
```

但确认路径应是：

```text
normal
-> motion_observe
-> slow_fall_candidate
-> slow_low_posture_hold
-> fallen_confirmed
-> cooldown / latched
```

如果同样动作发生在床、沙发、休息垫、护理床区域：

```text
不应直接判断为跌倒。
应进入 normal_lying_suppressed 或 low_risk_observe。
```

## 6. v6 状态机设计

### 6.1 主状态

建议状态：

```text
normal
motion_observe
falling_candidate
impact_or_low_contact
fallen_hold
slow_fall_candidate
slow_low_posture_hold
fallen_confirmed
cooldown
```

### 6.2 旁路状态

建议旁路状态：

```text
adl_suppressed
recovery_observed
uncertain_review
low_risk_observe
```

### 6.3 快速跌倒路径

```text
normal
  -> motion_observe
     条件：
       fall_probability >= 0.45
       或 low_posture_score 升高
       或 vertical_drop_score 升高

motion_observe
  -> falling_candidate
     条件：
       fall_probability >= 0.55
       vertical_drop_score 高
       adl_suppression_score < 0.60
       track_quality_score >= 0.70

falling_candidate
  -> impact_or_low_contact
     条件：
       transition_duration_ms 较短
       aspect_ratio_change_score 高
       low_posture_score 高
       impact_proxy_score 中高

impact_or_low_contact
  -> fallen_hold
     条件：
       post_fall_stillness_score 高
       low_posture 持续
       recovery_score 低

fallen_hold
  -> fallen_confirmed
     条件：
       fall_evidence_score >= 0.75
       adl_suppression_score < 0.45
       post_fall_hold_ms >= 1500
       candidate_frames >= 5
       recovery_score < 0.40
       track_quality_score >= 0.70
```

### 6.4 慢速跌倒路径

```text
motion_observe
  -> slow_fall_candidate
     条件：
       cumulative_drop_32f 中高
       continuous_descent_score 高
       low_posture_score 逐步升高
       vertical_drop_score 不一定高
       recovery_score 低
       adl_suppression_score < 0.65

slow_fall_candidate
  -> slow_low_posture_hold
     条件：
       low_posture_score 高
       speed 较低
       floor_contact_score 中高
       support_surface_score 低
       recovery_score 低

slow_low_posture_hold
  -> fallen_confirmed
     条件：
       low_posture_hold_ms >= 5000
       recovery_score < 0.30
       support_surface_score < 0.40
       floor_contact_score >= 0.60
       track_quality_score >= 0.70
       adl_suppression_score < 0.55
```

### 6.5 抑制与不确定路径

```text
任意候选状态
  -> adl_suppressed
     条件：
       sitting_score / bending_score / normal_lying_score / squatting_score 明显高
       且无强下坠、无 impact_proxy、无长时间地面低姿态

任意候选状态
  -> recovery_observed
     条件：
       center_y 回升
       bbox_height 恢复
       aspect_ratio 回到竖向
       head/hip 高度恢复

任意状态
  -> uncertain_review
     条件：
       track_switch
       bbox 严重跳变
       heavy occlusion
       多人交叉
       bbox/pose 矛盾严重
```

## 7. 一次事件锁与去重

对于“倒地后躺 5 到 10 秒”的场景，系统只能报一次，不能每隔几秒重复报警。

建议新增事件锁：

```text
fall_latched = true
incident_dedup_key = camera_id + temporal_key + fall_session_id
```

触发后：

```text
fallen_confirmed -> cooldown
```

同一个目标在 cooldown 或 latched 期间不再重复触发，除非出现以下释放条件：

```text
目标恢复站立/坐起
目标离开画面并超时
人工处理完成
冷却时间结束且状态回到 normal
```

## 8. 建议新增的运行时字段

短期建议不改 ONNX 输入，先在状态机外部计算扩展特征，并输出到 `temporal` payload，方便审核。

建议新增字段：

```text
fall_evidence_score
adl_suppression_score
sitting_score
bending_score
normal_lying_score
squatting_score
controlled_descent_score
recovery_score
track_quality_score
floor_contact_score
support_surface_score
impact_proxy_score
transition_duration_ms
low_posture_hold_ms
motion_path
decision_reason
```

示例输出：

```json
{
  "fall_evidence_score": 0.82,
  "adl_suppression_score": 0.21,
  "motion_path": "fast_fall_path",
  "decision_reason": [
    "high_lstm_probability",
    "fast_vertical_drop",
    "low_posture_persisted",
    "post_fall_stillness",
    "no_adl_suppression"
  ]
}
```

误报抑制样本示例：

```json
{
  "fall_evidence_score": 0.68,
  "adl_suppression_score": 0.74,
  "motion_path": "adl_suppressed",
  "decision_reason": [
    "controlled_descent",
    "bbox_bottom_stable",
    "quick_recovery",
    "bending_like_motion"
  ]
}
```

## 9. 数据与人工审核要求

### 9.1 建立 fp_regression 回归集

建议先建立误报回归集，而不是立刻大规模重训：

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
  slow_fall_floor/
```

每类先收集 5 到 10 段即可，重点是可解释、可复现、可回放。

### 9.2 审核字段

建议每段视频记录：

```text
video_id
binary_label
non_fall_subtype
fall_start_frame
fall_impact_frame
fall_end_frame
scene_zone
support_surface_type
hard_negative
track_quality
bbox_quality
pose_quality
occlusion_level
body_visible
expected_decision
review_status
notes
```

### 9.3 慢速跌倒专项数据

必须单独补充：

```text
老人缓慢滑倒
扶墙慢慢倒下
从椅边/床边滑落到地面
虚弱蹲下后无法恢复
缓慢倒下后躺地 5 到 10 秒
```

这些样本用于验证 slow_fall_path，不能只依赖快速摔倒数据。

## 10. 实施计划

### 阶段 1：文档审核与阈值冻结

目标：

```text
确认是否接受 v6 双评分 + 多路径状态机方向。
确认是否先不改 ONNX。
确认慢速跌倒是否以 5 秒低姿态保持作为初始阈值。
确认支撑区域/风险区域的业务定义。
```

产出：

```text
docs/fall_state_machine_v6_logic_review_20260703.md
审核意见
初始阈值表
```

### 阶段 2：只增强状态机，不改模型

建议新增模块：

```text
app/temporal/fall_evidence_scorer.py
app/temporal/adl_suppressor.py
app/temporal/scene_context.py
```

其中 `scene_context.py` 可先提供默认值，后续再接入手工配置的床/沙发/椅子/地面区域。

改造重点：

```text
FallStateMachine.update() 接收扩展评分
TemporalService 输出评分和 decision_reason
保持 LSTM ONNX 输入 15 维不变
保持原有 v5 模型可运行
```

### 阶段 3：建立回归集并离线评估

评估指标：

```text
confirmed_false_positive_count
adl_suppressed_count
uncertain_review_count
slow_fall_confirmed_count
fall_missed_count
first_candidate_delay_ms
first_confirmed_delay_ms
decision_reason 分布
```

必须分别评估：

```text
快速跌倒
慢速跌倒
坐下
弯腰
主动躺卧
蹲跪
遮挡/半身
多人交叉
```

### 阶段 4：决定是否训练 LSTM v6

只有在状态机增强后仍存在大量误报/漏报时，再训练 LSTM v6。

训练前必须修复：

```text
窗口标签不能继续使用“任意帧 fall 即正样本”的粗标签。
离线速度特征应改成基于 video fps / frame_seq，而不是 time.monotonic()。
```

如果训练 v6，再考虑新增特征 schema，而不是直接修改当前线上 15 维模型。

## 11. 初始阈值建议

以下阈值仅作为 v6 初始审核值，必须通过 `fp_regression` 和 `test_frozen` 回放校准：

```text
fall_probability_fast_entry = 0.55
fall_probability_confirm = 0.65
fall_evidence_confirm = 0.75
adl_suppression_confirm_max = 0.45
adl_suppression_slow_max = 0.55
track_quality_min = 0.70
fast_post_fall_hold_ms = 1500
fast_candidate_frames = 5
slow_low_posture_hold_ms = 5000
recovery_score_cancel = 0.60
recovery_score_confirm_max_fast = 0.40
recovery_score_confirm_max_slow = 0.30
support_surface_slow_max = 0.40
floor_contact_slow_min = 0.60
```

## 12. 场景判断表

| 场景 | 建议判断 | 路径 |
| --- | --- | --- |
| 快速摔倒，躺地 2 秒以上 | 跌倒 | fast_fall_path |
| 缓慢倒下，躺在地面目标区 5 到 10 秒 | 跌倒一次 | slow_fall_path |
| 缓慢躺到床/沙发 5 到 10 秒 | 不直接报警 | normal_lying_suppressed / low_risk_observe |
| 弯腰 2 秒后站起 | 不报警 | bending_suppressed / recovery_observed |
| 坐下后保持坐姿 10 秒 | 不报警 | sitting_down_suppressed |
| 蹲下捡东西后站起 | 不报警 | squat_kneel_suppressed / recovery_observed |
| track 丢失后画面像静止 | 不直接确认 | uncertain_review |
| 半身入画后框变横 | 不直接确认 | uncertain_review 或 low_risk_observe |

## 13. 对外说明口径

建议后续对外或对评审说明：

```text
系统没有将 LSTM 概率直接作为跌倒报警依据，而是采用“时序概率 + 多阶段状态机 + ADL 反证据抑制”的融合策略。

系统首先利用 LSTM 判断最近 32 帧轨迹是否像跌倒；随后状态机检查是否存在失控下坠、低姿态、疑似接触地面、倒地后静止等正证据。同时，系统反向识别坐下、弯腰、主动躺卧、蹲跪、遮挡和跟踪异常等日常动作或低质量证据。

只有当跌倒正证据持续成立，ADL 反证据不足，目标跟踪质量可靠，并且没有恢复动作时，系统才进入 fallen_confirmed 并触发告警。对于缓慢滑倒等无快速下坠场景，系统采用慢速跌倒兜底路径，以更长低姿态保持和无恢复作为确认条件。
```

## 14. 最终建议

当前最稳妥的升级路径：

```text
第一，不急着改 LSTM 结构。
第二，先增强状态机，补充 ADL 反证据分支。
第三，增加慢速跌倒兜底路径。
第四，建立 fp_regression 回归集，专门验证误报动作。
第五，根据回放结果再决定是否训练 LSTM v6。
```

本方案的核心目标是让系统不只会判断“像跌倒”，还会判断“是否更像非跌倒日常动作”。这比单纯调阈值更稳定，也更符合当前工程架构。

