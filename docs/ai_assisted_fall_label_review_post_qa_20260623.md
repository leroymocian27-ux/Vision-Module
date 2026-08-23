# AI-assisted Fall Label Review Post-QA Audit 20260623

## Scope

This audit reads the completed human button-review outputs and classifies each latest reviewed item into YOLO-ready positives, positives that still need boxes, hard-negative empty-label candidates, and excluded/manual-review samples.

No model training was started. `models/yolo_fall_detector_phase9_selected.pt` was not modified. `.env`, production code, training manifests, `data.yaml`, git staging, and commits were not touched.

## Inputs

- `artifacts/ai_assisted_fall_label_review/review_decisions.csv`
- `artifacts/ai_assisted_fall_label_review/review_decisions.jsonl`
- `artifacts/ai_assisted_fall_label_review/review_items.csv`
- `artifacts/hardneg_v1_data_preparation/test_manifest_frozen.csv`
- `artifacts/hardneg_v1_data_preparation/fp_regression_set.csv`

## Outputs

- `artifacts/ai_assisted_fall_label_review/post_qa_audit.csv`
- `artifacts/ai_assisted_fall_label_review/usable_yolo_positive.csv`
- `artifacts/ai_assisted_fall_label_review/needs_bbox_annotation.csv`
- `artifacts/ai_assisted_fall_label_review/hard_negative_empty_label.csv`
- `artifacts/ai_assisted_fall_label_review/review_post_qa_summary.json`

## Summary

| Metric | Count |
| --- | ---: |
| Total reviewed unique items | 157 |
| Raw decision rows | 160 |
| JSONL decision rows | 160 |
| human_verified total | 28 |
| human_verified fall/fallen/lying with valid bbox | 28 |
| human_verified fall/fallen/lying without valid bbox | 0 |
| rejected | 111 |
| ignored | 0 |
| uncertain/manual_review_required | 4 |
| hard negative empty-label candidates | 90 |
| frozen/FP accepted leakage | 0 |

## Category Counts

- `hard_negative_empty_label`: 90
- `manual_review_required`: 18
- `rejected_non_fall_or_bad_label`: 21
- `usable_yolo_positive`: 28

## YOLO Positive Split

- train usable positives: 18
- val usable positives: 10
- needs bbox annotation: 0

## Hard Negative Coverage

- `bend`: 1
- `lie_down_non_fall`: 3
- `no_person`: 1
- `occlusion`: 8
- `sit`: 2
- `squat`: 1
- `stand`: 5
- `walk`: 69

Covered required hard-negative scenes: walk, sit, squat, bend, lie_down_non_fall, no_person, occlusion.

Missing required hard-negative scenes: none.

## Training Gate

Result: **PASS**

Reason: `pass`

The next training-preparation phase must not include `needs_bbox_annotation.csv` directly in YOLO training. Those accepted semantic positives need bbox annotation first. Frozen test and FP regression leakage is currently 0.

