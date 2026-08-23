# Phase 6 Local ADL Supplement Recording Plan

## Purpose

Use this plan only when public datasets cannot provide enough license-clear ADL subtype clips. Local clips are negative examples for reducing confirmed false positives from sitting, bending, squatting, picking objects, and normal lying down.

## Required Subtypes

Record 5 to 10 short clips per subtype:

- `sitting`: normal sit, fast sit, sit and remain still.
- `bending`: bend to pick something up, bend to arrange objects, bend and recover.
- `squatting`: squat, stay squatting, squat and stand.
- `picking_object`: pick up ground object and recover.
- `lying_down_normal`: slow lie on bed, lie on sofa, sit-to-lie transition.
- `standing`: stand still, turn in place, brief occlusion.
- `walking`: slow walk, turn, approach and leave.

## Capture Rules

- Each clip should be 5 to 15 seconds.
- Use at least two camera distances or angles.
- Keep original videos under `datasets/local_adl/videos`.
- Do not keep only exported feature JSONL files.
- Do not include staged falls in local ADL negative clips.

## Label Manifest

Each clip must be added to `data/phase6_labels/phase6_labels.jsonl`:

```json
{
  "video_id": "local_adl/sitting_001.mp4",
  "source_dataset": "local_adl",
  "license": "project_owned",
  "split_group": "local_adl_sitting_001",
  "binary_label": "non_fall",
  "non_fall_subtype": "sitting",
  "event_start_frame": 0,
  "event_end_frame": null,
  "usable_for_training": true,
  "split": "unassigned",
  "notes": "normal sit and remain still"
}
```

## Acceptance Gate

Before training v2:

- `unknown_adl` must not exceed 20% of non-fall training windows.
- At least sitting, bending, squatting, picking_object, and lying_down_normal should exist in the validation or test split.
- `split_group` must never appear in more than one split.
