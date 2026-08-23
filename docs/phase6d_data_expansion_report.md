# Phase 6D Data Expansion Report

## Summary

- Added GMDCSA-24 from Zenodo record 10889217, CC BY 4.0.
- Added two UR Fall cam1 fall videos to reach the Phase 6D fall-count gate.
- Label manifest now has 184 rows: 80 fall and 104 non_fall.
- Training-usable rows: 167; usable non_fall unknown_adl ratio: 0%.

## v3 Training

- Samples: 735
- Positive samples: 91
- Negative samples: 644
- Subtype window counts: `{"lying_down_normal": 311, "sitting": 121, "walking": 219, "standing": 83, "fall": 165, "bending": 70, "squatting": 55, "picking_object": 32}`
- ONNX validation: `{'passed': True, 'max_abs_diff': 5.960464477539063e-08}`

## Decision

Phase 6D data expansion and v3 training passed. v3 is a candidate model for shadow/runtime evaluation, not a production default.
