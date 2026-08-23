# Phase 6C v2 Comparison Report

## Decision

```text
Phase 6C ADL subtype review = passed
v2 training = passed
Production provider = mock
Recommended runtime provider = shadow
onnx_lstm promotion = paused
```

## Label Quality

- Reviewed ADL videos: 40
- Usable ADL videos: 33
- unknown_adl ratio: 17.50%
- Subtype counts: `{"squatting": 8, "picking_object": 3, "bending": 5, "sitting": 8, "lying_down_normal": 9, "unknown_adl": 7}`

## v2 Training

- Samples: 206
- Positive samples: 37
- Negative samples: 169
- Split counts: `{"train": 206, "test": 43, "val": 54}`
- ONNX validation: passed=True max_abs_diff=0.0

## Provider Comparison

| Provider | ADL confirmed FP | Fall falling recall | Fall confirmed recall | Source evidence |
| --- | ---: | ---: | ---: | --- |
| mock | 0 | 0.2333 | 0.0000 | `{"mock": 70}` |
| onnx_lstm_v1 | 0 | 0.2333 | 0.0000 | `{"warming_up": 70, "onnx_lstm": 11}` |
| onnx_lstm_v2 | 0 | 0.2333 | 0.0000 | `{"warming_up": 70, "onnx_lstm": 11}` |
| shadow_v2 | 0 | 0.2333 | 0.0000 | `{"warming_up": 70, "shadow_onnx_lstm": 11}` |

## Promotion Gate

- adl_confirmed_fp_not_higher_than_mock: `true`
- each_adl_subtype_confirmed_fp_not_higher_than_mock: `true`
- fall_recall_improved_or_delay_lower: `false`
- onnx_validation_passed: `true`
- schema_match: `true`
- fallback_ok: `true`
- shadow_records_onnx_output: `true`

Current decision: keep production on `mock`, run recommended runtime as `shadow`, and do not promote `onnx_lstm` yet. v2 kept ADL false positives at zero but did not improve fall recall over mock on the held-out UR Fall evaluation.

## Artifacts

- `evaluations/phase6c_v2_comparison_001.json`
- `evaluations/phase6c_provider_eval/*_summary.json`
- `models/fall_lstm_v2.onnx`
- `models/fall_lstm_v2_features.json`
- `models/fall_lstm_v2_metrics.json`
