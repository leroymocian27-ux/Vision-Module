# Fall Hint Runtime Stability Test Plan (2026-07-06)

## 1. Scope

本测试计划只针对当前已经接入系统的实时跌倒检测主链路，重点验证以下模块在最新 Fall Hint 主线模型接入后的稳定性：

- 摄像头采集与 `FrameBuffer` 最新帧链路
- YOLO person 检测
- YOLO Fall Hint 检测
- Tracking / Pose / Temporal / Fusion 串联
- `VisionResult` 发布与 `/ws/results`
- `/integration/results/{camera_id}/latest`
- 跌倒告警推送到主系统 `/video-bridge/fall-events`

本轮不做新训练，不替换其他模型，不调整主系统逻辑。

## 2. Current Deployment Snapshot

截至 2026-07-06，本机运行态验证到的核心配置如下：

- 项目根目录：`D:\Program\vision_service`
- 本地服务：`http://127.0.0.1:8000`
- Vision 对外地址：`http://192.168.8.249:8000`
- 主系统地址：`http://192.168.8.248:8000/api/v1`
- 当前摄像头 RTSP：`rtsp://admin:***@192.168.8.250:10554/tcp/av0_0`
- 当前 YOLO person：`yolov8n.pt`
- 当前 YOLO Fall Hint：
  `models/yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt`
- 当前 Pose 模型：
  `D:\Program\vision_service\yolo11n-pose.pt`
- 当前 Temporal 模型：
  `models/fall_lstm_v5.onnx`

注意：

- [`.env`](D:/Program/vision_service/.env) 当前已经切到 `candidate_v3_c_temporal_friendly`。
- 为了让服务正常启动，当前 `POSE_DEPLOYMENT_GUARD_ENABLED=false`。

## 3. Test Objectives

本轮测试目标不是“宣称系统绝对没问题”，而是把下面四件事说清楚：

1. 当前链路是否稳定运行，不掉线、不假启动。
2. 最新接入的 Fall Hint 模型是否真的被加载并参与实时检测。
3. 检测结果是否能持续流到 WebSocket、latest result、主系统告警接口。
4. 当前还缺哪一类实测，哪些风险没有被真正关闭。

## 4. Evidence Files Produced This Round

本轮已生成的证据文件：

- [fall_hint_runtime_stability_smoke_20260706.json](D:/Program/vision_service/evaluations/fall_hint_runtime_stability_smoke_20260706.json)
- [main_system_integration_smoke_compact_20260706.json](D:/Program/vision_service/evaluations/main_system_integration_smoke_compact_20260706.json)
- [ws_results_smoke_20260706.json](D:/Program/vision_service/evaluations/ws_results_smoke_20260706.json)
- [fall_hint_runtime_soak_30min_20260706.json](D:/Program/vision_service/evaluations/fall_hint_runtime_soak_30min_20260706.json)
- [main_system_connectivity_block_20260706.json](D:/Program/vision_service/evaluations/main_system_connectivity_block_20260706.json)

## 5. Test Matrix

| ID | Test Item | Method | Pass Criteria | Current Result |
| --- | --- | --- | --- | --- |
| T01 | 配置与模型加载 | 检查 `.env`、启动日志、`/status` | Fall Hint 路径正确，服务成功加载目标模型 | PASS |
| T02 | 服务健康检查 | `GET /healthz`、`GET /status?camera_id=camera_01` | 服务返回 200，camera connected=true | PASS |
| T03 | 60s 运行稳定性 | 连续轮询 `/status` 30 次 | 无请求错误，frame_seq 单调递增，camera connected 比例 100% | PASS |
| T04 | latest result 输出 | `GET /integration/results/camera_01/latest` | 接口返回 200，不再是 `VISION_RESULT_NOT_READY` | PASS |
| T05 | WebSocket 结果流 | `ws://127.0.0.1:8000/ws/results?camera_id=camera_01` | 能持续收到消息，frame_seq 更新 | PASS |
| T06 | 主系统告警联调 | 发送合成 confirmed fall 事件到主系统 | 主系统返回 `accepted=true` 且产生 alarm_id | PASS |
| T07 | 主系统快照联调 | 主系统访问 Vision 快照 URL | snapshot URL 可访问，返回图片字节 | PASS |
| T08 | 单元回归测试 | 运行核心 pytest 子集 | 关键检测/融合/告警测试通过 | PASS |
| T09 | 前端 overlay 贴合人工验收 | 人工查看 WebRTC + overlay | 框、骨架、状态文字随人移动，不明显漂移 | BLOCKED (需要人工目视) |
| T10 | 真实跌倒触发验收 | 真实视频/真人演示跌倒动作 | 链路出现 `fallen_confirmed` 并在主系统弹窗 | BLOCKED (需要人工动作 + 当前环境无法直连主系统) |
| T11 | 长时稳定性 soak test | 连续运行 30-60 分钟 | 无持续 reconnect、无 latest 卡死、无 reporter 异常 | FAIL |

## 6. Commands Used This Round

### 6.1 Core Regression Tests

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe -m pytest `
  tests\test_detection_service.py `
  tests\test_fall_feature_builder.py `
  tests\test_fall_fusion.py `
  tests\test_result_publisher_service.py -q

C:\Users\YANG\.conda\envs\torchgpu\python.exe -m pytest `
  tests\test_yolo_fall_detector.py `
  tests\test_fall_event_reporter_service.py `
  tests\test_fall_alert_polling_api.py -q
```

### 6.2 Runtime Health Checks

```powershell
Invoke-WebRequest http://127.0.0.1:8000/healthz
Invoke-WebRequest "http://127.0.0.1:8000/status?camera_id=camera_01"
Invoke-WebRequest "http://127.0.0.1:8000/integration/results/camera_01/latest"
```

### 6.3 WebSocket Smoke

```text
ws://127.0.0.1:8000/ws/results?camera_id=camera_01
```

### 6.4 Main System Integration Smoke

向主系统接口发送一条合成 `confirmed_fall` 事件，验证：

- 主系统健康可达
- 主系统能拉取 Vision 提供的 snapshot
- 主系统返回 `accepted=true`
- 主系统生成 `alarm_id`

## 7. Results From This Round

### 7.1 Runtime Stability Summary

来自 [fall_hint_runtime_stability_smoke_20260706.json](D:/Program/vision_service/evaluations/fall_hint_runtime_stability_smoke_20260706.json)：

- 采样时长：约 60 秒
- 采样次数：30
- 请求错误数：0
- `camera_connected_ratio = 1.0`
- `frame_seq_monotonic = true`
- `frame_seq_delta_min = 17`
- `frame_seq_delta_max = 23`
- `capture_fps_mean = 10.7397`
- `detection_fps_mean = 4.1013`
- `fall_hint_latency_ms_p95 = 25.34`
- `publish_lag_ms_p95 = 234.0`

结论：

- 摄像头采集、检测、发布链路在这 60 秒内是稳定活着的。
- 当前 Fall Hint 推理延迟不高，至少没有出现因为新模型接入导致的明显推理爆炸。

### 7.2 Integration Latest Result

`/integration/results/camera_01/latest` 已经可以返回结构化结果，不再是之前那种 `404 VISION_RESULT_NOT_READY`。

这说明：

- `ResultPublisherService`
- `latest result store`
- integration API

这三层现在是通的。

### 7.3 Main System Alert Smoke

来自 [main_system_integration_smoke_compact_20260706.json](D:/Program/vision_service/evaluations/main_system_integration_smoke_compact_20260706.json)：

- 主系统 `healthz`：PASS
- Vision snapshot URL 可访问：PASS
- `POST /api/v1/video-bridge/fall-events`：PASS
- 返回 `alarm_id`：PASS
- 告警在主系统列表可见：PASS

结论：

当前至少可以确认一件很重要的事：

**只要 Vision 侧真正产出 `confirmed_fall` 事件，主系统接口链路现在是能接收并建告警记录的。**

### 7.4 Code Regression

本轮执行结果：

- `31 passed`
- `22 passed`

合计：`53 passed`

说明这次接入没有把核心检测/融合/告警相关的单元测试打坏。

### 7.5 30-Minute Soak Test

来自 [fall_hint_runtime_soak_30min_20260706.json](D:/Program/vision_service/evaluations/fall_hint_runtime_soak_30min_20260706.json)：

- 持续时长：`1800.02s`
- 采样数：`357`
- `status_failures = 0`
- `integration_failures = 0`
- `camera_disconnect_samples = 0`
- `stream_not_connected_samples = 0`
- `frame_seq_regressions = 0`
- `max_reconnect_count = 0`
- `latest_fall_states_seen = ["fallen_candidate", "fallen_confirmed", "normal", "suppressed"]`

关键指标：

- `capture_fps mean = 10.8183`
- `detection_fps mean = 3.1883`
- `fall_hint_latency_ms p95 = 71.19`
- `publish_lag_ms p95 = 297.0`
- `pose_fps mean = 0.39`

但同时出现了一个决定性的失败点：

- `reporter_error_samples = 357`
- `reporter_http2_seen = false`

也就是说，这 30 分钟里 Vision 主链路本身稳定，但 `FallEventReporterService` 持续异常，T11 按原始门槛必须判为 `FAIL`，不能算通过。

## 8. Risks Found This Round

### R1. Pose 实时频率偏低

60 秒 smoke 里：

- `pose_fps_mean = 0.322`

这明显低于理想实时值。即使当前链路能跑，骨架贴合和连续性仍然存在明显风险。

这会直接影响：

- 骨架是否稳定贴身
- Temporal 特征是否持续可用
- ADL / fall 边界动作的判别质量

### R2. 当前没有完成“真实跌倒触发”闭环实测

本轮没有在 live 场景中观测到：

- `fallen_confirmed`
- 主系统真实弹窗时刻
- 从检测到告警的真实延迟

所以现在只能说：

- **主系统接口能收 synthetic confirmed fall**
- **但真实跌倒触发闭环还需要人工演示或指定视频复测**

### R3. WebSocket 传输通过，但本轮窗口里没有拿到有效 person object

WebSocket 12 条消息已收到，但该窗口中 `person_message_count = 0`。

这更像是采样时段内画面里没有稳定目标，不等于 WebSocket 坏了；但也说明这轮 smoke **还不足以证明 overlay 在真实人物运动下完全贴合**。

### R4. 当前受限环境无法直接访问主系统地址

来自 [main_system_connectivity_block_20260706.json](D:/Program/vision_service/evaluations/main_system_connectivity_block_20260706.json)：

- `http://192.168.8.248:8000/healthz`
- `http://192.168.8.248:8000/api/v1/alarms?limit=1`

当前都会返回 `WinError 10013`。

这说明本轮后半段测试所在的执行环境，无法继续直接访问主系统 LAN 地址。它会影响两件事：

- 无法在当前受限环境里完成 T10 的主系统弹窗终验
- soak test 中 reporter 的持续失败，至少有一部分是环境网络访问被拦截造成的

因此这一项要和“代码逻辑故障”分开看，不能混为同一个结论。

## 9. Acceptance Thresholds For Next Round

后续每次接入检测相关改动，建议至少满足下面的最低门槛：

- `healthz` 连续 3 次 200
- `/status` 连续 60 秒无 error
- `camera_connected_ratio = 1.0`
- `frame_seq_monotonic = true`
- `detection_fps_mean >= 3.5`
- `fall_hint_latency_ms_p95 <= 40`
- `publish_lag_ms_p95 <= 300`
- `/integration/results/camera_01/latest` 返回 200
- 合成告警推送主系统成功
- 关键 pytest 子集全部通过

如果要宣称“检测稳定且可演示”，还必须额外满足：

- 人工看到 bbox/pose/overlay 随人运动稳定贴合
- 至少完成 1 次真实跌倒演示触发 `fallen_confirmed`
- 主系统真实弹出跌倒告警

## 10. Recommended Next Test Order

下一步建议严格按这个顺序继续：

1. 前端人工验收 overlay 贴合
2. 真实跌倒动作闭环实测
3. 长时 30-60 分钟 soak test
4. 如果骨架仍漂移，优先回到 pose 模型与 pose worker 节流策略，不要先怪 Fall Hint
5. 在不受限网络环境下重跑主系统联调与真实跌倒弹窗终验

## 11. Current Verdict

本轮结论分三层：

1. **系统已恢复运行，最新 Fall Hint 主线模型已经真实接入。**
2. **采集、检测、latest result 这三段在 30 分钟内保持稳定，没有出现掉流、卡死或重连。**
3. **但 T11 没过，因为 reporter 持续异常；同时真实跌倒闭环和 overlay 贴合也还没有完成最终人工验收。**

换句话说：

当前系统已经不是“起不来”或者“接口不通”的状态了，但还没到可以不带保留地宣布“现场效果稳定可靠”的程度。

