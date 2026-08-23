# Fall Clean v1 Public Dataset Plan 20260623

## Decision

Stop using the contaminated local `hardneg_v1_min` candidate set as the primary training source. Build a clean public-data-first dataset under `datasets/fall_clean_v1/`.

## Answers

1. Local data quarantined: generated `hardneg_v1_min` train/val candidates, visual-QA positive repairs/removals, rejected val hard-negative candidates, and post-QA rejected/manual-review items. Reasons: incomplete independent val hard-negative coverage, inconsistent scene names vs visual content, phase-boundary positive labels, and local candidate contamination risk.
2. Evaluation assets retained: `test_manifest_frozen.csv` and `fp_regression_set.csv`, written to `frozen_eval_assets.csv` as `evaluation_only_do_not_train`.
3. Priority public datasets: Multiple Cameras Fall Dataset, GMDCSA-24, UR Fall Detection Dataset, then FallVision/UP-Fall as verified supplements; OmniFall mainly taxonomy/sensor reference.
4. Scene supplementation: Multiple Cameras and GMDCSA/URFD should cover fall/fallen/walk/sit/stand and some ADL; UP-Fall may supplement sit/stand/walk/object-pick/bend-like taxonomy; FallVision only after access/schema verification; OmniFall is not primary YOLO due sensor modality.
5. Download/cleaning readiness: can start license verification and controlled download/inventory for top-priority public datasets.
6. Training readiness: **尚不能训练，只能进入公开数据集下载与清洗阶段。**

## Required Target Taxonomy

- fall
- fallen
- lying
- walk
- stand
- sit
- squat / crouch
- bend
- lie_down_non_fall
- no_person
- occlusion
- sofa/bed/chair non_fall
- recovery / getting_up

## Public Dataset Candidate Manifest

See `datasets/fall_clean_v1/manifests/public_dataset_candidates.csv`.

## Download Plan

See `datasets/fall_clean_v1/manifests/download_plan.csv`. Every dataset requires license/terms verification before download/use. Downloaded raw files must remain under `raw_public/` and must not enter YOLO training until inventory, split locking, fall-window labeling, and bbox QA are complete.

## Safety

No model training was started. No model weights were generated. Baseline was not overwritten. `.env` and production code were not modified. No git add/commit was performed.
