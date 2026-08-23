# 姿态检测当前基线报告

生成时间：`2026-07-05T13:03:56.648326+00:00`

## 当前配置

- `POSE_PROVIDER`: `yolo11_legacy`
- `YOLO11_POSE_MODEL_PATH`: `yolo11n-pose.pt`
- `POSE_FPS`: `3`
- `POSE_WORKER_FPS`: `3`
- `POSE_RESULT_TTL_MS`: `800`
- `POSE_MAX_FRAME_AGE_MS`: `800`
- `POSE_MAX_TRACKING_FRAME_DELTA`: `2`
- `POSE_SKIP_WHEN_INFERENCE_BUSY`: `true`

## 模型资产

- `YOLO_POSE_MODEL_PATH`: exists=True size=6832633 sha256=c6fa93dd1ee4
- `YOLO11_POSE_MODEL_PATH`: exists=True size=6255593 sha256=869e83fcdffd
- `YOLO_MODEL_PATH`: exists=True size=6549796 sha256=f59b3d833e2f
- `YOLO_FALL_MODEL_PATH`: exists=True size=5461914 sha256=4bafc88b2ec0
- `TEMPORAL_ONNX_MODEL_PATH`: exists=True size=85630 sha256=01af710c6f89

## 离线姿态指标

- baseline: `yolo11n-pose.pt`, pose mAP50-95 `0.883491`, inference `16.359573 ms`
- candidate: `models/pose_yolo_batch001_003_yolo11s_best.pt`, pose mAP50-95 `0.848643`, inference `11.750265 ms`
- delta pose mAP50-95: `-0.034848`

## 端到端运行证据

- samples: `30`
- pose provider: `yolo`
- pose_valid: `0.3`
- pose_fps: `0.67`
- skipped_due_to_busy: `137`
- last inference latency: `31.0 ms`

## LSTM 姿态闭环

- temporal dir: `D:\Program\vision_service\data\temporal_sequences_phase6d`
- jsonl files: `167`
- rows: `6659`
- pose field rows: `6659`
- pose_available true rows: `0`
- pose_available true ratio: `0.0`
- pose quality counts: `{'unknown': 6659}`
- pose rejected reasons: `{}`

## 诊断结论

- pose_valid 低于 0.70 门槛；先修运行链路，再谈重训是否有意义。
- 存在 busy skip；worker 频率、推理锁竞争和 TTL 是第一嫌疑人。
- 时序训练数据有姿态字段名，但没有真实可用姿态证据，LSTM 实际没学到姿态。
- 时序训练数据缺少 pose_quality_level，无法区分缺失、低质、错绑和高质量姿态。
- 当前 yolo11s 候选更快，但 pose mAP50-95 低于 baseline，不能凭感觉上线。
- 当前 .env provider 是 yolo11_legacy，但 E2E 证据 provider 是 yolo；后续必须用当前配置重跑基线。

## 下一步门槛

- 姿态链路先把 `pose_valid_rate` 拉到 `>= 0.70`，再进入正式重训。
- 前端骨架可见率目标 `>= 0.60`。
- `pose_track_mismatch_rate` 必须控制到 `<= 0.05`。
- 新 LSTM 数据中 `pose_available_true_rows` 不能再是 0。
