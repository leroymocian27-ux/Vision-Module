# Fall Dataset Inventory - 2026-06-23

## Scope

本报告扫描并整理当前 `datasets`、`logs`、`acceptance`、`artifacts` 中可用视频，生成训练前数据审计结果。没有训练模型，没有修改生产配置。

输出文件：

- `artifacts/fall_dataset_inventory_20260623/dataset_inventory.csv`
- `artifacts/fall_dataset_inventory_20260623/relabel_needed.csv`
- `artifacts/fall_dataset_inventory_20260623/hard_negative_plan.csv`

## Inventory Summary

本次扫描到视频文件 328 个。

| Label | Count |
| --- | ---: |
| fall | 86 |
| non_fall | 121 |
| unknown | 121 |

按数据来源统计：

| Dataset / Source | Count |
| --- | ---: |
| gmdcsa24 | 224 |
| ur_fall | 70 |
| ur_fall_cam1 | 2 |
| new_pose_raw | 23 |
| acceptance_recording | 9 |

按场景统计：

| Scene | Count |
| --- | ---: |
| fall | 133 |
| walk | 103 |
| unknown | 65 |
| screen_recording | 9 |
| stand | 5 |
| sit | 4 |
| lie_down_non_fall | 4 |
| no_person | 2 |
| squat | 2 |
| bend | 1 |

说明：scene 与 label 不完全等价。部分 `unknown/fall` 是路径或来源可疑但未有可信训练标签的素材，必须人工确认后才能使用。

## Recommended Use

| Recommended Use | Count | Meaning |
| --- | ---: | --- |
| train_candidate | 88 | 可作为训练候选，但仍需标签 QA 和 split 锁定。 |
| train_candidate_relabel_needed | 31 | fall 训练候选，必须补 `fall_start_sec/fall_end_sec`。 |
| test_only | 48 | 保持 held-out 或公共测试，不进入训练。 |
| test_only_relabel_needed | 12 | 当前 2026-06-23 验证样本，保持测试集并补时间窗。 |
| relabel_needed | 32 | fall-like 样本缺可信时间窗。 |
| review_needed | 112 | 标签/场景不足，不能训练。 |
| delete_or_exclude | 5 | 零字节或 codec probe 类文件，应排除。 |

## Hard Negative Coverage

重点 hard negative 场景：

| Scene | Current non_fall videos | Eval FP | Recommended min train count | Gap |
| --- | ---: | ---: | ---: | ---: |
| walk | 103 | 1 | 80 | 0 |
| sit | 4 | 2 | 80 | 76 |
| squat | 2 | 1 | 60 | 58 |
| bend | 1 | 0 | 60 | 59 |
| lie_down_non_fall | 4 | 0 | 80 | 76 |
| no_person | 2 | 1 | 60 | 58 |

当前 walk 数量看似充足，但多数来自公共 ADL 或路径规则，不等于本地摄像机场景已充分覆盖。sit、squat、bend、lie_down_non_fall、no_person 明显不足，且 sit/squat/no_person 已在验证集中产生误报。

## Current FP Samples To Freeze

以下样本已在 2026-06-23 labeled validation 中误报，应作为 hard-negative regression test 冻结，不建议直接混入第一轮训练：

| Scene | Path | Max fall score |
| --- | --- | ---: |
| no_person | `datasets/new_pose_raw/camera_01/session_20260621_151001_no_person_retake_b/video.mp4` | 0.6185 |
| sit | `datasets/new_pose_raw/camera_01/session_20260621_151101_sitting_normal_retake_b/video.mp4` | 0.5032 |
| sit | `datasets/new_pose_raw/camera_01/session_20260621_151201_sitting_side_retake_b/video.mp4` | 0.5681 |
| squat | `datasets/new_pose_raw/camera_01/session_20260621_151301_squat_retake_b/video.mp4` | 0.5470 |
| walk | `datasets/new_pose_raw/camera_01/session_20260621_160500_walking_slow/video.mp4` | 0.5007 |

## Missing fall_start_sec / fall_end_sec

发现存在视频级标签但缺少时间窗的问题。

关键情况：

- `artifacts/labeled_dataset_validation_20260623/labels.csv` 中 12 条全部有视频级 label，但 `fall_start_sec` / `fall_end_sec` 全为空。
- 其中 5 条为 fall 标签，必须补齐跌倒发生区间。
- 另外 7 条 non_fall 也建议明确保持空值并标注为 `verified_non_fall_no_fall_window`，避免后续脚本误解为漏标。
- 全量 inventory 中 205 条进入 `relabel_needed.csv`，包括 fall 时间窗缺失和 unknown/review_needed 样本。

优先重标对象：

1. 2026-06-23 labeled validation 12 条，保持 held-out。
2. GMDCSA24 fall 候选样本，补时间窗后才能用于 temporal 或 frame-level 训练。
3. 本地 `new_pose_raw` fall_simulated / fallen_hold 样本，补时间窗并区分 fall transition 与 fallen hold。
4. `unknown/fall` 路径样本，先确认是否真 fall，再决定保留或删除。

## Add / Delete / Relabel Plan

建议增加：

- sit：正常坐下、坐姿前倾、侧坐、椅边滑动、从坐姿站起。
- squat：深蹲、半蹲、蹲下捡物、靠近画面边缘蹲下。
- bend：弯腰捡物、系鞋带、低柜取物、背对摄像头弯腰。
- lie_down_non_fall：主动躺下、地面休息、床/沙发躺下、侧卧/仰卧/俯卧。
- no_person：空房间、家具遮挡、光影变化、摄像头抖动、屏幕/反光干扰。
- occlusion：半身出画、被桌椅遮挡、人体边缘进入画面、低光下局部人体。

建议删除或排除：

- 0 字节或近零字节 codec probe：`codec_test_*.mp4`。
- screen/cropped/frontend recording：只做验收回放，不作为原始训练样本。
- 标签冲突、无法打开、来源不明且无法复核的 unknown 样本。

建议降权：

- 公共数据集中大量重复的 walk/ADL 样本，避免训练集被单一 ADL 模式主导。
- 自动标签或路径规则生成的 fall 样本，未补时间窗前只能低权重或禁用。
- 与测试集同 actor/session/source 的近重复样本。

## Training Readiness

当前尚不具备开始训练 `hardneg_v1` 的条件。

必须先完成：

- hard negative 新增或确认，尤其 sit/squat/bend/lie_down_non_fall/no_person。
- fall 样本补齐 `fall_start_sec/fall_end_sec`。
- 训练/验证/测试 split 冻结，避免把本次 FP 回归测试混入训练。
- 人工复核 121 个 unknown 视频。
- 排除 codec probe 和 screen recording 类文件。
