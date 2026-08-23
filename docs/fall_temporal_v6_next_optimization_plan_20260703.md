# 跌倒检测时序模型 v6 后续优化计划

日期：2026-07-03  
项目路径：`D:\Program\vision_service`  
目标：在现有 LSTM 时序概率基础上，完善状态机和时序证据逻辑，降低弯腰、坐下、短暂躺卧等 ADL 动作误报，同时补偿慢速跌倒漏报。

## 1. 当前判断

当前问题不应只理解为阈值不合适。真实跌倒与日常动作存在大量相似特征：

```text
身体高度降低
bbox 形态改变
短时间运动速度升高
动作后静止
LSTM fall_probability 升高
```

如果系统只判断：

```text
fall_probability >= 0.65
最近有快速下坠
姿态足够低
动作后足够静止
候选状态持续 5 帧
候选状态持续 1500ms
```

则会出现两类风险：

```text
误报：弯腰、坐下、蹲下、跪下、主动躺卧被当作跌倒
漏报：老人缓慢滑倒、扶墙慢慢倒下、虚弱倒地没有明显快速下坠
```

因此 v6 的核心不是简单调高或调低阈值，而是把判断改为：

```text
跌倒正证据足够
ADL 反证据不足
目标轨迹质量可靠
没有恢复趋势
不在床/沙发/椅子等正常支撑区域
同一事件只报警一次
```

## 2. 总体技术路线

### 2.1 保留现有 LSTM

短期不修改：

```text
models/fall_lstm_v5.onnx
models/fall_lstm_v5_features.json
app/temporal/feature_vectorizer.py 的 15 维输入
```

原因：

```text
当前 LSTM 可以提供有价值的时序概率
当前数据集规模不足，不宜先改网络结构
误报主要来自确认逻辑缺少反证据分支
先完善状态机可以更快验证效果
```

### 2.2 新增 v6 时序融合层

建议形成三层判断：

```text
第一层：LSTM 给出 fall_probability
第二层：v6 scorer 计算 fall_evidence_score 和 adl_suppression_score
第三层：FallStateMachine 根据路径确认、抑制或进入人工复核
```

核心路径：

```text
fast_fall_path：快速跌倒，确认更快
slow_fall_path：慢速跌倒兜底，确认更慢
adl_suppressed：更像日常动作，抑制告警
uncertain_review：证据冲突或跟踪质量差，进入复核
fall_latched：同一跌倒事件锁定，只报警一次
```

## 3. 状态机目标逻辑

### 3.1 快速跌倒路径

适用场景：

```text
突然摔倒
快速下坠
倒地后短时间静止
有明显姿态从竖向变为横向
```

建议确认逻辑：

```text
fall_evidence_score >= 0.70
vertical_drop_score >= 0.60
low_posture_score >= 0.55
post_fall_stillness_score >= 0.50
adl_suppression_score < 0.55
recovery_score < 0.35
track_quality_score >= 0.70
hold_ms >= 1500
=> fallen_confirmed, motion_path = fast_fall_path
```

### 3.2 慢速跌倒兜底路径

适用场景：

```text
站立后缓慢倒下
扶墙缓慢下滑
坐椅边缘滑落到地面
虚弱跪倒后无法恢复
没有明显快速下坠，但最终长期低姿态无恢复
```

建议确认逻辑：

```text
最近 2 到 5 秒存在持续下降趋势
最终进入低姿态或接近地面
low_posture_duration_ms >= 5000
post_fall_stillness_score >= 0.60
recovery_score < 0.30
support_surface_score < 0.55
adl_suppression_score < 0.60
track_quality_score >= 0.70
=> fallen_confirmed, motion_path = slow_fall_path
```

重要口径：

```text
慢速跌倒不应因为没有快速下坠而漏报
慢速跌倒也不应在 1.5 秒内立刻报警
慢速跌倒应通过长期低姿态、无恢复、地面风险区域来确认
```

### 3.3 ADL 抑制路径

ADL 反证据包括：

```text
bending_score：弯腰
sitting_score：坐下
squatting_score：蹲下/跪下
normal_lying_score：主动躺卧
controlled_descent_score：受控缓慢下降
support_surface_score：床、沙发、椅子等支撑区域
recovery_score：短时间内恢复站立/坐起
track_instability_score：跟踪异常
```

建议抑制逻辑：

```text
adl_suppression_score >= 0.65
且 fall_evidence_score < 0.85
=> adl_suppressed
```

如果证据冲突：

```text
fall_evidence_score 高
adl_suppression_score 也高
或者 track_quality_score 低
=> uncertain_review
```

### 3.4 事件锁

同一个人倒地后 5 到 10 秒不能重复报警。

建议逻辑：

```text
fallen_confirmed 后设置 fall_latched = true
同一 camera_id + track_id + fall_session_id 不重复触发
直到出现 recovery、目标离开画面、冷却结束或人工处理完成
```

## 4. 数据集建设计划

### 4.1 需要新增两类验证集

第一类：`fp_regression`，专门测试误报。

```text
sitting_down_fast
sitting_down_slow
bending_pick_object
squatting
kneeling
normal_lying_bed
normal_lying_sofa
normal_lying_floor_short
half_body_entering
occlusion
multi_person_crossing
track_lost_static_scene
```

第二类：`slow_fall_review`，专门测试慢速跌倒漏报。

```text
slow_fall_floor
wall_supported_slow_fall
chair_edge_slide_to_floor
bed_edge_slide_to_floor
weak_kneel_then_cannot_recover
standing_to_floor_no_impact
```

### 4.2 每条视频必须标注的信息

建议 manifest 字段：

```json
{
  "video": "path/to/video.mp4",
  "label": "fall",
  "expected_alarm": true,
  "scene_type": "floor_risk_area",
  "hard_negative_type": null,
  "fall_start_ms": 3200,
  "low_posture_start_ms": 4700,
  "expected_confirm_after_ms": 5000,
  "support_surface": "none",
  "person_count": 1,
  "occlusion_level": "low",
  "review_status": "approved",
  "reviewer": "professor_or_engineer",
  "notes": "slow fall, no clear impact"
}
```

ADL 负样本示例：

```json
{
  "video": "path/to/bending.mp4",
  "label": "adl",
  "expected_alarm": false,
  "scene_type": "floor_risk_area",
  "hard_negative_type": "bending_pick_object",
  "fall_start_ms": null,
  "low_posture_start_ms": 1800,
  "support_surface": "none",
  "review_status": "approved"
}
```

### 4.3 人工审核原则

人工审核不要只看“最后有没有躺下”，而要看完整过程：

```text
1. 起始姿态：站立、坐着、半身入画、已经躺着
2. 下降方式：突然下坠、受控下降、缓慢滑落、弯腰
3. 最终位置：地面风险区、床、沙发、椅子、护理垫
4. 持续时间：低姿态持续多久
5. 恢复行为：是否站起、坐起、翻身、继续移动
6. 轨迹质量：是否遮挡、多人交叉、track_id 是否切换
7. 结论：fall / adl / uncertain
```

不确定样本不要强行放入训练集，应先进入：

```text
unknown_or_uncertain_review
```

## 5. 实施步骤

### 阶段 A：影子模式补全

目标：只计算 v6 分数，不改变线上告警。

任务：

```text
确认 FALL_V6_SCORING_ENABLED=true
确认 FALL_V6_DECISION_ENABLED=false
输出 fall_evidence_score
输出 adl_suppression_score
输出 motion_path
输出 decision_reason
输出 suppressed_by_adl
输出 uncertain_review
输出 fall_latched
```

验收：

```text
线上和离线流程不报错
现有告警结果不变化
每一次疑似跌倒都能解释为什么确认或不确认
```

### 阶段 B：离线回归集

目标：构建可重复评估的验证闭环。

任务：

```text
建立 fp_regression_manifest.json
建立 slow_fall_review_manifest.json
使用同一批视频分别运行 baseline_shadow 和 v6_decision
比较 TP/FN/FP/TN、确认延迟、重复报警次数
```

命令：

```powershell
python scripts\run_temporal_v6_regression_eval.py `
  --manifest evaluations\fall_temporal_v6\fp_regression_manifest.json `
  --output-dir evaluations\fall_temporal_v6\fp_regression_stride4 `
  --frame-stride 4

python scripts\run_temporal_v6_regression_eval.py `
  --manifest evaluations\fall_temporal_v6\slow_fall_review_manifest.json `
  --output-dir evaluations\fall_temporal_v6\slow_fall_review_stride4 `
  --frame-stride 4
```

验收：

```text
ADL confirmed FP 不高于 baseline
慢速跌倒至少能进入 slow_fall_path
真实快速跌倒 recall 不下降
同一事件不重复报警
decision_reason 可以解释每个样本
```

### 阶段 C：阈值校准

目标：在真实样本上确定可上线阈值。

优先校准：

```text
fast_fall fall_evidence 阈值
slow_fall low_posture_hold_ms
adl_suppression 抑制阈值
recovery_score 撤销阈值
track_quality_score 复核阈值
support_surface_score 抑制阈值
```

原则：

```text
不要为了救一个漏报盲目降低全局阈值
先分析漏报原因是检测、跟踪、姿态、LSTM 还是状态机
每次调参必须同时跑 hard negative 和 slow fall 两类集合
```

### 阶段 D：小范围开启 v6 决策

目标：在可控场景验证线上效果。

建议配置：

```text
FALL_V6_SCORING_ENABLED=true
FALL_V6_DECISION_ENABLED=true
FALL_V6_DEBUG_PAYLOAD=true
```

上线范围：

```text
先选择 1 到 2 个摄像头
优先选择目标区域清晰、床/沙发区域明确、遮挡较少的场景
连续观察 3 到 7 天
```

观察指标：

```text
confirmed_alarm_count
confirmed_false_positive_count
missed_fall_review_count
slow_fall_path_count
adl_suppressed_count
uncertain_review_count
duplicate_alarm_count
```

### 阶段 E：决定是否训练 LSTM v6

只有当状态机优化后仍存在稳定瓶颈，再进入 LSTM 重训。

触发条件：

```text
大量 ADL 的 fall_probability 持续偏高
大量慢速跌倒 fall_probability 持续偏低
状态机只能依赖规则硬兜底
已积累足够人工审核后的时序样本
```

训练数据要求：

```text
原始视频
逐事件人工标签
fall_start_ms
low_posture_start_ms
recovery_ms
scene_type
support_surface
hard_negative_type
导出的 32 帧滑动窗口特征
```

训练策略：

```text
保留 15 维输入先训练 LSTM v6
优先增加 hard negative 和 slow fall 样本
使用独立测试集评估，不允许训练集视频泄漏到测试集
评估指标同时看 recall、confirmed FP、confirm delay
```

## 6. 教授协作重点

建议教授重点参与四件事：

```text
1. 定义医学/护理视角下的真实跌倒、慢速跌倒、正常躺卧边界
2. 审核 hard negative 和 slow fall 数据集标签
3. 审核 decision_reason 是否符合临床/护理常识
4. 根据误报/漏报案例建议新的反证据特征
```

建议每轮评审提供：

```text
样本视频
系统逐帧输出
最终报警时间
motion_path
fall_evidence_score
adl_suppression_score
decision_reason
人工结论
分歧说明
```

## 7. 最终验收标准

v6 逻辑进入生产前，至少满足：

```text
1. 快速真实跌倒 recall 不低于当前 baseline
2. 慢速倒地并在地面风险区躺卧 5 到 10 秒可以触发一次告警
3. 弯腰、坐下、蹲下、短暂躺卧 confirmed FP 不高于 baseline
4. 床/沙发/椅子等正常支撑区域不直接按跌倒确认
5. 同一 track 同一跌倒过程只报警一次
6. 跟踪质量差或证据冲突时进入 uncertain_review，而不是强行确认
7. 所有确认和抑制都有 decision_reason
8. 离线回归脚本和单元测试全部通过
```

## 8. 当前建议结论

当前最合理的下一步不是马上重训模型，而是：

```text
先用 v6 影子模式收集证据
建立 fp_regression 和 slow_fall_review 两个真实视频回归集
用回归集校准状态机阈值
小范围开启 v6 决策
最后再决定是否训练 LSTM v6
```

这条路线更稳，因为它可以同时解决误报、漏报、可解释性和教授审核协作问题。
