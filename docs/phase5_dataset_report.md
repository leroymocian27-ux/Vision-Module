# Phase 5 Dataset Evaluation Report

This report evaluates the current rule-based Temporal Decision Layer.
It does not train models, does not use GRU/LSTM, and does not modify runtime rules.

## Summary

- Tested videos: 2
- Normal videos: 0
- Fall videos: 2
- False positive confirmed: 0
- False positive candidate: 0
- Fall detected: 0
- Fall missed: 2
- ADL unstable rate: 0/0 (0.00%)
- ADL candidate FP: 0
- ADL confirmed FP: 0
- Fall falling recall: 0/2 (0.00%)
- Fall candidate recall: 0/2 (0.00%)
- Fall confirmed recall: 0/2 (0.00%)

## Per Video

- `ur_fall_cam1/fall-01-cam1.mp4` label=fall frames=160 subtype=None sampled=32 max_prob=0.05 states=['normal'] confirmed=False risk_peak=low max_vy=0.0 max_dy=0.0 max_ratio=0.53 pose_frames=0 shadow_sources=['warming_up'] max_shadow_prob=0.00
- `ur_fall_cam1/fall-02-cam1.mp4` label=fall frames=110 subtype=None sampled=22 max_prob=0.11 states=['normal'] confirmed=False risk_peak=low max_vy=1025.6 max_dy=16.4 max_ratio=2.01 pose_frames=0 shadow_sources=['warming_up'] max_shadow_prob=0.00

## Suggestions

- Some fall videos were missed: lower rapid descent thresholds or add bbox center-y trend features.
- Editable files for next tuning: app/temporal/mock_sequence_model.py and app/temporal/fall_state_machine.py.

## Artifacts

- `D:\Program\vision_service\logs\phase5_dataset_eval\summary.json`
- `D:\Program\vision_service\logs\phase5_dataset_eval\per_video.jsonl`
