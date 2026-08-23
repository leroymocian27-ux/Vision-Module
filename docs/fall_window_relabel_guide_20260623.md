# Fall Window Relabel Guide - 2026-06-23

## Scope

本指南用于 `hardneg_v1` 训练前 fall window 人工复核。当前阶段仍禁止训练、禁止覆盖 baseline、禁止修改 `.env`、禁止修改生产代码。

已生成的候选标签：

- `artifacts/fall_window_relabel/fall_window_labels.csv`
- `artifacts/fall_window_relabel/non_fall_verified.csv`
- `artifacts/yolo_fall_hardneg_v1_dataset/train_manifest_final_candidate.csv`
- `artifacts/yolo_fall_hardneg_v1_dataset/val_manifest_final_candidate.csv`

注意：`fall_window_labels.csv` 中的时间窗是半自动候选，不是最终真值。

## Required Fields

每个 fall 视频必须人工确认：

| Field | Meaning |
| --- | --- |
| `fall_start_sec` | 人体从正常活动进入不可控跌落或明显失衡的起点。 |
| `fall_end_sec` | 跌落动作结束并进入地面/床/椅旁稳定姿态的时间点。 |
| `fall_phase` | 当前标注窗口的主要阶段：`pre_fall` / `falling` / `fallen_hold` / `recovery`。 |
| `label_status` | 人工复核后改为 `human_verified`；仍不确定则保留 `manual_review_required`。 |
| `notes` | 记录遮挡、半身出画、坐到躺、主动躺下、镜头切换等歧义。 |

## Phase Definition

| Phase | Definition | YOLO use |
| --- | --- | --- |
| `pre_fall` | 跌倒前正常站立、行走、坐姿、准备动作。 | 不标 fall，通常作为 negative 或忽略。 |
| `falling` | 明显失衡、快速下落、身体姿态从直立转为水平/倾倒。 | 可抽 fall/fallen/lying 正样本，但需人工框 QA。 |
| `fallen_hold` | 已经倒地/倒床/倒椅旁且保持不动或低动。 | 可抽 fallen/lying 正样本，避免与主动躺下混淆。 |
| `recovery` | 起身、坐起、被扶起、离开跌倒姿态。 | 通常不作为 fall 正样本，除非业务明确需要。 |

## Non-fall Verification

`non_fall_verified.csv` 中的 non_fall 样本已写入：

- `window_status=verified_non_fall_no_fall_window`
- `fall_start_sec` 为空
- `fall_end_sec` 为空

人工复核时只需确认：

1. 视频中确实没有跌倒事件。
2. 场景分类正确：`sit`、`squat`、`bend`、`lie_down_non_fall`、`no_person`、`occlusion`、`walk`、`stand`。
3. 若发现真实跌倒，必须从 non_fall 清单移除并重新标注 fall window。

## YOLO Annotation Rules

当前 YOLO 类别沿用 baseline 数据配置：

| id | name |
| ---: | --- |
| 0 | person |
| 1 | fall |
| 2 | fallen |
| 3 | lying |
| 4 | sitting |
| 5 | bending |
| 6 | kneeling |
| 7 | standing |

建议规则：

- `falling` 过程优先标 `fall`。
- 已稳定倒地/倒床状态优先标 `fallen` 或 `lying`。
- 主动躺下的 non_fall hard negative 不标 fall/fallen/lying 正类，除非训练目标明确区分 `lying` 正负语义。
- no_person 样本 label txt 应为空文件。
- hard negative 可保持空 label，或在后续策略中加入 person/sitting/bending 等非 fall 类，但必须与原 baseline 类语义一致。

## QA Checklist

训练前必须完成：

- `fall_window_labels.csv` 所有 train/val fall 行改为 `human_verified`。
- `fall_start_sec` / `fall_end_sec` 不能全空，且 `fall_end_sec > fall_start_sec`。
- 抽帧图片和 YOLO txt 一一对应。
- baseline 伪框必须人工复核，错误框删除或修正。
- `test_manifest_frozen.csv` 和 `fp_regression_set.csv` 不得出现在 train/val manifest。
- 补齐 train 中 `occlusion` hard negative。
- 补充 val 的 non_fall / hard negative 样本，避免 val 只有 fall。

## Current Candidate Status

当前构建结果是候选数据集，不是最终训练集：

- train 有 fall 正样本候选和 hard negative 候选。
- val 有 fall 正样本候选，但缺 non_fall val 候选。
- train 缺 `occlusion` hard negative。
- fall window 和 YOLO box 都需要人工 QA。

因此当前仍不满足开始训练 `yolo_fall_detector_hardneg_v1.pt` 的条件。
