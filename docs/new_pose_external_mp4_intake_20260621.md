# New Pose External MP4 Intake

日期: `2026-06-21`

仓库: `D:\Program\vision_service`

commit: `c6da604`

## Context

本轮新增 5 段外部 MP4，用于补充 `camera_01` 新 Pose 训练数据。

这些视频不是通过当前 `new_pose_raw` 现场采集模板直接产出，因此当前先进入独立的 `datasets/new_pose_imports/` 区，不直接进入 `datasets/new_pose_raw/` 主集合，也不直接进入 `frame_manifest_curated_v1.jsonl`。

这样做的目的:

- 保留原始样本和来源追踪。
- 不污染 Phase 4B 当前的主 curated 口径。
- 允许先做人审、切段和动作重标，再决定是否进入抽帧与标注。

## Curated Baseline Refresh

已重新生成:

- [frame_manifest_curated_v1.jsonl](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/frame_manifest_curated_v1.jsonl)
- [frame_selection_curated_report_20260621.md](/D:/Program/vision_service/datasets/new_pose_frames/frame_selection_curated_report_20260621.md)

当前主 curated 集合仅保留:

- `standing_front`: `30`
- `standing_side`: `30`
- `standing_back`: `30`
- `walking_slow`: `48`
- `recovery_standing_retake`: `48`

当前仍缺:

- `no_person_retake`
- `sitting_normal_retake`
- `sitting_side_retake`
- `squat_retake`
- `lying_back_retake`
- `fall_simulated_back_retake`

这说明外部 MP4 的主要价值，是优先补 `fall_simulated_back / sitting / mixed recovery` 这几类缺口，但进入主标注池前仍需动作级切段与人工确认。

## Imported Sessions

### 1. Standing Candidate

- source: `C:\Users\YANG\Desktop\a64f9bce58dfda706d4ba830a7749ae2.mp4`
- imported session: [session_20260621_175141_standing_front_long_take_a64f9b](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175141_standing_front_long_take_a64f9b)
- contact sheet: [contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175141_standing_front_long_take_a64f9b/contact_sheet.jpg)
- duration: `103.133s`
- resolution: `1280x720`
- action_hypothesis: `standing_front_long_take`
- standard_action_candidate: `standing_front`
- review_decision: `candidate`
- recommended_split: `trim_needed`

判断:

- 主体动作为正面对镜站立。
- 中间包含手臂展开等轻微变化，不适合整段直接当成纯 `standing_front`。
- 适合作为 `standing_front` 的补充长片段来源，但建议先人工裁出稳定站立窗口。

### 2. Long Fall Candidate

- source: `C:\Users\YANG\Desktop\ec4c9594a3fee498abcee80566372029.mp4`
- imported session: [session_20260621_175142_fall_simulated_back_long_take_ec4c95](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175142_fall_simulated_back_long_take_ec4c95)
- contact sheet: [contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175142_fall_simulated_back_long_take_ec4c95/contact_sheet.jpg)
- duration: `122.966s`
- resolution: `960x544`
- action_hypothesis: `fall_simulated_back_long_take`
- standard_action_candidate: `fall_simulated_back`
- review_decision: `candidate`
- recommended_split: `trim_needed`

判断:

- 存在明显的 `standing -> fall_transition -> fallen_hold` 过程。
- 但整段较长，前后含非目标窗口，不能整段直接送抽帧。
- 建议优先人工切出跌倒段和倒地保持段，后续可拆成 `fall_simulated_back` 与 `fallen_hold` 两类标注来源。

### 3. Short Fall Candidate

- source: `C:\Users\YANG\Desktop\20eab7404c5cac9c3038a059cf6d0bbc.mp4`
- imported session: [session_20260621_175142_fall_simulated_back_short_take_20eab7](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175142_fall_simulated_back_short_take_20eab7)
- contact sheet: [contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175142_fall_simulated_back_short_take_20eab7/contact_sheet.jpg)
- duration: `10.3s`
- resolution: `1280x720`
- action_hypothesis: `fall_simulated_back_short_take`
- standard_action_candidate: `fall_simulated_back`
- review_decision: `candidate`
- recommended_split: `direct_reuse`
- ready_for_frame_extraction: `true`

判断:

- 这是 5 段里最接近直接复用的样本。
- 画面包含站立、下落和倒地保持，动作链路紧凑。
- 适合作为 `fall_simulated_back` 的补充短样本，后续可以优先进入抽帧试跑。

### 4. Mixed Fall + Seated Recovery

- source: `C:\Users\YANG\Desktop\87b7d5c9e038702bb20062f873c6a465.mp4`
- imported session: [session_20260621_175142_mixed_fall_and_seated_recovery_87b7d5](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175142_mixed_fall_and_seated_recovery_87b7d5)
- contact sheet: [contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175142_mixed_fall_and_seated_recovery_87b7d5/contact_sheet.jpg)
- duration: `68.233s`
- resolution: `1280x720`
- action_hypothesis: `mixed_fall_and_seated_recovery`
- standard_action_candidate: `recovery_standing`
- review_decision: `review`
- recommended_split: `trim_needed`

判断:

- 整段含 `standing -> fall/low_posture -> seated_recovery` 混合过程。
- 末段没有形成干净的 `recovery_standing` 完整闭环，更像“倒地后坐起”。
- 不建议直接进入主标注池，适合保留作 hard case review 或后续人工切段。

### 5. Mixed Floor Sit Transition

- source: `C:\Users\YANG\Desktop\574c42749fa162a487f7e3d3e84bb181_raw.mp4`
- imported session: [session_20260621_175142_mixed_floor_sit_transition_574c42](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175142_mixed_floor_sit_transition_574c42)
- contact sheet: [contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_imports/camera_01/session_20260621_175142_mixed_floor_sit_transition_574c42/contact_sheet.jpg)
- duration: `8.233s`
- resolution: `1280x720`
- action_hypothesis: `mixed_floor_sit_transition`
- standard_action_candidate: `sitting_normal`
- review_decision: `review`
- recommended_split: `review_only`

判断:

- 视频从空场开始，随后有人进入，再发生借助椅子的下沉/地面坐姿过程。
- 不属于干净的 `sitting_normal`，也不是标准 `no_person`。
- 当前更适合作为“动作污染示例”或后续自定义坐地 hard case，不建议进入现阶段主训练集。

## Intake Decision Summary

可优先推进:

- `20eab7404c5cac9c3038a059cf6d0bbc.mp4`
  - 可作为 `fall_simulated_back` 补充样本直接试抽帧。
- `ec4c9594a3fee498abcee80566372029.mp4`
  - 适合切出 `fall_simulated_back` 与 `fallen_hold` 子段后再抽帧。
- `a64f9bce58dfda706d4ba830a7749ae2.mp4`
  - 适合切出稳定站立窗口补充 `standing_front`。

需保留 review，不进入主 curated:

- `87b7d5c9e038702bb20062f873c6a465.mp4`
- `574c42749fa162a487f7e3d3e84bb181_raw.mp4`

## Recommended Next Step

1. 先不要把这 5 段视频直接并入 `datasets/new_pose_raw` 主采集集。
2. 先基于外部导入会话做人审切段。
3. 优先处理 `20eab...` 和 `ec4c...`，补 `fall_simulated_back` 缺口。
4. 如果要正式进入 Phase 5 标注前 QA，建议新增一轮 “external curated v1”：
   - 只纳入切段后动作清晰的外部样本
   - 不把 mixed review clip 直接送标注

## Paths

- import root: [datasets/new_pose_imports/camera_01](/D:/Program/vision_service/datasets/new_pose_imports/camera_01)
- import tool: [import_external_videos.py](/D:/Program/vision_service/tools/new_pose_dataset/import_external_videos.py)
