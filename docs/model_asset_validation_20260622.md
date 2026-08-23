# Model Asset Validation - 2026-06-22

## 1. 核验时间

- 执行时间：2026-06-23 00:03:33 +08:00
- 报告文件名沿用演示收口日期：`model_asset_validation_20260622.md`
- 项目路径：`D:\Program\vision_service`

## 2. 核验边界

本次只做模型文件和独立加载能力核验，边界如下：

- 只读检查模型文件、配置路径、文件大小、修改时间和 SHA256。
- 只读检查 `.env` / `.env.example` 中的模型路径和开关配置。
- 仅在独立 Python 进程中执行 `import` 和权重对象加载。
- 未调用 `/stream/start`。
- 未切换摄像头，未打开摄像头动作测试。
- 未运行本地 replay，未跑跌倒流程。
- 未修改生产代码。
- 未修改 `.env`。
- 未启用 `pose_use_for_fall` / Pose 跌倒判断。
- 未启用 Temporal。
- 未训练模型。
- 未调用真实 POST。
- 未执行 `git add` 或 `git commit`。

## 3. 依赖版本

| 依赖 | 核验结果 |
| --- | --- |
| Python | 3.9.13 |
| ultralytics | 8.4.67 |
| torch | 2.8.0+cpu |
| cv2 / OpenCV | 4.13.0 |
| onnxruntime | 1.19.2 |
| CUDA | 不可用，`torch.cuda.is_available() == false`，`device_count=0`，`torch.version.cuda=null` |
| ByteTrack | `from ultralytics.trackers.byte_tracker import BYTETracker` 成功 |

## 4. `.env` 路径和开关核验

| 配置项 | 当前值 | 说明 |
| --- | --- | --- |
| `YOLO_MODEL_PATH` | `yolov8n.pt` | 明天演示主链路：YOLO person 检测 |
| `YOLO_FALL_MODEL_PATH` | `models/yolo_fall_detector_phase9_selected.pt` | 明天演示主链路：YOLO fall detector |
| `BYTETRACK_TRACK_HIGH_THRESH` | `0.5` | ByteTrack 配置，非模型 |
| `BYTETRACK_TRACK_LOW_THRESH` | `0.1` | ByteTrack 配置，非模型 |
| `BYTETRACK_NEW_TRACK_THRESH` | `0.6` | ByteTrack 配置，非模型 |
| `BYTETRACK_MATCH_THRESH` | `0.8` | ByteTrack 配置，非模型 |
| `BYTETRACK_TRACK_BUFFER` | `30` | ByteTrack 配置，非模型 |
| `BYTETRACK_FRAME_RATE` | `10` | ByteTrack 配置，非模型 |
| `BYTETRACK_FUSE_SCORE` | `true` | ByteTrack 配置，非模型 |
| `ENABLE_POSE` | `false` | 明天采用 no-pose 安全基线 |
| `POSE_PROVIDER` | `disabled_placeholder` | Pose provider 未启用 |
| `YOLO_POSE_MODEL_PATH` | `yolov8n-pose.pt` | Pose 资产存在并可独立加载，但不接入明天实时跌倒判断 |
| `ENABLE_TEMPORAL` | `false` | Temporal 未启用 |
| `TEMPORAL_ONNX_MODEL_PATH` | `models/fall_lstm_v5.onnx` | Temporal / LSTM 资产只做只读核验 |
| `TEMPORAL_FEATURE_SCHEMA_PATH` | `models/fall_lstm_v5_features.json` | Temporal 特征 schema 只做只读核验 |
| `MAIN_SYSTEM_REPORT_DRY_RUN` | `true` | 保持 dry-run，不真实 POST |

补充：`.env.example` 中存在 `YOLO11_POSE_MODEL_PATH=D:\Program\health(5-12)\pose_detection_model_bundle\yolo11n-pose.pt`，但当前项目根目录下也存在 `yolo11n-pose.pt`，本次按当前工作区本地文件独立加载核验。

## 5. 模型清单

| 模型名称 | 路径 | 用途 | 是否存在 | 文件大小 | 修改时间 | SHA256 | 加载状态 |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| YOLO person 检测模型 | `yolov8n.pt` | 明天演示主链路，人体检测 | 是 | 6,549,796 bytes | 2026-06-02 10:10:13 | `F59B3D833E2FF32E194B5BB8E08D211DC7C5BDF144B90D2C8412C47CCFC83B36` | OK，`YOLO()` 加载成功，task=`detect`，class=`DetectionModel`，names=80 |
| YOLO fall detector | `models/yolo_fall_detector_phase9_selected.pt` | 明天演示主链路，跌倒检测候选/确认链路输入 | 是 | 19,181,530 bytes | 2026-06-08 11:02:38 | `73D47684FD0B8558F0C6AE76A63C643ACC26A66F2ECD0667E00D059D0BA1DF49` | OK，`YOLO()` 加载成功，task=`detect`，class=`DetectionModel`，names=8 |
| YOLO11 pose | `yolo11n-pose.pt` | 后续能力 / 离线说明，明天不启用 | 是 | 6,255,593 bytes | 2026-06-18 10:00:48 | `869E83FCDFFDC7371FA4E34CD8E51C838CC729571D1635E5141E3075E9319DC0` | OK，`YOLO()` 加载成功，task=`pose`，class=`PoseModel`，names=1 |
| YOLOv8 pose | `yolov8n-pose.pt` | 后续能力 / `.env` 当前 pose 路径，明天不启用 | 是 | 6,832,633 bytes | 2026-06-03 16:42:11 | `C6FA93DD1EE4A2C18C900A45C1D864A1C6F7ABA75D84F91648A30B7FB641D212` | OK，`YOLO()` 加载成功，task=`pose`，class=`PoseModel`，names=1 |
| Temporal / LSTM v5 ONNX | `models/fall_lstm_v5.onnx` | 后续能力 / Temporal，只读核验，明天不启用 | 是 | 85,630 bytes | 2026-06-08 14:42:06 | `01AF710C6F8996EA0B894EF063956121988F32DF6DF10208F21EDA4869FB0A8C` | OK，`onnxruntime.InferenceSession` CPU provider 加载成功 |
| Temporal / LSTM v5 feature schema | `models/fall_lstm_v5_features.json` | 后续能力 / Temporal 特征 schema，只读核验 | 是 | 729 bytes | 2026-06-08 14:42:06 | `36EC2CF4E64E08B40E55F0F0C9A3BD83226D7C4BC0720921861440EB0BCAFD9F` | N/A，schema 文件只读清点 |
| VisualRiskMarker runtime observable | `scripts/fast_pose_fall/visual_risk_mark_runtime_observable.py` | 0-5 VisualRiskMarker 后续能力 / 半接入说明 | 是 | 6,977 bytes | 2026-06-22 18:18:22 | `9907330E0ED64862ACB435F237A2AA160A3B204C58F9AAE5BFF887E7B9309BD8` | N/A，脚本资产只读清点，未接入 runtime |
| VisualRiskMarker offline | `scripts/fast_pose_fall/visual_risk_mark_offline.py` | 0-5 VisualRiskMarker 离线说明 | 是 | 6,327 bytes | 2026-06-22 17:54:33 | `24B3510FA84B048D40CFBA946FBFC3EC83B56BD54D7F1DBC47E57D8DDEF4DDAC` | N/A，脚本资产只读清点，未接入 runtime |
| ByteTrack | ultralytics 内置 `BYTETracker` + `.env` 阈值配置 | 明天演示主链路，目标跟踪 | N/A | N/A | N/A | N/A | OK，依赖导入成功；ByteTrack 是跟踪算法依赖和配置，不是模型文件 |

## 6. 各模型加载结果

独立 Python 进程中仅执行权重对象加载，没有执行预测、视频读取、摄像头访问或 replay。

| 权重 | 加载方式 | 结果 |
| --- | --- | --- |
| `yolov8n.pt` | `ultralytics.YOLO("yolov8n.pt")` | 成功，task=`detect` |
| `models/yolo_fall_detector_phase9_selected.pt` | `ultralytics.YOLO("models/yolo_fall_detector_phase9_selected.pt")` | 成功，task=`detect` |
| `yolo11n-pose.pt` | `ultralytics.YOLO("yolo11n-pose.pt")` | 成功，task=`pose` |
| `yolov8n-pose.pt` | `ultralytics.YOLO("yolov8n-pose.pt")` | 成功，task=`pose` |
| `models/fall_lstm_v5.onnx` | `onnxruntime.InferenceSession(..., providers=["CPUExecutionProvider"])` | 成功，input=`["batch", 32, 15]`，output=`fall_probability ["batch", 1]` |

## 7. Temporal / GRU / LSTM / VisualRiskMarker 只读清点

- LSTM / Temporal 资产存在：`models/fall_lstm*.onnx`、`models/fall_lstm*_features.json`、metrics、threshold calibration、train config 等。
- 当前 `.env` 指向 `models/fall_lstm_v5.onnx` 和 `models/fall_lstm_v5_features.json`，但 `ENABLE_TEMPORAL=false`。
- Temporal runtime 相关代码存在于 `app\temporal\*` 和 `app\services\temporal_service.py`，本次未改动、未启用。
- VisualRiskMarker / 0-5 风险标记相关脚本和评估报告存在于 `scripts\fast_pose_fall\*` 与 `evaluations\fast_pose_fall\*`，本次只读清点，未作为明天实时主功能展示。
- 未发现单独以 `gru` 命名的模型资产或配置文件；本次仅按当前文件树做只读清点，不新增 GRU 资产。

## 8. 明天演示主链路模型

明天演示主链路建议保持：

- `yolov8n.pt`：RTSP 摄像头在线能力展示中的人体检测。
- `models/yolo_fall_detector_phase9_selected.pt`：本地 replay 跌倒确认主证明链路中的 YOLO fall detector。
- ByteTrack：目标跟踪依赖和配置，展示 track id / tracking 输出；注意它不是模型文件。
- WebRTC / WebSocket / Polling / dry-run reporter：作为链路能力展示，不属于本次模型资产范围。

## 9. 后续能力或离线说明资产

以下资产本次核验通过或已清点，但不建议作为明天实时主功能展示：

- `yolo11n-pose.pt`：Pose 模型可独立加载，明天不启用。
- `yolov8n-pose.pt`：`.env` 当前 pose 路径资产可独立加载，明天不启用。
- `models/fall_lstm_v5.onnx`：Temporal / LSTM 可由 onnxruntime CPU provider 独立加载，明天不启用。
- `models/fall_lstm_v5_features.json`：Temporal feature schema 已清点，明天不启用。
- 0-5 VisualRiskMarker：当前仍主要作为离线/半接入能力说明，不作为实时主链路能力展示。

## 10. 风险说明

- 当前 torch 为 `2.8.0+cpu`，CUDA 不可用；实时推理性能应按 CPU 推理预期沟通。
- Pose 模型虽然存在并可加载，但 `.env` 中 `ENABLE_POSE=false`、`POSE_PROVIDER=disabled_placeholder`；明天采用 no-pose 安全基线。
- Temporal / LSTM 虽然存在并可由 onnxruntime 加载，但 `.env` 中 `ENABLE_TEMPORAL=false`；明天不启用 Temporal。
- 0-5 VisualRiskMarker 仍主要是离线/半接入能力，不作为明天实时主功能展示。
- 本次没有验证摄像头实时效果、没有跑 replay、没有产生新的 `fallen_confirmed` 证据；跌倒确认主证明仍沿用此前本地 replay 稳定证据。
- 当前报告确认的是模型资产存在性、路径清晰度、hash 可追溯性和独立加载能力，不等价于现场动作稳定触发保证。

## 11. 明天演示建议

- 保持当前 no-pose 安全基线，不启用 pose 参与跌倒判断。
- 保持 `MAIN_SYSTEM_REPORT_DRY_RUN=true`，不向主系统真实发送告警。
- 现场 RTSP 摄像头用于展示在线能力：RTSP 接入、视频解码、WebRTC 实时画面、YOLO 人体检测、ByteTrack 跟踪、风险字段输出和 dry-run 事件状态。
- 本地 replay 用于稳定证明跌倒确认链路，因为现场动作、角度、遮挡和安全因素会影响实时触发稳定性。
- 不在演示前临时启用 Temporal、VisualRiskMarker 实时主接入或新的多模态能力。

## 12. 核验结论

模型资产核验通过。

验收口径中的四个 YOLO 权重均已独立加载成功：

- `yolov8n.pt`
- `models/yolo_fall_detector_phase9_selected.pt`
- `yolo11n-pose.pt`
- `yolov8n-pose.pt`

路径、文件大小、修改时间、SHA256、依赖版本和加载状态均已记录完整。ByteTrack 依赖导入成功，并已明确标注为算法依赖和配置而非模型。Temporal / LSTM / VisualRiskMarker 相关资产已只读清点，未启用、未接入 runtime。
