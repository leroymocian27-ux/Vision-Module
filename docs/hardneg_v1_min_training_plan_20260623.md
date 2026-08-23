# Hardneg v1 Min Smoke Training Plan 20260623

## Status

未训练。

The reviewed minimum dataset has been built at:

`D:\Program\vision_service\artifacts\yolo_fall_hardneg_v1_min_dataset`

The current gate result is **PASS**.

This is a small smoke-training candidate only. It must not be described as a formal replacement for the current baseline, and it must not be wired into production runtime without a separate evaluation and promotion step.

## Safety Boundaries

- Do not overwrite `models/yolo_fall_detector_phase9_selected.pt`.
- Do not modify `.env`.
- Do not modify production service code.
- Do not send real POST requests.
- Do not run `git add` or `git commit` as part of this preparation.
- Do not connect the new model to runtime automatically.

## Dataset Summary

| Metric | Count |
| --- | ---: |
| train positive images | 18 |
| val positive images | 10 |
| train hard negative images | 85 |
| val hard negative images | 5 |
| needs bbox annotation | 0 |
| frozen/FP leakage | 0 |

## Proposed Smoke Training Command

Run only after explicit user confirmation:

```powershell
cd D:\Program\vision_service
yolo detect train `
  model=models\yolo_fall_detector_phase9_selected.pt `
  data=artifacts\yolo_fall_hardneg_v1_min_dataset\data.yaml `
  epochs=20 `
  imgsz=640 `
  batch=4 `
  project=artifacts\training_runs `
  name=yolo_fall_detector_hardneg_v1_min_smoke `
  exist_ok=False
```

After training, copy the selected smoke weight manually only after evaluation, for example:

```powershell
Copy-Item artifacts\training_runs\yolo_fall_detector_hardneg_v1_min_smoke\weights\best.pt `
  models\yolo_fall_detector_hardneg_v1_min.pt
```

Do not overwrite the baseline weight.

## Post-Training Evaluation Required

Before any promotion discussion, evaluate against:

- frozen labeled validation set
- FP regression set
- public frozen test subsets
- hard-negative scenes: walk, sit, squat, bend, lie_down_non_fall, no_person, occlusion

Promotion should require precision/false-positive improvement without materially harming fall recall.

