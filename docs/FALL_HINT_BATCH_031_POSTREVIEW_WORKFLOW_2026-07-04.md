# Fall Hint Batch 031 Post-Review Workflow

## Purpose

This workflow is for the targeted hard-case audit batch:

- `datasets/fall_hint_v2_raw/batch_031_hardcase_audit`

The batch is designed to reduce:

- empty-scene false positives
- `lying / kneeling / sitting / bending` boundary confusion
- ADL drifting toward `fallen`

## Current Status

As of 2026-07-04, the local labeler is serving:

- `http://127.0.0.1:8082/`
- batch id: `batch_031_hardcase_audit`

The labeler now includes:

- `Reviewed / Draft / Remaining` progress display
- `下一张未审核`
- `保存并下一张未审核`
- shortcut: `Shift + S`

Quick status check:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\report_fall_hint_batch031_status.py
```

## Review Rules

1. Review every image.
2. If the scene is truly empty, save an empty label file.
3. If the draft class is wrong, correct the class.
4. If the draft box is wrong, correct the box.
5. Saving an image must produce:
   - `human_review/labels/<stem>.txt`
   - `human_review/meta/<stem>.json`
   - with `status = reviewed`

## Validate Batch Completion

Run:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\validate_fall_hint_review_batch.py --batch-id batch_031_hardcase_audit --require-all-reviewed --write-report
```

Expected result:

- `frame_count = 120`
- all items are `reviewed`
- `ready_for_merge = true`

Validation outputs:

- `datasets/fall_hint_v2_raw/batch_031_hardcase_audit/meta/review_validation_summary.json`
- `datasets/fall_hint_v2_raw/batch_031_hardcase_audit/meta/review_validation_reviewed_rows.csv`
- `datasets/fall_hint_v2_raw/batch_031_hardcase_audit/meta/review_validation_invalid_items.csv`

## Merge Into Finetune Dataset

Run only after validation passes:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\extend_fall_hint_seed_finetune_with_review_batch.py --batch-id batch_031_hardcase_audit --output datasets/fall_hint_v2_finetune_seed_7_3testmodel_v1_plus_batch031 --overwrite
```

Guardrails:

- merge refuses to run if batch 031 is not fully reviewed
- new samples are added to `train` only
- base `val/test` are preserved
- no augmented data is copied

Merge outputs:

- `datasets/fall_hint_v2_finetune_seed_7_3testmodel_v1_plus_batch031`
- `meta/batch_031_hardcase_audit_added_rows.csv`
- `meta/batch_031_hardcase_audit_merge_summary.json`

## Next Training Step

After merge succeeds, the next safe experiment is:

1. keep runtime model unchanged
2. finetune from the current experimental line
3. evaluate against:
   - current runtime model
   - empty holdout
   - ADL false-fallen diagnostics
   - kneeling/lying confusion diagnostics

Do not replace the runtime model unless the new candidate passes the same acceptance gate.

## One-Command Pipeline

After batch 031 is fully reviewed, the end-to-end pipeline can be started with:

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe scripts\run_fall_hint_batch031_refine_pipeline.py --overwrite-merged
```

Behavior:

- if review is incomplete, the pipeline stops in `waiting_for_manual_review`
- if review is complete, it will:
  1. validate batch 031
  2. merge batch 031 into train only
  3. finetune from the current experimental seed model
  4. evaluate runtime vs candidate_b vs candidate_c vs candidate_d
  5. run threshold sweep for runtime/candidate_b/candidate_c/candidate_d
  6. write a pipeline summary under `runs/fall_hint_batch031_refine`

Important:

- this pipeline does not replace the runtime model automatically
- runtime replacement still requires explicit acceptance by evaluation results
