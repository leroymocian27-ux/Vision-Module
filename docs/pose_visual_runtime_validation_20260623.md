# Pose Visual Runtime Validation - 2026-06-23

## 1. 核验时间

- 执行时间：2026-06-23 00:42:46 +08:00
- 项目路径：`D:\Program\vision_service`
- 结论：PARTIAL

## 2. 核验边界

本阶段目标是启用 Pose 作为实时 demo 的可视化增强能力，并确认它不参与正式跌倒判断。

已遵守的边界：

- 未修改 `FallStateMachine`。
- 未修改 `ResultPublisherService`。
- 未修改告警 POST 逻辑。
- 未训练模型。
- 未启用 Temporal，`ENABLE_TEMPORAL=false`。
- 未启用 0-5 VisualRiskMarker 实时主接入。
- 未运行本地 replay。
- 未调用真实 POST。
- 未点击前端“发送模拟告警”按钮。
- 未提交 git。

本次做过的配置级变更：

- 修改 `.env` 中 Pose 相关开关以启用实时可视化增强。
- 重启当前 `uvicorn app.main:app --host 0.0.0.0 --port 8000` 服务，让配置生效。

## 3. Pose 启用配置

当前 `.env` 关键配置：

| 配置项 | 当前值 | 说明 |
| --- | --- | --- |
| `ENABLE_POSE` | `true` | 已启用 Pose runtime |
| `POSE_PROVIDER` | `yolo11_legacy` | 使用 YOLO11 legacy pose provider |
| `YOLO11_POSE_MODEL_PATH` | `yolo11n-pose.pt` | 优先 Pose 模型路径 |
| `YOLO_POSE_MODEL_PATH` | `yolov8n-pose.pt` | 保留当前已有 YOLO pose 路径 |
| `ENABLE_TEMPORAL` | `false` | Temporal 未启用 |
| `MAIN_SYSTEM_REPORT_DRY_RUN` | `true` | 保持 dry-run，不真实 POST |

服务进程：

- Python：`C:\Users\YANG\.conda\envs\torchgpu\python.exe`
- 启动命令：`python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- 健康检查：`GET /healthz` 返回 `{"status":"ok"}`

## 4. `/status` 字段

接口：`GET http://127.0.0.1:8000/status?camera_id=camera_01`

关键返回：

| 字段 | 结果 |
| --- | --- |
| `service_status` | `running` |
| `cameras[0].connected` | `true` |
| `cameras[0].stream_state` | `connected` |
| `cameras[0].capture_fps` | `15.08` |
| `detection[0].loaded` | `true` |
| `detection[0].model_name` | `yolov8n.pt` |
| `detection[0].detection_fps` | `4.01` |
| `tracking.tracking_fps` | `4.01` |
| `pipeline.tracking_worker_fps` | `10.62` |
| `pipeline.result_publish_fps` | `9.12` |
| `pose.pose_enabled` | `true` |
| `pose.pose_provider` | `yolo11_legacy` |
| `pose.pose_pipeline_removed` | `false` |
| `pose.pose_fps` | `0.0` |
| `pose.pose_model_path` | `null` |
| `pose.last_error` | `null` |
| `latest_result.latest_objects_count` | `0` |
| `latest_result.pose_available` | `false` |
| `temporal.enabled` | `false` |
| `fall_event_reporter.enabled` | `true` |
| `fall_event_reporter.running` | `true` |
| `fall_event_reporter.last_post_status` | `null` |

说明：

- 当前代码的 Pose 服务为按需推理路径：只有检测/跟踪到 person 目标后才会触发 Pose estimator 加载和推理。
- 本次实时画面持续无人，`latest_objects_count=0`，因此 `pose_fps=0.0`、`pose_model_path=null` 属于未触发推理状态，不代表模型路径配置失败。
- 当前 `/status.pose` 未暴露独立的 `model_loaded` 布尔字段；可观测替代信号是 `pose_enabled=true`、`pose_provider=yolo11_legacy`、`pose_pipeline_removed=false`、`pose.last_error=null`，以及后续有人入镜后 `pose_model_path` / `pose_fps` / keypoints 更新。

## 5. `/alerting/status` 字段

接口：`GET http://127.0.0.1:8000/alerting/status`

关键返回：

| 字段 | 结果 |
| --- | --- |
| `endpoint.enabled` | `true` |
| `endpoint.dry_run` | `true` |
| `endpoint.base_url` | `http://192.168.8.254:8000/api/v1` |
| `endpoint.path` | `/video-bridge/fall-events` |
| `simulation.running` | `false` |
| `simulation.sent_count` | `0` |

结论：

- reporter 仍保持 dry-run。
- 未真实 POST。
- 未启动 alert simulation。

## 6. Demo 页面连接状态

页面：`http://127.0.0.1:8000/demo/?rawJson=1&poseValidation=20260623`

点击 `Connect` 后，前端面板显示：

| 面板项 | 结果 |
| --- | --- |
| WebRTC | `connected` |
| WebSocket | `connected` |
| Stream | `画面正常 (63ms) / 显示=single` |
| Has Stream | `yes` |
| ICE State | `connected` |
| Video Size | `640 x 360` |
| Video FPS | `30.0 (drop 30)` |
| WS FPS | `9.1` |
| Overlay FPS | `29.9` |
| Detect FPS | `4.0` |
| Track FPS | `10.6` |
| Pose FPS | `0.0` |
| Persons | `0` |
| Pose | `-` |
| Reporter | `ready` |

结论：

- WebRTC 实时画面连接正常。
- WebSocket 结果链路连接正常。
- 前端 overlay 渲染循环正常。
- 当前无人入镜，前端未收到可绘制 Pose payload。

## 7. 骨架 / 17 关键点验证情况

本项未完成闭环。

原因：

- 连续约 60 秒采样期间，`latest_objects_count=0`。
- demo 页面 `Persons=0`。
- 没有 person bbox / track id，Pose worker 没有可用目标。
- 因此未触发 `yolo11_legacy` Pose 推理，也未产生 `keypoint_count=17` 的实时证据。
- 页面骨架 overlay 代码已存在并运行在 `overlayMode=full` 默认模式下，但当前没有 pose keypoints 可绘制。

待补验条件：

1. 单人全身入镜，尽量居中，无遮挡，停留 20-30 秒。
2. `/status.latest_result.latest_objects_count >= 1`。
3. `/status.tracking.active_target_exists=true` 或 demo 出现 `Track ID`。
4. `/status.pose.pose_fps > 0`。
5. `/status.pose.pose_model_path` 指向 `yolo11n-pose.pt` 或实际 resolved path。
6. demo 最新 result 中 person object 的 `pose.keypoints.length == 17`。
7. demo 页面显示骨架或 Pose 状态非 `-`。

## 8. FPS 影响

当前无人入镜时的性能状态：

| 指标 | 结果 | 说明 |
| --- | ---: | --- |
| capture_fps | 约 `14.9-15.1` | RTSP 解码稳定 |
| detect_fps | 约 `4.0` | YOLO person / fall detector 主检测链路正常 |
| tracking_worker_fps | 约 `10.6` | ByteTrack worker 正常 |
| result_publish_fps | 约 `9.1` | WebSocket / publish 链路正常 |
| pose_fps | `0.0` | 无 person 目标，Pose 未触发 |
| demo Video FPS | 约 `30.0` | WebRTC 播放正常 |
| demo WS FPS | 约 `9.1` | WebSocket 接收正常 |
| demo Overlay FPS | 约 `29.9` | 前端 overlay 循环正常 |

风险提示：

- 当前尚未测得“有人入镜 + Pose 推理运行中”的 FPS，因此不能断言 `pose_fps` 对 CPU 推理无影响。
- 需要现场补验 `pose_fps`、`detect_fps`、`ws_fps` 是否在人员入镜后仍可接受。

## 9. 跌倒判断链路边界

本阶段没有改动跌倒判断生产代码。

当前演示口径保持：

- 跌倒确认主证明仍使用本地 replay 的既有证据。
- 实时摄像头用于展示在线能力和 Pose 可视化增强，不作为稳定触发 `fallen_confirmed` 的唯一证明。
- Pose 作为可视化与辅助状态输出，不作为正式 `FallStateMachine` 决策依据。
- Temporal 未启用。
- 0-5 VisualRiskMarker 未作为实时主接入。
- reporter 保持 dry-run，不真实 POST。

## 10. 是否适合明天展示

当前状态：有条件适合，需补一个现场入镜确认。

已通过：

- 服务可启动。
- RTSP 摄像头 connected。
- WebRTC connected。
- WS connected。
- Pose runtime 已启用：`pose_enabled=true`。
- Pose provider 正确：`pose_provider=yolo11_legacy`。
- Pose pipeline 未移除：`pose_pipeline_removed=false`。
- dry-run 保持 true。
- Temporal 保持 disabled。
- 前端 overlay 循环正常。

未通过 / 待补：

- 未确认 `keypoint_count=17`。
- 未确认实际骨架显示。
- 未确认有人入镜后的 `pose_fps` 和 FPS 影响。
- 未确认 `/status.pose.pose_model_path` 在实时人员目标触发后解析到 `yolo11n-pose.pt`。

明天建议：

1. 保持当前 Pose 配置：`ENABLE_POSE=true`、`POSE_PROVIDER=yolo11_legacy`、`YOLO11_POSE_MODEL_PATH=yolo11n-pose.pt`。
2. 保持 `MAIN_SYSTEM_REPORT_DRY_RUN=true`。
3. 保持 `ENABLE_TEMPORAL=false`。
4. 演示前先让单人全身入镜 20-30 秒，确认 `Persons >= 1`、`Track ID`、`Pose FPS > 0`、`keypoint_count=17` 和骨架可见。
5. 若 Pose FPS 明显拖慢或骨架不稳定，现场口径调整为：Pose 已启用为可视化增强，但跌倒确认主证明仍使用本地 replay。

## 11. 最终结论

Pose 可视化增强验证结果为 PARTIAL。

配置启用、服务启动、WebRTC/WS 连接、dry-run 安全边界均已通过；但由于实时画面无人，未能完成 `keypoint_count=17` 和骨架可视化的现场闭环验证。明天演示前必须补做单人全身入镜检查，确认 Pose payload 和前端骨架实际显示。
