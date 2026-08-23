# 跌倒混淆矩阵生成流程

本文档说明如何使用当前系统模型生成跌倒/非跌倒二分类混淆矩阵。推荐口径是视频事件级：一个视频样本最终是否触发跌倒告警，而不是单帧 YOLO mAP。

## 当前模型链路

- YOLO fall hint: `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt`，由 `models/model_locator.json` 标记为活动 fall hint 模型。
- YOLO Pose: `models/pose_yolo_batch001_003_yolo11s_best.pt`，活动姿态模型。
- LSTM: `models/fall_lstm_v5.onnx`，配套 schema 为 `models/fall_lstm_v5_features.json`。

## 准备视频 manifest

先准备一个带真实标签的视频清单，例如 `data/eval/fall_matrix_manifest.json`：

```json
{
  "videos": [
    {
      "path": "D:/datasets/fall_eval/fall_001.mp4",
      "label": "fall",
      "expected_alarm": true,
      "fall_start_ms": 1200,
      "fall_end_ms": 4200
    },
    {
      "path": "D:/datasets/fall_eval/adl_001.mp4",
      "label": "non_fall",
      "expected_alarm": false
    }
  ]
}
```

`expected_alarm=true` 会计入真实跌倒；`expected_alarm=false` 会计入真实非跌倒。脚本会根据最终是否出现 `alarm_confirmed_frames` 或 `confirmed_frames` 计算 TP/FP/FN/TN。

## 跑当前完整模型链路

完整链路对应“YOLO + YOLO Pose + LSTM”：

```powershell
$env:ENABLE_POSE="true"
$env:POSE_PROVIDER="yolo"
$env:YOLO_FALL_MODEL_PATH="models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt"
$env:YOLO11_POSE_MODEL_PATH="models/pose_yolo_batch001_003_yolo11s_best.pt"
$env:ENABLE_TEMPORAL="true"
$env:TEMPORAL_MODEL_PROVIDER="onnx_lstm"
$env:TEMPORAL_ONNX_MODEL_PATH="models/fall_lstm_v5.onnx"
$env:TEMPORAL_FEATURE_SCHEMA_PATH="models/fall_lstm_v5_features.json"
$env:TEMPORAL_ONNX_PROVIDERS="CPUExecutionProvider"
python scripts\evaluate_fall_video_offline.py `
  --manifest data\eval\fall_matrix_manifest.json `
  --output-dir logs\offline_fall_eval\fall_matrix_yolo_pose_lstm
```

然后生成矩阵：

```powershell
python scripts\create_fall_confusion_matrices.py `
  --input logs\offline_fall_eval\fall_matrix_yolo_pose_lstm\offline_fall_eval_summary.json `
  --title "YOLO + YOLO Pose + LSTM" `
  --output-dir reports\fall_confusion_matrix
```

输出文件：

- `reports/fall_confusion_matrix/fall_confusion_matrices.svg`
- `reports/fall_confusion_matrix/fall_confusion_matrices.csv`
- `reports/fall_confusion_matrix/fall_confusion_matrices.json`
- `reports/fall_confusion_matrix/fall_confusion_matrices.md`

## 做三组对比

可以分别跑三次离线评估：

```powershell
# 1. YOLO only
$env:YOLO_FALL_MODEL_PATH="models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt"
$env:ENABLE_POSE="false"
$env:ENABLE_TEMPORAL="false"
python scripts\evaluate_fall_video_offline.py `
  --manifest data\eval\fall_matrix_manifest.json `
  --output-dir logs\offline_fall_eval\fall_matrix_yolo_only

# 2. YOLO + YOLO Pose
$env:ENABLE_POSE="true"
$env:POSE_PROVIDER="yolo"
$env:YOLO_FALL_MODEL_PATH="models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt"
$env:YOLO11_POSE_MODEL_PATH="models/pose_yolo_batch001_003_yolo11s_best.pt"
$env:ENABLE_TEMPORAL="false"
python scripts\evaluate_fall_video_offline.py `
  --manifest data\eval\fall_matrix_manifest.json `
  --output-dir logs\offline_fall_eval\fall_matrix_yolo_pose

# 3. YOLO + YOLO Pose + LSTM
$env:ENABLE_POSE="true"
$env:POSE_PROVIDER="yolo"
$env:YOLO_FALL_MODEL_PATH="models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt"
$env:ENABLE_TEMPORAL="true"
$env:TEMPORAL_MODEL_PROVIDER="onnx_lstm"
$env:TEMPORAL_ONNX_MODEL_PATH="models/fall_lstm_v5.onnx"
$env:TEMPORAL_FEATURE_SCHEMA_PATH="models/fall_lstm_v5_features.json"
$env:TEMPORAL_ONNX_PROVIDERS="CPUExecutionProvider"
python scripts\evaluate_fall_video_offline.py `
  --manifest data\eval\fall_matrix_manifest.json `
  --output-dir logs\offline_fall_eval\fall_matrix_yolo_pose_lstm
```

再合成一张横向对比图：

```powershell
python scripts\create_fall_confusion_matrices.py `
  --panel "YOLO=logs\offline_fall_eval\fall_matrix_yolo_only\offline_fall_eval_summary.json" `
  --panel "YOLO + YOLO Pose=logs\offline_fall_eval\fall_matrix_yolo_pose\offline_fall_eval_summary.json" `
  --panel "YOLO + YOLO Pose + LSTM=logs\offline_fall_eval\fall_matrix_yolo_pose_lstm\offline_fall_eval_summary.json" `
  --output-dir reports\fall_confusion_matrix
```

## 注意事项

- 三个矩阵必须使用同一份 manifest，否则 Accuracy/Recall/F1 不能公平对比。
- `models/*_metrics.json` 中的 YOLO mAP 指标不是事件级混淆矩阵；如果要复现截图里的 TN/FP/FN/TP，应优先使用离线视频评估输出。
- 如果只评估 LSTM 窗口级结果，可以使用 `scripts\evaluate_fall_lstm_metrics.py` 生成带 `event_metrics.confusion` 的 JSON，再交给 `scripts\create_fall_confusion_matrices.py` 渲染。
