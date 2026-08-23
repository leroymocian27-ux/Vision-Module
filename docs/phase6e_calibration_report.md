# Phase 6E Calibration Report

## Provider Aggregate

| Provider | ADL confirmed FP | ADL candidate FP | Falling recall | Candidate recall | Confirmed recall | Avg first falling delay ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mock | 0 | 0 | 0.3000 | 0.0000 | 0.0000 | 3066.7 |
| onnx_lstm_v2 | 0 | 0 | 0.3000 | 0.0000 | 0.0000 | 3066.7 |
| onnx_lstm_v3 | 0 | 0 | 0.3125 | 0.0000 | 0.0000 | 3216.0 |
| shadow_v3 | 0 | 0 | 0.3000 | 0.0000 | 0.0000 | 3066.7 |

## Model Threshold Sweep

- Test AUC: 0.7092
- Best threshold: `{"threshold": 0.5, "tp": 25, "fp": 14, "tn": 110, "fn": 27, "precision": 0.641, "recall": 0.4808, "f1": 0.5495, "subtype_fp": {"walking": 11, "bending": 1, "squatting": 2}}`

## Promotion Gate

- adl_confirmed_fp_not_higher_than_mock: `true`
- each_adl_subtype_confirmed_fp_not_higher_than_mock: `true`
- fall_falling_recall_higher_than_mock: `true`
- first_falling_delay_lower_than_mock: `false`
- onnx_validation_passed: `true`
- schema_match: `true`
- fallback_ok: `true`
- shadow_records_onnx_output: `true`

Decision: keep `Production provider = mock` and `Recommended runtime provider = shadow`; `onnx_lstm` is eligible only for a controlled local/test-camera trial.
Reason: v3 improves aggregate falling recall and keeps confirmed FP at zero, but ADL falling FP exists and candidate/confirmed recall remains zero, so it must not become the default production provider.
