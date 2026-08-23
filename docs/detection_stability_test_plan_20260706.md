# 检测稳定性详细测试计划

- 日期：2026-07-06
- 范围：视觉检测主链路、人体骨架链路、跟踪、结果发布、时序/LSTM、跌倒融合、生产启动门禁。
- 当前结论：本机代码级稳定性测试已通过；生产级稳定性尚未完成，因为当前环境缺 CUDA 生产证据，真实 FastAPI `/status` 也未连通。

## 1. 测试目标

本轮测试不是只看“能不能跑起来”，而是确认系统在连续检测、姿态补充、跟踪绑定、发布、时序判断、告警输出这些环节里是否稳定。

核心目标：

1. 检测服务稳定输出 `person/fall` 等目标，不因为空帧、低置信度、异常模型返回而崩。
2. 跟踪服务能稳定生成 `track_id`，并在目标短暂缺失时合理保持/预测，不把对象乱甩。
3. 姿态服务能正确区分 `high_confidence`、`valid`、`low_quality`、`pose_track_mismatch`、`pose_absent`。
4. 姿态 worker 不把 stale detection、tracking desync、busy skip 伪装成有效骨架。
5. result publisher 只发布新鲜且 frame-aligned 的姿态，不把过期骨架塞给下游。
6. 时序/LSTM 和融合逻辑能正确消费 `pose_available`、`pose_quality_level`，但不能把 low quality 或错绑骨架当硬证据。
7. 生产启动必须经过 evidence package、deployment guard、promotion gate，不能绕过门禁直接上线。

## 2. 当前已执行测试

本机已执行以下稳定性回归测试：

```powershell
python -m pytest tests\test_detection_service.py tests\test_tracking_worker_service.py tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_result_publisher_service.py tests\test_temporal_service.py tests\test_fall_feature_builder.py tests\test_fall_fusion.py tests\test_realtime_result_store.py tests\test_target_feature_extractor.py tests\test_end_to_end_pipeline.py tests\test_fall_alert_polling_api.py tests\test_app_pose_deployment_guard.py tests\test_check_pose_promotion_gate.py tests\test_check_pose_launch_safety.py tests\test_check_pose_deployment_guard.py tests\test_start_current_camera_pose_defaults.py tests\test_check_pose_evidence_package.py tests\test_check_pose_production_preflight.py tests\test_run_pose_optimization_pipeline.py tests\test_check_pose_optimization_readiness.py tests\test_check_pose_temporal_sequences.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_replay_pose_runtime_profiles.py -q
```

结果：

```text
167 passed, 4 warnings
```

警告来自 Pillow/torchvision 的弃用提示，不是当前检测链路失败。

## 3. 当前不能宣称生产稳定的原因

当前 production pipeline 仍然失败在：

```text
production_preflight
cuda_unavailable
live_status_unreachable
```

因此以下结论不能说：

- 不能说人体骨架生产稳定。
- 不能说 CUDA provider 性能已达标。
- 不能说真实摄像头下 `pose_valid_rate >= 0.70`。
- 不能说 pose-aware LSTM 已优于 bbox+motion baseline。
- 不能说当前系统已经可生产推广。

现在只能说：代码级回归、门禁、证据链、本机 mock/e2e 链路通过；生产稳定性还需要真实环境证明。

## 4. 模块测试矩阵

| 模块 | 测试重点 | 已有测试 | 当前状态 |
| --- | --- | --- | --- |
| DetectionService | 空帧、模型异常、检测结果写入 store | `tests\test_detection_service.py` | 已通过 |
| RealtimeResultStore | detection/tracking/pose/result 快照缓存与读取 | `tests\test_realtime_result_store.py` | 已通过 |
| TrackingWorkerService | track 保持、预测、目标丢失、稳定 track 字段 | `tests\test_tracking_worker_service.py` | 已通过 |
| PoseService | provider 选择、骨架质量分级、错绑标记 | `tests\test_pose_service.py` | 已通过 |
| PoseWorkerService | stale frame、tracking desync、busy skip、frame age | `tests\test_pose_worker_service.py` | 已通过 |
| ResultPublisherService | TTL、frame alignment、pose 发布、fall decision | `tests\test_result_publisher_service.py` | 已通过 |
| TemporalService | pose 特征入模、状态机输出、窗口稳定性 | `tests\test_temporal_service.py` | 已通过 |
| FallFusionService | bbox/motion/pose 融合、抑制误报 | `tests\test_fall_fusion.py` | 已通过 |
| End-to-End Mock | mock camera 到告警完整链路 | `tests\test_end_to_end_pipeline.py` | 已通过 |
| Fall Alert API | 告警轮询、弹窗、状态输出 | `tests\test_fall_alert_polling_api.py` | 已通过 |
| Pose Deployment Guard | 生产启动门禁 | `tests\test_check_pose_deployment_guard.py`、`tests\test_app_pose_deployment_guard.py` | 已通过 |
| Pose Evidence Package | 证据包同轮产物、readiness 一致性 | `tests\test_check_pose_evidence_package.py` | 已通过 |
| Pose Runtime Replay | replay 下 TTL/frame age/profile 检查 | `tests\test_replay_pose_runtime_profiles.py` | 已通过 |

## 5. 分层测试计划

### A. 静态配置与启动门禁测试

目的：防止系统用错模型、错 provider、脆弱 TTL，或直接绕过生产门禁。

执行命令：

```powershell
python -m pytest tests\test_app_pose_deployment_guard.py tests\test_check_pose_launch_safety.py tests\test_check_pose_deployment_guard.py tests\test_start_current_camera_pose_defaults.py -q
```

通过标准：

- `POSE_PROVIDER=yolo11_legacy`
- `YOLO11_POSE_MODEL_PATH=yolo11n-pose.pt`
- `POSE_RESULT_TTL_MS >= 800`
- `POSE_MAX_FRAME_AGE_MS >= 800`
- `POSE_MAX_TRACKING_FRAME_DELTA <= 2`
- `POSE_INFERENCE_LOCK_WAIT_MS >= 160`
- FastAPI `app.main` lifespan 已执行 deployment guard
- `start_current_camera.py` 已执行 deployment guard
- 直接关闭 `POSE_DEPLOYMENT_GUARD_ENABLED=false` 的启动脚本必须被 launch safety 拦截

失败优先排查：

1. `.env` / `.env.example`
2. `app\core\config.py`
3. `app\main.py`
4. `scripts\start_current_camera.py`
5. `scripts\check_pose_launch_safety.py`

### B. 检测与跟踪单元稳定性测试

目的：确认 detection 和 tracking 是稳定骨架链路的基础，不让下游拿到乱跳目标。

执行命令：

```powershell
python -m pytest tests\test_detection_service.py tests\test_tracking_worker_service.py tests\test_realtime_result_store.py -q
```

通过标准：

- detection 写入 `RealtimeResultStore` 正常
- 空对象/异常对象不会导致服务崩溃
- tracking 能输出稳定 `track_id`
- tracking stale/held/predicted 字段符合预期
- store 中 detection、tracking、pose、result 快照不会互相污染

失败优先排查：

1. `app\services\detection_service.py`
2. `app\detection\realtime_result_store.py`
3. `app\services\tracking_worker_service.py`
4. `app\tracking\tracker.py`

### C. 姿态链路稳定性测试

目的：确认骨架不是“有字段就算有骨架”，而是按质量、时效、绑定关系进入系统。

执行命令：

```powershell
python -m pytest tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_result_publisher_service.py tests\test_check_pose_temporal_sequences.py tests\test_replay_pose_runtime_profiles.py -q
```

通过标准：

- `pose_absent` 不能伪装成有效骨架
- `low_quality` 不能直接支持告警
- `pose_track_mismatch` 必须作为风险标记
- stale detection 必须被识别为 stale，不进入有效骨架
- tracking frame delta 超阈值必须被识别为 desync
- publisher 只接受新鲜且 frame-aligned 的 pose
- temporal rows 中可用骨架必须带 `pose_runtime.pose_provider` 和 `pose_runtime.pose_model_path`

失败优先排查：

1. `app\services\pose_service.py`
2. `app\services\pose_worker_service.py`
3. `app\services\result_publisher_service.py`
4. `app\pose\placeholders.py`
5. `app\temporal\target_feature_extractor.py`

### D. 时序与融合稳定性测试

目的：确认姿态进入 LSTM/融合逻辑后，不会因为无效骨架导致误报或假提升。

执行命令：

```powershell
python -m pytest tests\test_temporal_service.py tests\test_fall_feature_builder.py tests\test_fall_fusion.py tests\test_target_feature_extractor.py tests\test_build_pose_lstm_comparison.py tests\test_evaluate_fall_lstm_metrics.py -q
```

通过标准：

- `pose_available=false` 时不能被当作有效骨架
- `pose_quality_level` 进入 feature builder
- bbox+motion+pose LSTM 必须和 baseline、zero-pose ablation 对比
- pose LSTM 没有优于 zero-pose 时必须判失败
- LSTM manifest、metrics、train_config hash 必须一致

失败优先排查：

1. `app\fall\feature_builder.py`
2. `app\fall\fusion.py`
3. `app\services\temporal_service.py`
4. `scripts\build_pose_lstm_comparison.py`
5. `scripts\evaluate_fall_lstm_metrics.py`

### E. Mock E2E 稳定性测试

目的：验证从 mock camera 到检测、跟踪、发布、告警 API 的完整链路不崩。

执行命令：

```powershell
python -m pytest tests\test_end_to_end_pipeline.py tests\test_fall_alert_polling_api.py -q
```

通过标准：

- mock camera 能启动
- latest result 有对象输出
- track_id 可用
- fall decision 可进入 `fallen_confirmed` 或预期状态
- status API 可返回 camera、latest result、pose、tracking、fall state
- fall event reporter 能构造告警 payload

限制：

这不是生产稳定性证明。mock camera 不能代表真实 RTSP 抖动、CUDA 推理延迟、真实人体遮挡、多目标错绑。

### F. 生产 CUDA/真实服务稳定性测试

目的：证明系统在真实部署环境中稳定，不再用本机 mock/replay 充数。

前置条件：

- CUDA 可用
- FastAPI 服务可启动
- `/api/v1/status` 可访问
- 使用真实摄像头或生产代表性视频流
- `POSE_PROVIDER=yolo11_legacy`
- `YOLO11_POSE_MODEL_PATH=yolo11n-pose.pt`
- deployment guard 不允许绕过

执行命令：

```powershell
python scripts\check_pose_production_preflight.py --base-url http://127.0.0.1:8000/api/v1 --camera-id camera_01 --device cuda:0 --duration-seconds 120 --labels data\phase7_labels\phase7_video_labels.jsonl --temporal-output-dir data\temporal_sequences_pose_v1 --lstm-eval-split test --output evaluations\pose_production_preflight_20260705.json
```

然后执行：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode production --device cuda:0 --duration-seconds 120 --lstm-eval-split test --summary evaluations\pose_optimization_pipeline_20260705.json
```

生产通过标准：

- `pose_production_preflight.summary.passed=true`
- `pose_optimization_pipeline.summary.status=ok`
- `pose_optimization_pipeline.summary.production_ready=true`
- `pose_evidence_package_check.summary.handoff_ready=true`
- `pose_deployment_guard.summary.deployment_allowed=true`
- `pose_promotion_gate.summary.promotion_allowed=true`

runtime 指标门槛：

- `runtime_pose_valid_rate >= 0.70`
- `latest_result_pose_available_ratio >= 0.60`
- `runtime_inference_success_rate >= 0.95`
- 不允许大量 `pose_frame_stale_detection_lag`
- 不允许大量 `frame_tracking_desync`
- 不允许 `pose_track_mismatch` 进入可用骨架

provider A/B 门槛：

- CUDA device
- sampled frames >= 120
- inference attempts >= 30
- avg latency <= 250ms
- avg skeleton confidence >= 0.50
- no provider errors
- no pose track mismatch

temporal/LSTM 门槛：

- temporal rows >= 1000
- pose available rows >= 100
- 覆盖 `ur_fall` 和 `gmdcsa24`
- 覆盖 `fall` 和 `non_fall`
- pose rows 必须带 provider/model metadata
- bbox+motion+pose LSTM 必须优于 bbox+motion baseline
- bbox+motion+pose LSTM 必须优于 zero-pose ablation
- false positive 不能变差

## 6. 长时间稳定性压测计划

生产环境通过基础门禁后，必须执行长时间稳定性测试。

建议分三档：

| 档位 | 时长 | 输入 | 目的 |
| --- | ---: | --- | --- |
| S1 | 10 分钟 | 单摄像头真实 RTSP | 冒烟确认服务不崩、status 可查 |
| S2 | 2 小时 | 单摄像头真实 RTSP | 检查内存、CPU/GPU、pose stale、tracking desync |
| S3 | 8 小时 | 白天/夜间混合场景 | 检查长期漂移、断流重连、误报、漏报 |

每档必须采集：

- `/api/v1/status`
- latest result
- pose worker status
- result publisher status
- GPU memory
- CPU/memory
- RTSP reconnect count
- fall alert count
- pose quality counts
- skip reasons
- false positive/false negative 人工复核表

通过标准：

- 服务进程无崩溃
- RTSP 断流可恢复
- GPU memory 无持续泄漏
- status 延迟稳定
- `pose_valid_rate` 不随时间持续下降
- stale/desync 不呈持续累积
- 告警无明显重复刷屏

## 7. 回归测试触发条件

以下改动后必须重跑 A 到 E，全量生产前再跑 F：

- 换检测模型
- 换姿态模型
- 改 `POSE_PROVIDER`
- 改 `POSE_RESULT_TTL_MS`
- 改 `POSE_MAX_FRAME_AGE_MS`
- 改 `POSE_MAX_TRACKING_FRAME_DELTA`
- 改 tracking 逻辑
- 改 result publisher
- 改 temporal feature schema
- 改 LSTM 模型
- 改 fall fusion 或告警确认规则
- 改启动脚本或 deployment guard

## 8. 问题定位顺序

如果骨架不稳定，按这个顺序查：

1. `/status` 是否能看到正确 provider/model。
2. CUDA 是否可用，provider 是否真的跑在 CUDA。
3. detection 是否稳定有人框。
4. tracking frame 是否落后 detection。
5. pose worker 是否大量 busy skip。
6. detection frame 是否 stale。
7. pose result 是否 TTL 过期。
8. publisher 是否因为 frame alignment 丢骨架。
9. pose quality 是否大量 low_quality。
10. temporal rows 是否真的带 `pose_available=true`。
11. LSTM 是否优于 zero-pose ablation。

如果前 1 到 8 没过，不要急着重训模型。那是链路不稳，不是训练玄学。

## 9. 当前下一步

当前已经完成本机稳定性回归：

```text
167 passed, 4 warnings
```

下一步必须在 CUDA 生产候选机执行：

1. 启动真实 FastAPI 服务。
2. 确认 `/api/v1/status` 可访问。
3. 跑 `check_pose_production_preflight.py`。
4. 跑完整 `run_pose_optimization_pipeline.py --mode production`。
5. 只有 promotion gate 通过，才允许把“姿态检测稳定”写进上线结论。

在这之前，所有“效果稳定了”“骨架提升了”的说法都只能算嘴硬，不算证据。
