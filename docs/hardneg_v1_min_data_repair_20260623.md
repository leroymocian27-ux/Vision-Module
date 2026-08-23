# Hardneg v1 Min Data Repair 20260623

## Scope

This stage repaired the `hardneg_v1_min` dataset after final visual QA. It did not train a model, did not generate `models/yolo_fall_detector_hardneg_v1_min.pt`, did not overwrite `models/yolo_fall_detector_phase9_selected.pt`, did not modify `.env`, did not modify production code, and did not run git add/commit.

## Positive Issue Repair

- Removed from training candidates: item_00033, item_00044, item_00048, item_00052, item_00079, item_00083, item_00085
- Corrected class: `item_00060` -> `lying`

Suspicious boundary frames were not forced to remain positive.

## Val Hard Negative Repair

Rebuilt val hard negatives from existing human-confirmed hard-negative candidates. Remaining gaps:

- `squat`: required 2, have 1, gap 1
- `bend`: required 2, have 1, gap 1
- `no_person`: required 2, have 1, gap 1

## Gate Result

Final gate: **BLOCKED**

The dataset is not ready for smoke training until val hard-negative coverage is complete.

## Outputs Updated

- `artifacts/yolo_fall_hardneg_v1_min_dataset/train_manifest_final_from_review.csv`
- `artifacts/yolo_fall_hardneg_v1_min_dataset/val_manifest_final_from_review.csv`
- `artifacts/yolo_fall_hardneg_v1_min_dataset/data.yaml`
- `artifacts/yolo_fall_hardneg_v1_min_dataset/dataset_final_gate_report.md`
- `artifacts/yolo_fall_hardneg_v1_min_dataset/final_visual_qa/final_visual_qa_report.md`
- `artifacts/yolo_fall_hardneg_v1_min_dataset/final_visual_qa/final_visual_qa_issues.csv`
- `artifacts/yolo_fall_hardneg_v1_min_dataset/final_visual_qa/positive_repair_decisions.csv`
- `artifacts/yolo_fall_hardneg_v1_min_dataset/final_visual_qa/val_hard_negative_gap.csv`

## Recommendation

Continue data repair by collecting or reviewing independent val hard negatives for the missing scenes. Do not resume smoke training yet.
