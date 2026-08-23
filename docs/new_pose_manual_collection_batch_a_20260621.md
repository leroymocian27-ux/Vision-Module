# New Pose Manual Collection Batch A

日期: `2026-06-21`

仓库: `D:\Program\vision_service`

批次: `Batch A`

## 采集概览

- 采集人: `codex + user on-camera`
- camera_id: `camera_01`
- runtime_profile: `current_camera_live`
- pose_enabled: `false`
- pose_provider: `disabled_placeholder`
- no_pose 正式链路: `unchanged`

本轮只做原始 raw 采集，没有:

- 启用真实 Pose
- 修改 `8000` 正式 runtime
- 开始抽帧
- 开始标注
- 开始训练

## Session 列表

| session_id | action | duration_sec | video | preview | metadata | status_samples | integration_samples | quality_status | retake_reason |
| --- | --- | ---: | --- | --- | --- | ---: | ---: | --- | --- |
| `session_20260621_160100_no_person` | `no_person` | 25.23 | yes | yes | yes | 49 | 49 | PASS | None |
| `session_20260621_160200_standing_front` | `standing_front` | 35.19 | yes | yes | yes | 69 | 69 | PASS | None |
| `session_20260621_160300_standing_side` | `standing_side` | 35.19 | yes | yes | yes | 69 | 69 | PASS | None |
| `session_20260621_160400_standing_back` | `standing_back` | 35.11 | yes | yes | yes | 69 | 69 | PASS | None |
| `session_20260621_160500_walking_slow` | `walking_slow` | 35.08 | yes | yes | yes | 69 | 69 | PASS | None |
| `session_20260621_160600_sitting_normal` | `sitting_normal` | 35.06 | yes | yes | yes | 69 | 69 | PASS | None |
| `session_20260621_160700_sitting_side` | `sitting_side` | 35.12 | yes | yes | yes | 68 | 68 | PASS | None |
| `session_20260621_160800_bending_pickup` | `bending_pickup` | 35.22 | yes | yes | yes | 69 | 69 | PASS | None |
| `session_20260621_160900_squat` | `squat` | 35.22 | yes | yes | yes | 69 | 69 | PASS | None |
| `session_20260621_161000_lying_side` | `lying_side` | 35.00 | yes | yes | yes | 68 | 68 | PASS | None |
| `session_20260621_161100_lying_back` | `lying_back` | 35.14 | yes | yes | yes | 68 | 68 | PASS | None |
| `session_20260621_161200_lying_prone` | `lying_prone` | 35.06 | yes | yes | yes | 68 | 68 | PASS | None |
| `session_20260621_161300_fall_simulated_side` | `fall_simulated_side` | 45.11 | yes | yes | yes | 88 | 88 | PASS | None |
| `session_20260621_161400_fall_simulated_back` | `fall_simulated_back` | 45.17 | yes | yes | yes | 88 | 88 | PASS | None |
| `session_20260621_161500_fallen_hold` | `fallen_hold` | 35.11 | yes | yes | yes | 68 | 68 | PASS | None |
| `session_20260621_161600_recovery_standing` | `recovery_standing` | 35.09 | yes | yes | yes | 69 | 69 | PASS | None |

## 总体结果

- total_sessions: `16`
- valid_sessions: `16`
- invalid_sessions: `0`
- retake_recommended_sessions: `0`
- missing_video: `0`
- missing_preview: `0`
- missing_metadata: `0`
- missing_status_samples: `0`
- missing_integration_samples: `0`
- possible_secret_leak: `0`

## 动作覆盖结论

Batch A 已覆盖本轮目标中的全部 16 个核心动作:

1. `no_person`
2. `standing_front`
3. `standing_side`
4. `standing_back`
5. `walking_slow`
6. `sitting_normal`
7. `sitting_side`
8. `bending_pickup`
9. `squat`
10. `lying_side`
11. `lying_back`
12. `lying_prone`
13. `fall_simulated_side`
14. `fall_simulated_back`
15. `fallen_hold`
16. `recovery_standing`

结论:

- `action_coverage=PASS`

## 可进入 Phase 4 的 session

### 可用于后续抽帧和人工标注

建议直接进入 Phase 4 的主 session:

- `session_20260621_160200_standing_front`
- `session_20260621_160300_standing_side`
- `session_20260621_160400_standing_back`
- `session_20260621_160500_walking_slow`
- `session_20260621_160600_sitting_normal`
- `session_20260621_160700_sitting_side`
- `session_20260621_160800_bending_pickup`
- `session_20260621_160900_squat`
- `session_20260621_161000_lying_side`
- `session_20260621_161100_lying_back`
- `session_20260621_161200_lying_prone`
- `session_20260621_161300_fall_simulated_side`
- `session_20260621_161400_fall_simulated_back`
- `session_20260621_161500_fallen_hold`
- `session_20260621_161600_recovery_standing`

数量:

- `usable_for_training_sessions=15`

### 保留为负样本 / 质检样本

- `session_20260621_160100_no_person`

用途:

- no-person 空场负样本
- 采集链路完整性对照
- 不作为关键点标注主样本

数量:

- `usable_for_eval_sessions=16`

## 需要重采的 session

当前没有建议重采的 session。

- `needs_retake_sessions=0`

## 相关报告

- [dataset_raw_qa_report.md](/D:/Program/vision_service/datasets/new_pose_raw/dataset_raw_qa_report.md)
- [new_pose_data_audit_20260621.md](/D:/Program/vision_service/docs/new_pose_data_audit_20260621.md)
- [new_pose_collection_protocol_20260621.md](/D:/Program/vision_service/docs/new_pose_collection_protocol_20260621.md)
- [new_pose_action_script_20260621.md](/D:/Program/vision_service/docs/new_pose_action_script_20260621.md)

## 下一步建议

1. 进入 Phase 4 抽帧与样本筛选。
2. 对 `A02` 到 `A16` 执行标准抽帧。
3. `A01 no_person` 保留为负样本和采集链路 QA，不进入关键点标注主集。
4. 继续保持 `ENABLE_POSE=false`、`POSE_PROVIDER=disabled_placeholder`，不要在进入抽帧前恢复真实 Pose runtime。
