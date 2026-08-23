# New Pose Data Audit

日期: `2026-06-21`

仓库: `D:\Program\vision_service`

## 范围

本审计只读扫描了以下位置，用于判断哪些历史材料可复用为新 Pose 的数据资产来源:

- `logs/acceptance`
- `logs/runtime_debug`
- `datasets`
- `data`
- `docs`

本轮没有:

- 启用真实 Pose runtime
- 修改 `8000` 的正式 no-pose 行为
- 开始训练
- 开始抽帧或标注

## 分类说明

- `A`: 可作为训练候选原始来源，但仍需要后续人工标注或抽帧规范化
- `B`: 可作为评估候选或可视化回放候选
- `C`: 主要用于故障复盘和 hard case 解释
- `D`: 当前不建议直接使用

## 资产清单

| category | path | file_type | source | session_name | camera_id | approximate_action | has_video | has_frames | has_metadata | has_status_samples | has_integration_samples | has_visual_preview | usable_for_pose_training | usable_for_pose_eval | usable_for_hard_case | reason | privacy_risk | recommended_action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B | `logs/acceptance/detector_only_guard_live_retest_20260620_165846` | mixed | live acceptance | `detector_only_guard_live_retest_20260620_165846` | `camera_01` | `no_person, standing, sitting, arm_motion, bending, real_fall, recovery_standing` | yes | yes | no | yes | yes | yes | no | yes | yes | 有 `cropped_recording.mp4`、`preview.gif`、动作分段帧和采样 jsonl，适合做新 Pose 的 live 评估回放与 hard case 清单，但不是规范 raw session | medium | 作为 `Phase 8/12/13` 评估回放素材保留，不直接入训练集 |
| B | `logs/acceptance/incident_dedup_live_retest_20260620_182505` | mixed | live acceptance | `incident_dedup_live_retest_20260620_182505` | `camera_01` | `no_person, standing, real_fall, fallen_hold, recovery_standing` | yes | yes | no | yes | yes | yes | no | yes | yes | 同时包含视频、分段帧、状态采样和最终报告，适合做真实跌倒保持阶段的姿态评估与事件回放 | medium | 作为跌倒/保持/恢复 hard case 保留，不直接作为标准训练 raw |
| B | `logs/acceptance/reporter_guard_incident_dedup_live_retest_20260621_102213` | frames+jsonl | live acceptance | `reporter_guard_incident_dedup_live_retest_20260621_102213` | `camera_01` | `no_person, standing, fall, incident reuse` | no | yes | no | yes | yes | no | no | yes | yes | 无原始视频，但有大量分段帧和 jsonl，适合问题对比与 hard case 评估 | medium | 保留为 hard case，不作为训练主数据源 |
| C | `logs/acceptance/standard_action_retest_20260618_112537` | frames+jsonl | live acceptance | `standard_action_retest_20260618_112537` | `camera_01` | `sitting, fall_candidate, false_confirm` | no | yes | no | yes | no | no | no | limited | yes | 主要价值在于坐姿误报和 candidate 波动复盘，缺原视频和规范 metadata | medium | 仅用于 field rule / temporal / pose hard case 复盘 |
| C | `logs/acceptance/real_retest_after_field_fix_20260618_140733` | frames+jsonl | live acceptance | `real_retest_after_field_fix_20260618_140733` | `camera_01` | `sitting, fall, missing_conditions` | no | yes | no | yes | no | no | no | limited | yes | 适合解释真实跌倒未确认的结构性阻塞，不适合作为训练原始素材 | medium | 作为漏报 hard case 保存 |
| C | `logs/acceptance/branch4_legacy_20260618_093756` | images | live debug | `branch4_legacy_20260618_093756` | `camera_01` | `pose drift sample` | no | yes | no | no | no | no | no | limited | yes | 只有少量图像，价值主要在姿态边界污染与腿部漂移故障定位 | medium | 仅用于姿态错误样本讲解 |
| C | `logs/runtime_debug/latest_frame_endpoint.jpg` | image | runtime debug | `latest_frame_endpoint` | `camera_01` | `latest frame snapshot` | no | yes | no | no | no | no | no | limited | yes | 单帧调试图像可帮助检查采集质量，但不足以组成训练样本 | medium | 作为质检参考图 |
| A | `datasets/ur_fall` | videos | public dataset | `ur_fall` | `external` | `adl + fall` | yes | no | yes | no | no | no | yes | yes | limited | 已有公开视频与动作标签，可作为外部补充原始来源，但与当前摄像头视角存在明显 domain gap | low | 保留为外部补充源，后续只做辅训或对比，不替代现场数据 |
| A | `datasets/gmdcsa24` | videos | public dataset | `gmdcsa24` | `external` | `adl + fall` | yes | no | yes | no | no | no | yes | yes | limited | 公共 ADL / fall 视频数量较多，可补充动作多样性，但不等于当前场景数据 | low | 保留为补充数据源，优先用于预训练/迁移参考 |
| B | `datasets/ur_fall_cam1` | videos | public dataset | `ur_fall_cam1` | `external` | `fall` | yes | no | yes | no | no | no | limited | yes | limited | 数量少，但可作为不同视角 fall 补充 | low | 仅作补充评估素材 |
| C | `data/pose_adaptation_dataset` | derived annotations | derived internal | `pose_adaptation_dataset` | `mixed` | `historical pose adaptation` | no | yes | yes | no | no | no | no | limited | no | 这是旧阶段整理出的衍生小样本，不属于规范 raw session，不能作为新一期 raw 真值替代物 | medium | 仅作结构参考，不直接并入新 raw 数据集 |
| C | `data/pose_adaptation_dataset_full` | derived annotations | derived internal | `pose_adaptation_dataset_full` | `mixed` | `historical pose adaptation full` | no | yes | yes | no | no | no | limited | limited | no | 样本量较大，但属于衍生训练中间产物，来源混合且质量口径未按新规范重新审计 | medium | 只保留作历史参考，后续如要用需二次 QA |
| D | `data/pose_pseudolabels` | jsonl | pseudolabel output | `actor_1_fall_01` | `external` | `auto pose labels` | no | no | no | no | no | no | no | no | limited | 该目录是历史伪标签输出，不适合作为新 Pose 的真值训练材料 | low | 不直接复用为训练真值 |

## 结论

### 可复用训练候选

优先级最高的训练候选不是现有 `logs/acceptance`，而是:

1. `datasets/ur_fall`
2. `datasets/gmdcsa24`

原因:

- 这两类目录有成体系原始视频
- 有相对明确的动作标签
- 可在后续 Phase 4/5 被规范化抽帧与人工标注

但它们只适合作为补充，不可替代当前摄像头现场数据。

### 可复用评估候选

最适合做新 Pose visual review / shadow 评估回放的现有资产:

1. `detector_only_guard_live_retest_20260620_165846`
2. `incident_dedup_live_retest_20260620_182505`
3. `reporter_guard_incident_dedup_live_retest_20260621_102213`

原因:

- 同时覆盖 `no_person / standing / sitting / bending / real_fall / fallen_hold / recovery`
- 包含 live 场景帧、采样 jsonl 和部分视频/预览
- 非常适合后续离线比对新 Pose 稳定性

### Hard case 资产

当前最值得保留的 hard case:

- `standard_action_retest_20260618_112537`
- `real_retest_after_field_fix_20260618_140733`
- `branch4_legacy_20260618_093756`
- `logs/runtime_debug/latest_frame_endpoint.jpg`

这些素材主要用于:

- 坐姿误报
- candidate 不持续
- 腿部/边界污染
- 真实跌倒漏报解释

### 不建议直接复用的资产

- `data/pose_pseudolabels`
- `data/pose_adaptation_dataset`
- `data/pose_adaptation_dataset_full`

原因:

- 它们是历史衍生中间产物，不是新的 raw ground-truth 采集成果
- 数据来源、质量门槛和标注口径未按本次新协议统一重审

## 审计结论

当前已经具备:

- 足够的 `评估候选 / hard case` 资产
- 一定量的 `外部公开视频训练候选`

当前仍缺:

- 按统一 session 命名和 metadata 标准采集的 `camera_01` 现场 raw 数据
- 单独为新 Pose 设计的原始视频、动作脚本和 QA 记录

因此下一步应该进入:

- `ReadyForManualDataCollection`

但仍不适合:

- 直接开始训练
- 直接启用新 Pose runtime
