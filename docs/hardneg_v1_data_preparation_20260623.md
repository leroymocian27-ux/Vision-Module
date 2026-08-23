# hardneg_v1 Data Preparation - 2026-06-23

## Scope

本阶段只做 `hardneg_v1` 训练前数据准备。已遵守边界：

- 未训练模型。
- 未覆盖 baseline：`models/yolo_fall_detector_phase9_selected.pt`。
- 未修改 `.env`。
- 未修改生产代码。
- 未启用真实 POST。
- 未执行 `git add .` 或 `git commit`。
- 未把 unknown 或未复核样本自动混入训练集。

输入依据：

- `docs/fall_dataset_inventory_20260623.md`
- `artifacts/fall_dataset_inventory_20260623/dataset_inventory.csv`
- `artifacts/fall_dataset_inventory_20260623/relabel_needed.csv`
- `artifacts/fall_dataset_inventory_20260623/hard_negative_plan.csv`
- `artifacts/labeled_dataset_validation_20260623/labels.csv`
- `artifacts/labeled_dataset_validation_20260623/per_video_results.csv`
- `datasets/fast_pose_fall/registry/clean_dataset_registry_20260622.csv`

## Outputs

生成文件：

- `artifacts/hardneg_v1_data_preparation/train_manifest_draft.csv`
- `artifacts/hardneg_v1_data_preparation/val_manifest_draft.csv`
- `artifacts/hardneg_v1_data_preparation/test_manifest_frozen.csv`
- `artifacts/hardneg_v1_data_preparation/fp_regression_set.csv`
- `artifacts/hardneg_v1_data_preparation/public_dataset_download_plan.csv`

## Held-out Freeze

已冻结测试集，共 58 条：

| Frozen subset | Count | Rule |
| --- | ---: | --- |
| 2026-06-23 labeled validation | 12 | 全部保持 held-out，不进入训练。 |
| Current FP regression samples | 5 | 已包含在 12 条 validation 中，同时单独输出 `fp_regression_set.csv`。 |
| GMDCSA public_test | 40 | 沿用现有 registry 的 `public_test`：20 fall + 20 non_fall。 |
| URFD public_test | 10 | 从 URFD 文件名稳定抽样：最后 5 条 fall + 最后 5 条 ADL。 |

冻结测试集分布：

| Label / Scene / Dataset | Count |
| --- | ---: |
| fall / fall / gmdcsa24 | 20 |
| fall / fall / ur_fall | 5 |
| fall / unknown / new_pose_raw | 3 |
| non_fall / walk / gmdcsa24 | 20 |
| non_fall / walk / ur_fall | 5 |
| non_fall / walk / new_pose_raw | 1 |
| non_fall / sit / new_pose_raw | 2 |
| non_fall / squat / new_pose_raw | 1 |
| non_fall / no_person / new_pose_raw | 1 |

## FP Regression Set

`fp_regression_set.csv` 固定 5 条当前误报样本：

| Scene | Sample |
| --- | --- |
| no_person | `datasets/new_pose_raw/camera_01/session_20260621_151001_no_person_retake_b/video.mp4` |
| sit | `datasets/new_pose_raw/camera_01/session_20260621_151101_sitting_normal_retake_b/video.mp4` |
| sit | `datasets/new_pose_raw/camera_01/session_20260621_151201_sitting_side_retake_b/video.mp4` |
| squat | `datasets/new_pose_raw/camera_01/session_20260621_151301_squat_retake_b/video.mp4` |
| walk | `datasets/new_pose_raw/camera_01/session_20260621_160500_walking_slow/video.mp4` |

这些样本不得加入 `hardneg_v1` 训练集；训练后用于回归验证 Precision/FPR 是否改善。

## Label Completion Status

本阶段完成的是标签状态整理，而不是替代人工逐帧标注。

已明确：

- `non_fall` 样本在 manifest 中写入 `verified_non_fall_no_fall_window`。
- `unknown` 样本没有自动进入 train/val draft。
- `screen_recording`、`codec_test_*`、零字节/近零字节文件没有进入 train draft。
- `fall` 样本若缺 `fall_start_sec/fall_end_sec`，统一标为 `missing_fall_window_manual_relabel_required`。

未完成且阻塞训练：

- GMDCSA 原始 CSV 只有 `File Name`、`Length`、`Description`，没有精确 fall_start/fall_end。
- 2026-06-23 labeled validation 的 12 条视频级标签中，`fall_start_sec/fall_end_sec` 仍为空。
- 当前没有足够可信的 fall 正样本时间窗，不能生成可训练的 fall 正样本清单。

## Manifest Drafts

### train_manifest_draft.csv

当前训练草案 83 条，全部为 non_fall：

| Label / Scene | Count |
| --- | ---: |
| non_fall / walk | 77 |
| non_fall / stand | 5 |
| non_fall / bend | 1 |

说明：

- 只纳入当前可较安全确认的 non_fall/no-fall-window 样本。
- 没有纳入 frozen test / FP regression。
- 没有纳入 unknown。
- 没有纳入 screen/cropped/frontend recording。
- 没有纳入 codec probe 或零字节文件。

### val_manifest_draft.csv

当前验证草案 84 条：

| Split / Label / Scene | Count |
| --- | ---: |
| val_draft / non_fall / walk | 26 |
| blocked_relabel_pool / fall / fall | 58 |

说明：

- `blocked_relabel_pool` 不是可训练验证集，只是集中列出需要人工补时间窗的 fall 候选。
- 真正可用的 val 正样本仍需人工补 `fall_start_sec/fall_end_sec` 后重新生成。

### test_manifest_frozen.csv

冻结测试集 58 条，包含 validation、FP regression、GMDCSA public_test、URFD public_test。训练脚本不得读取这些样本。

## Hard Negative Gap

根据现有 draft，hard negative 缺口仍然明显：

| Scene | Current train draft | Minimum target | Gap |
| --- | ---: | ---: | ---: |
| sit | 0 | 80 | 80 |
| squat | 0 | 60 | 60 |
| bend | 1 | 60 | 59 |
| lie_down_non_fall | 0 | 80 | 80 |
| no_person | 0 | 60 | 60 |
| occlusion | 0 | 60 | 60 |

当前 sit/squat/no_person 样本已优先冻结为 FP regression，不能同时拿来训练。必须新增或复核更多同类样本。

## Data Cleaning Status

已在 manifest 生成规则中排除：

- `codec_test_*.mp4`
- 0 字节 / 近零字节视频
- `screen_recording`
- `cropped_recording`
- `frontend_recording`
- `unknown`
- `review_needed`
- 冻结测试集和 FP regression 样本

这些文件没有物理删除，只是在训练草案中排除，保留审计可追溯性。

## Public Dataset Download Plan

下载计划已生成：`artifacts/hardneg_v1_data_preparation/public_dataset_download_plan.csv`

优先级：

1. GMDCSA-24：本地已有，先做时间窗 QA，不重新下载。
2. URFD：本地已有，冻结 public_test 子集，其余等 split 锁定后再决定。
3. Multiple Cameras Fall Dataset：优先下载，补 sit/squat/crouch/lie sofa/occlusion。
4. FallVision：确认原始视频、类别和许可后下载。
5. OmniFall：先作为 taxonomy / temporal segmentation 参考。
6. UP-Fall：第二阶段 temporal/multimodal 参考。

## Training Readiness

当前仍不满足开始训练 `models/yolo_fall_detector_hardneg_v1.pt` 的条件。

阻塞项：

1. 可训练 fall 正样本时间窗不足，`fall_start_sec/fall_end_sec` 未补齐。
2. 当前 `train_manifest_draft.csv` 只有 non_fall，没有可用 fall 正样本。
3. sit/squat/lie_down_non_fall/no_person/occlusion hard negative 训练样本不足。
4. 当前 FP 样本已冻结为 regression set，不能用于训练补洞。
5. public dataset 下载和许可确认尚未完成，尤其 Multiple Cameras Fall Dataset、FallVision、OmniFall、UP-Fall。
6. unknown 样本尚未人工复核，不能进入训练。

建议下一步：

- 人工逐帧/逐秒标注 fall 候选的 `fall_start_sec/fall_end_sec`。
- 本地补采或公开数据补充 sit/squat/bend/lie_down_non_fall/no_person/occlusion。
- 完成 Multiple Cameras Fall Dataset 下载和许可确认。
- 重新生成包含 fall 正样本与 hard negatives 的 train/val manifest。
