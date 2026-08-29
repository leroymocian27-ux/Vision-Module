# Post-Fall V2 双路径安全决策

本文描述当前 Post-Fall V2 真实运行链路中的最终跌倒决策、告警和测试归档规则。代码中的权威实现位于 `app/post_fall_v2/safety_decision.py`。

## 1. 角色边界

```text
二分类模型 -> 高频发现异常外观并建立候选事件
关键帧时序 -> 提供跌倒前、触发时和跌倒后证据
千问模型   -> 描述动作、姿态、主动行为、恢复和可见性
事件状态机 -> 唯一最终安全决策者：ALERT / OBSERVE / DISMISS
```

千问不能直接决定“是否发送告警”。它提供语义证据；状态机结合二分类是否持续异常以及观察时长作最终决定。

## 2. 两条独立告警路径

### 路径 A：Transition Fall

关键帧中真实可见非自主失衡、失控下降并倒地，且经过一致性校验后同时满足：

```text
fall_verdict = confirmed_fall
fall_transition_visible = true
```

```text
outcome = alert
path = transition_fall
public state = fallen_confirmed
alert level = high
```

### 路径 B：Post-Fall Abnormality

即使没有拍到跌倒瞬间，只要满足以下条件，仍升级为疑似持续倒地告警：

1. 二分类事件仍处于 `EVENT_ACTIVE` 或 `FALL_CONFIRMED`。
2. 从候选开始计算的持续时间达到 `POST_FALL_V2_POST_FALL_ALERT_MIN_MS`，默认 `10000 ms`。
3. 千问分析成功并输出 `fall_verdict = unclear`；失败、超时、解析失败或画面不足只进入观察/重试。
4. `posture_state` 为 `ground_low` 或 `lying`。
5. `persistent_ground_state = observed`，仅表示在所给关键帧跨度内持续低位。
6. `recovery_observed` 不为 `true`。
7. `intentional_action_evidence` 不为 `true`。

输出为：

```text
outcome = alert
path = post_fall_abnormality
public state = suspected_post_fall
alert level = warning
review_required = true
```

该告警语义是“持续异常低姿态，需要立即查看”，不能对外伪装成已经确认的真实跌倒。

## 3. 观察、否决和冲突

| 输入情况 | 状态机结果 |
| --- | --- |
| `normal_activity` + 明确正常活动和正常姿态证据 | `dismiss / explicit_non_fall` |
| `intentional_low_posture` + `intentional_action_evidence=true` | `dismiss / explicit_non_fall` |
| `unclear` + 低位持续证据，但未到 10 秒 | `observe / uncertain_evidence` |
| `unclear` + 低位持续证据 + 二分类持续至少 10 秒 | `alert / post_fall_abnormality` |
| `insufficient_visual_evidence` | `observe / retry` |
| 千问失败、超时或解析失败 | `observe / retry` |
| 千问仍在运行 | `observe / awaiting_post_fall_followup_review` |
| 二分类进入恢复状态 | 保持观察，不升级 Post-Fall 告警 |
| 千问观察到恢复 | 保持观察，不升级 Post-Fall 告警 |
| 同时出现跌倒转场与主动行为证据 | 证据冲突，进入观察/人工复核 |

核心安全原则：

```text
不知道 != 没有跌倒
模型失败 != 没有跌倒
只有明确正常活动或明确主动低姿态证据才能作语义否决
```

千问 JSON 必须填写以下结构化证据字段：

```text
activity
posture_state
fall_transition_visible
intentional_action_evidence
recovery_observed
persistent_ground_state
```

Parser 不会再根据 `confirmed_fall` 自动补出 `fall_transition_visible=true`。结论与证据冲突或字段缺失时，结论降级为 `unclear`。

## 4. 对外字段

PFV2 发布结果必须包含：

```json
{
  "decision_authority": "event_state_machine",
  "safety_outcome": "alert | observe | dismiss",
  "safety_path": "transition_fall | post_fall_abnormality | explicit_non_fall | uncertain_evidence",
  "qwen_gate": "confirmed | denied | observe | pending"
}
```

`qwen_gate` 只表示语义复核状态，不是告警门。Reporter 和事件管线对 PFV2 只接受：

```text
decision_authority == event_state_machine
AND safety_outcome == alert
```

Transition 告警对外使用 `fallen_confirmed`；Post-Fall 告警使用 `suspected_post_fall` 和 `fall_suspected`，避免把疑似事件描述为已确认跌倒。

## 5. 测试归档完整性

测试期间每个二分类完整事件使用同一 `incident_id` 进入千问归档，目录名必须一一对应：

```text
E:\国赛\event\binary-classification\full\<incident_id>
E:\国赛\event\qwen\confirm\<incident_id>
E:\国赛\event\qwen\deny\<incident_id>
E:\国赛\event\qwen\review\<incident_id>
```

归档分类：

- `confirm`：千问成功输出 `confirmed_fall`。
- `deny`：千问明确输出 `normal_activity` 或 `intentional_low_posture`。
- `review`：`unclear`、`insufficient_visual_evidence`、失败、超时或解析失败。

完整性等式为：

```text
binary_full_count
= qwen_confirm_count + qwen_deny_count + qwen_review_count
```

测试结束时尚未完成的千问任务先进入 draining；超过 drain 超时后按 review 处理，不能丢进 deny。

## 6. 当前边界

- 当前会持续按配置 FPS 采样二分类画面，并在不确定时继续观察二分类状态。
- 当前尚未自动建立一组更晚时间点的新关键帧并发起第二次千问请求；`vlm_reviews` 已保留多次复核的数据结构，但实时链路目前通常只有一次复核。
- 真实外部告警验证必须保持 `MAIN_SYSTEM_ALERT_ENABLED=false` 且 `MAIN_SYSTEM_REPORT_DRY_RUN=true`，待受控验收通过后再单独开启。

## 7. 主要实现位置

- 安全决策：`app/post_fall_v2/safety_decision.py`
- 实时状态与派发：`app/post_fall_v2/post_fall_runtime_service.py`
- 千问证据解析：`app/events/qwen_keyframe.py`
- 千问适配器：`app/post_fall_v2/qwen_fall_analyzer.py`
- Reporter 门控：`app/services/fall_event_reporter_service.py`
- 测试归档：`app/post_fall_v2/test_archive_service.py`
