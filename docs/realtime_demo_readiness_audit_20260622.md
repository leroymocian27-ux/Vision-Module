# VisionRealtimeDemoReadinessAudit - 2026-06-22

审计范围：只读检查当前 `D:\Program\vision_service` 实时摄像头视频检测最小演示链路。未修改生产代码，未训练模型，未关闭 dry-run，未真实 POST 主系统。

## 核心结论

```text
【VisionRealtimeDemoReadinessAudit Result】

overall_status:
PARTIAL

recommended_demo_mode:
本地视频主演示 + 摄像头加分
```

判断依据：

- 当前本机服务在线，`GET /status?camera_id=camera_01` 返回 `service_status=running`。
- 当前真实 RTSP 摄像头已接入并持续出帧：`stream_state=connected`，`connected=true`，`frame_age_ms≈31ms`，`capture_fps≈14.93`。
- 当前画面检测结果为空：`latest_raw_person_count=0`，`latest_objects_count=0`，因此不能证明现场摄像头动作一定能稳定触发跌倒。
- 本地 replay 已有稳定证据：`docs/stable_demo_runbook_20260622.md` 记录本地跌倒视频 replay 可产生 `fallen_confirmed`、`risk_level=critical`、`dry_run_skipped`。
- `MAIN_SYSTEM_REPORT_DRY_RUN=true`，当前 `/alerting/status` 显示 `dry_run=true`，真实 POST 风险低。

## 链路分段状态

```text
RTSP 摄像头输入
→ 视频解码 / 读取帧
→ 实时画面显示
→ 人体检测
→ 目标跟踪
→ 跌倒疑似分数
→ 视觉风险分级
→ 误报降级
→ 前端/调试画面展示
→ WebSocket / Polling / 结果输出
→ dry-run 告警或事件记录
```

| 链路段 | 状态 | 证据 | 明天依赖建议 |
|---|---|---|---|
| RTSP 摄像头输入 | READY | `.env` 有 `DEFAULT_RTSP_URL`；当前 `/status` 已连接真实 RTSP | 可展示实时画面 |
| 视频解码 / 读取帧 | READY | `FrameBuffer`、`CaptureWorker`、`frame_seq` 持续增长，`capture_fps≈14.93` | 可依赖，但保留 fallback |
| 实时画面显示 | READY | `/demo/` 返回 200；前端使用 WebRTC 视频 | 可展示 |
| 人体检测 | READY | `YoloPersonDetector` 已加载 `yolov8n.pt`，当前检测 worker running | 需要现场人进入画面 |
| 目标跟踪 | PARTIAL | ByteTrack 已接入；当前无人体，无法实时观察稳定 track | 单人全身无遮挡可演示 |
| 跌倒疑似分数 | PARTIAL | runtime 有 `fall_decision`、`alarm_preview`、`fall_score` 输出路径；当前 live 画面无人体 | 不建议只依赖实时摄像头触发 |
| 视觉风险分级 | PARTIAL | runtime 有 `risk_level=low/medium/high/critical`；0-5 VisualRiskMarker 仍主要是离线审计 | 可讲解，不建议说已完整实时接入 |
| 误报降级 | PARTIAL | runtime 有 `suppressed_reason`、`rejected_reason`、field rule debug；离线 runtime-observable 风险分级为 PARTIAL | 可展示部分字段，不建议作为稳定卖点 |
| 前端/调试画面 | PARTIAL | 前端显示 bbox、track、fall state、risk、FPS；不直接显示降级原因 | 明天可用，缺“降级原因”直观展示 |
| WebSocket / Polling / 输出 | READY | `WS /ws/results`、`GET /integration/results/{camera_id}/latest`、`GET /status` 均存在，latest 当前返回 200 | 可依赖 |
| dry-run 告警/事件 | READY | `/alerting/status` 显示 `dry_run=true`；`fall_event_reporter.last_post_status=dry_run_skipped` | 可安全展示 dry-run |

## 摄像头输入状态

```text
camera_input_status:
READY
evidence:
- 当前配置文件：D:\Program\vision_service\.env
- 当前默认 camera_id：camera_01
- 当前源：rtsp://admin:***@192.168.8.252:10554/tcp/av0_1
- 当前 /status：running=true, connected=true, stream_state=connected
- 当前 frame_seq：462603
- 当前 frame_age_ms：约 31ms
- 当前 capture_fps：约 14.93
- reconnect_count：6
- read_timeout_count：140
```

说明：

- 摄像头当前能连接，也能持续读到帧。
- 有 `frame_age_ms`、`capture_fps`、`stream_state`、`reconnect_count`、`read_latency_ms`、`stale_count` 等运行状态。
- 有重连机制：OpenCV capture worker 对 `open_failed`、`read_failed`、`slow_read`、`stale_frame` 会进入 reconnect；另有 subprocess capture worker，但当前运行态是 `capture_backend=opencv`。
- 支持本地视频 fallback：`is_local_file_source()` 会把本地路径交给 `CaptureWorker`，本地 replay 会按视频 FPS 节流。

风险：

- 当前运行态 `read_latency_max_ms=176500.0`、`read_timeout_count=140`，说明历史上出现过很慢的 read。当前已恢复，但现场演示仍需准备本地 fallback。

## 实时视频显示状态

```text
video_display_status:
READY
evidence:
- /demo/ HTTP 200
- 前端入口：frontend_demo/index.html
- 视频展示：WebRTC，接口 POST /webrtc/offer
- 结果叠加：WebSocket + Canvas overlay
- 辅助 latest frame：GET /stream/latest-frame.jpg
```

当前推荐展示方式：

1. 主展示：`http://127.0.0.1:8000/demo/` 的 WebRTC 实时画面。
2. 结果观察：页面指标面板 + `/integration/results/camera_01/latest`。
3. 兜底画面：`/stream/latest-frame.jpg` 或本地 replay。

稳定性判断：

- WebRTC + WebSocket 是当前项目正式 demo 页面使用方式。
- 刷新页面会重新建立 WebRTC/WS 连接；后端是单一 `FrameBuffer`，不是每个前端重复拉 RTSP。
- overlay 使用 `requestVideoFrameCallback` 或 100ms fallback 循环，结果通常能随视频刷新，但严格像素级同步未在本次审计重新验证。

## 人体检测状态

```text
person_detection_status:
READY
detector_status:
READY
evidence:
- app/detection/object_detector.py 使用 Ultralytics YOLO，classes=[0] 检测 person
- 当前 .env：YOLO_MODEL_PATH=yolov8n.pt
- 权重存在：D:\Program\vision_service\yolov8n.pt
- 当前 /status：detection.running=true, detection.enabled=true, detection.loaded=true
- 当前 detection_fps≈3.22, inference_latency_ms≈96.82
```

限制：

- 当前摄像头画面没有人，`latest_raw_person_count=0`，所以本次审计没有证明现场人体检测效果。
- 明天请保证单人全身、无遮挡、光照稳定、距离适中。

## 目标跟踪状态

```text
tracking_status:
PARTIAL
evidence:
- app/tracking/bytetrack_tracker.py 已接入 Ultralytics BYTETracker
- app/services/tracking_worker_service.py 从检测结果生成 tracking snapshot
- 当前 /status：tracker_running=true, tracking_worker_fps≈10.61
- 当前无人体：tracked_objects_count=0，latest_result.track_id=null
```

明天可依赖范围：

- 单人、全身、无遮挡、画面中停留时，基本 track 可演示。
- 多人、遮挡、边缘入镜、快速出入画面不作为明天硬演示项。

## 跌倒检测状态

```text
fall_detection_status:
PARTIAL
evidence:
- app/detection/yolo_fall_detector.py 使用独立 YOLO fall model
- 当前 .env：FALL_DETECTOR_ENABLED=true
- 权重存在：models/yolo_fall_detector_phase9_selected.pt
- ResultPublisherService 会合并 fall detector、tracking、field rule，输出 fall_decision / alarm_preview
- 当前 latest result 无人，fall_score=null
- 历史 replay 证据显示可输出 fallen_confirmed / risk_level=critical
```

明天演示判断：

- 实时摄像头：可尝试触发疑似/候选/确认，但不建议把“实时确认跌倒必定稳定”作为承诺。
- 本地 replay：建议作为主演示，已有稳定确认跌倒证据。
- 如果确认跌倒现场不稳定，建议只演示到 `fallen_candidate` / `high`，并用本地视频展示 `fallen_confirmed`。

## 视觉风险分级状态

```text
visual_risk_mark_status:
PARTIAL
evidence:
- runtime 已有 risk_level 字段：low / medium / high / critical / cooldown
- 前端显示 riskLevel
- integration latest 映射 risk_level / fall_score
- 独立 0-5 VisualRiskMarker 当前主要在 scripts/fast_pose_fall 与 evaluations/fast_pose_fall 中
- evaluations/fast_pose_fall/runtime_observable_risk_mark_eval_20260622.md 显示 ready_for_visual_risk_mark_runtime_shadow=PARTIAL
```

明确区分：

- 已实时接入：runtime fall risk，即 `fall_decision.risk_level` / `alarm_preview.risk_level`。
- 只做过离线验证：0-5 VisualRiskMarker / RuntimeObservableVisualRiskMark。
- 尚未完整接入实时摄像头链路：前一阶段设计的 `MARK_0` 到 `MARK_5` 视觉风险分级器。
- 明天建议说法：当前实时演示显示的是“跌倒候选风险等级”，视觉风险分级离线版已验证为可讲解材料，尚不作为实时主裁判。

## 误报降级状态

```text
false_positive_downgrade_status:
PARTIAL
evidence:
- runtime 中存在 detector_only_guard、upright_guard、field_rule_debug、suppressed_reason、rejected_reason
- 离线 runtime-observable 风险分级审计显示 hard_negative_false_positive_rate=0.0833，但 recall 较低
- 当前前端未直接显示 suppressed_reason / rejected_reason
```

场景覆盖判断：

| 场景 | 当前状态 |
|---|---|
| 慢走 | 离线 runtime-observable 有验证；实时显示未独立验收 |
| 弯腰 | 规划/规则侧有相关姿态语义；当前 no-pose runtime 不稳定依赖 |
| 蹲下 | 离线/规划可讲，实时未验证 |
| 坐下 | field rule 有 possible sitting guard；实时未做本次动作验收 |
| 躺下但非跌倒 | YOLO lying 是弱 hint，runtime 有 guard；实时未做本次动作验收 |
| 恢复站立 | temporal disabled，实时恢复过程判断不建议强调 |
| 无人误检 | 当前无人画面 latest_objects_count=0，表现正常 |

明天最稳策略：

- 实时摄像头只演示正常站立、慢走、弯腰/蹲下“不会马上真实 POST”。
- 跌倒确认用本地 replay。
- 不把“误报降级已经完整覆盖所有动作”作为演示承诺。

## 前端展示字段

```text
frontend_overlay_status:
PARTIAL
evidence:
- 已显示：人体框、Target/Track、fallState、riskLevel、fallProbability、fallCountdown、temporalWindow、reporterStatus、detectionFps、trackingFps、poseFps、wsFps、overlayAge、streamState、WebRTC/WS 状态
- 缺失：显式 downgraded 字段、降级原因、suppressed_reason/rejected_reason 的醒目展示
```

明天最应该补的字段：

1. 降级/抑制原因：`alarm_preview.suppressed_reason` 或 `fall_decision.rejected_reason`。
2. 当前模式：`dry-run` / `no real POST`。
3. 当前输入源：RTSP / local replay。

本阶段按要求未修改前端代码。

## WebSocket / Polling / 结果输出

```text
result_output_status:
READY
evidence:
- WebSocket：WS /ws/results?camera_id=camera_01
- Polling latest：GET /integration/results/camera_01/latest
- Polling alert：GET /integration/fall-alerts/camera_01/poll
- Status：GET /status
- 当前 latest endpoint 返回 200，包含 frame_seq、detector、source_fps、analysis_fps、objects、fall_score、risk_level 等字段
```

当前 latest 观察：

- `frame_width=640`
- `frame_height=360`
- `source_fps≈14.93`
- `analysis_fps≈9.09`
- `objects=[]`
- `fall_detected=false`
- `fall_score=null`

## dry-run 告警与主系统桥接

```text
dry_run_safety_status:
MAIN_SYSTEM_REPORT_DRY_RUN=true

real_post_risk:
LOW
```

证据：

- `.env` 当前 `MAIN_SYSTEM_REPORT_DRY_RUN=true`。
- `/alerting/status` 当前 `endpoint.dry_run=true`。
- `/status` 当前 `fall_event_reporter.last_post_status=dry_run_skipped`。
- `FallEventReporterService._post_payload()` 在 `dry_run` 时只记录 `dry_run_skipped`，不会执行 `requests.post()`。

注意：

- `MAIN_SYSTEM_ALERT_ENABLED=true`，但由于 dry-run 为 true，确认跌倒只会生成本地 dry-run 事件。
- 前端有手动 simulation 按钮和 `/alerting/simulation/send-once`，明天不要点击或调用。

## 本地视频 fallback

```text
fallback_status:
READY
evidence:
- 本地文件源由 app/camera/source_models.py 识别
- CaptureWorker 支持本地视频 EOF 和 FPS throttle
- 已验证 replay 视频存在：
  D:\Program\vision_service\logs\acceptance\cropped_recording_2026-06-20T07-32-20-181Z\run2\cropped_recording_run2.mp4
- docs/stable_demo_runbook_20260622.md 记录该视频可产生 fallen_confirmed
```

备用视频资源：

- 稳定跌倒 replay：`logs\acceptance\cropped_recording_2026-06-20T07-32-20-181Z\run2\cropped_recording_run2.mp4`
- 公共/本地数据集：`datasets\gmdcsa24\videos\*.mp4`、`datasets\ur_fall\videos\*.mp4`
- 基础测试 fixture：`tests\fixtures\*.mp4`

## 已实时接入 / 离线验证 / 规划中 / 不建议展示

| 分类 | 能力 |
|---|---|
| 已实时接入 | RTSP 输入、FrameBuffer、WebRTC 显示、YOLO person、YOLO fall detector、ByteTrack、WebSocket results、latest polling、dry-run reporter |
| 只做过离线验证 | RuntimeObservable VisualRiskMark、困难负样本风险分级、0-5 mark 方案 |
| 半成品 / 部分接入 | runtime risk_level、field fall candidate、suppressed/rejected reason、误报降级 |
| 规划中或当前禁用 | pose_use_for_fall、正式多模态辅助、生产 FallStateMachine 改造、正式 POST |
| 明天不建议展示 | 人脸识别、多摄像头平台、真实主系统告警、pose 骨架作为跌倒依据、多模态裁判、多人遮挡跌倒 |

## 明天演示阻塞项

```text
tomorrow_demo_blockers:
1. 实时摄像头当前虽然出帧，但当前画面无人，未证明现场动作可稳定触发跌倒。
2. 0-5 视觉风险分级未完整接入实时摄像头 runtime，只能作为离线讲解材料。
3. 前端没有醒目展示 suppressed_reason / rejected_reason，误报降级讲解需要配合接口或日志。
```

## 今晚必须修复 / 检查

```text
must_fix_tonight:
1. 现场走一遍摄像头单人全身测试，确认 person bbox 和 track_id 能显示。
2. 走一遍本地 replay，确认 fallen_confirmed、critical、dry_run_skipped 仍能出现。
3. 演示前再次确认 /alerting/status 的 dry_run=true。
```

## 今晚可选优化

```text
nice_to_have_tonight:
1. 前端显示 suppressed_reason / rejected_reason。
2. 在 demo 页面明显显示 dry-run / no real POST。
3. 准备一个慢走或坐下的本地负样本视频，作为误报降级讲解素材。
```

## 今晚不要碰

```text
do_not_touch_tonight:
1. 不改 FallStateMachine、ResultPublisherService、main system bridge。
2. 不打开真实 POST，不改 MAIN_SYSTEM_REPORT_DRY_RUN，不改 .env。
3. 不启用 pose_use_for_fall，不训练模型，不接入新多模态模型。
```

## 推荐演示脚本

```text
recommended_demo_script:
1. 打开 /status 和 /alerting/status，先展示摄像头 connected 与 dry_run=true。
2. 打开 /demo/，展示 RTSP 实时画面、WebRTC/WS 状态、FPS、人体框/track_id。
3. 做正常站立、慢走、弯腰/蹲下，强调当前不会真实 POST。
4. 切换本地 replay，展示稳定跌倒检测链路。
5. 展示 /integration/results/camera_01/latest 或前端字段中的 fall_state、risk_level、fall_score。
6. 展示 reporter dry_run_skipped，说明只生成 dry-run 事件记录。
7. 回到摄像头实时画面，说明 RTSP 实时接入已具备，但明天不承诺复杂生产场景。
```

## 推荐演示动作

```text
recommended_demo_actions:
1. 正常站立
2. 慢走
3. 弯腰
4. 蹲下/坐下
5. 模拟跌倒
6. 倒地保持 2～3 秒
7. 恢复站立
```

建议：

- 第 5-6 步优先用本地 replay 做主证明。
- 真实摄像头模拟跌倒只作为加分项，避免现场确认不稳定。

## 推荐演示话术

```text
recommended_wording_for_demo:
当前演示不是完整智慧养老系统，也不做真实告警推送。我们展示的是实时视频检测最小链路：摄像头接入、解码取帧、人体检测、目标跟踪、跌倒候选识别、风险状态输出、前端可视化和 dry-run 事件记录。当前摄像头链路已经在线，正式告警 POST 被 dry-run 保护关闭。本地 replay 可以稳定展示确认跌倒；实时摄像头用于展示在线检测能力，复杂误报降级和 0-5 视觉风险分级仍处于离线/半接入阶段。
```

## Git 状态

审计开始前已有未跟踪文件：

```text
?? docs/local_dataset_asset_inventory_20260622.md
?? docs/vscode_startup_guide_20260622.md
?? evaluations/fast_pose_fall/
?? scripts/fast_pose_fall/
?? tests/test_visual_risk_mark_runtime_observable.py
```

本报告新增后预期会增加：

```text
?? docs/realtime_demo_readiness_audit_20260622.md
?? docs/realtime_demo_gap_list_20260622.md
?? docs/realtime_demo_runbook_20260622.md
```

