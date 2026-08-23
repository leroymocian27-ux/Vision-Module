# 姿态检测优化目标期间工作总览（2026-07-05）

## 1. 文档目的

这份文档整理本轮目标期间围绕“完善并优化姿态检测模型”实际完成的工作。它不是宣传稿，也不是一句“建议多训练数据”。这里记录的是已经落到代码、配置、数据、评估和文档里的内容，以及当前仍未完成的生产级闭环。

一句话概括：本轮没有急着重训姿态模型，而是先把姿态检测从“偶尔能出骨架的模型”推进到“可诊断、可回放、可进入时序数据、可被训练 gate 约束的系统链路”。这一步不 glamorous，但很关键，因为现在的问题很大一部分不是模型不会看人，而是姿态证据在运行时被跳过、过期、错绑或没有进入下游。

## 2. 起点问题

目标开始时，系统里的姿态检测主要有以下问题。

### 2.1 当前模型接入效果差

旧 E2E 证据显示：

- `pose_valid=0.3`
- `pose_fps=0.67`
- `skipped_due_to_busy=137`

这不是“精度差一点”。这说明姿态链路在线上经常没有稳定给下游交付可用证据。

### 2.2 当前候选模型不是明显更优

当前接入模型：

- `models/pose_yolo_batch001_003_yolo11s_best.pt`

基线报告中模型指标：

- baseline `yolo11n-pose.pt`：`pose mAP50-95=0.883491`
- candidate `pose_yolo_batch001_003_yolo11s_best.pt`：`pose mAP50-95=0.848643`
- candidate 更快，但 mAP 更低

结论：不能因为它是当前接入模型就默认它更好。它可能只是更快，并不更准。

### 2.3 LSTM 实际没有用上姿态

旧时序数据：

- `data/temporal_sequences_phase6d`

检查结果：

- `rows=6659`
- `pose_available_true_rows=0`
- `pose_quality_counts={"unknown": 6659}`

这意味着旧 LSTM 数据虽然有姿态字段名，但没有真实可用姿态。说得刻薄一点：它不是“融合姿态”，它只是“字段占位”。

### 2.4 原运行时配置过于脆弱

目标初期 `.env` 中姿态运行时配置：

- `POSE_WORKER_FPS=2`
- `POSE_RESULT_TTL_MS=500`
- `POSE_MAX_FRAME_AGE_MS=500`
- `POSE_MAX_TRACKING_FRAME_DELTA=2`

500ms TTL 和 frame age 对一个包含 detection、tracking、pose worker、publisher 的异步链路来说非常脆。任一环节抖一下，下游就看不到姿态。

## 3. 总体处理策略

本轮采用的顺序是：

1. 先做运行时诊断，不先重训。
2. 区分模型问题、调度问题、TTL 问题、tracking 对齐问题。
3. 让 provider A/B 有足够指标，不只看骨架截图。
4. 让姿态质量字段进入时序数据。
5. 用 gate 阻止脏姿态数据进入 LSTM 训练。
6. 用本地 replay 工具复现运行时损耗。
7. 修明确认存在的运行时 bug。
8. 只把当前配置调到保守稳定档，不做过度放宽。

这个顺序的核心判断是：如果姿态证据还没有稳定进入系统，直接重训模型就是把问题打包扔给训练脚本，听起来忙，实际上不聪明。

## 4. 已完成的代码改动

### 4.1 姿态运行时诊断指标

涉及文件：

- `app/services/pose_service.py`
- `app/services/pose_worker_service.py`
- `app/pose/schemas.py`
- `app/schemas/status.py`
- `app/pose/placeholders.py`
- `app/fall/feature_builder.py`

新增或完善的诊断指标：

- `worker_tick_count`
- `inference_attempt_count`
- `inference_success_count`
- `pose_target_object_count`
- `pose_attached_object_count`
- `pose_valid_rate`
- `inference_success_rate`
- `skip_reasons`
- `pose_quality_level`

这些字段让 `/status` 不再只告诉我们“姿态开没开”，而是能回答：

- worker 是否在跑？
- worker 跑了但是否没有目标？
- 是否被 `pose_fps_throttle` 节流？
- 是否因为 busy lock 跳过？
- 是否因为 frame stale 跳过？
- 是否因为 tracking/detection 帧不同步跳过？
- 是否算出了 payload 但没有可见关键点？
- 是否发生了 track mismatch？

### 4.2 姿态质量分级

新增质量等级：

- `high_confidence`
- `valid`
- `low_quality`
- `pose_track_mismatch`
- `pose_absent`

核心原则：

- `high_confidence` 和 `valid` 才能作为有效姿态证据。
- `low_quality` 不能直接支持告警。
- `pose_track_mismatch` 不但不能支持告警，还要明确记录为风险。
- `pose_absent` 要和 `unknown` 区分开，避免旧数据污染训练。

这修掉了一个很隐蔽的问题：以前有 payload 不等于有姿态。现在系统会更严格地区分“真骨架”和“看上去像骨架字段的空壳”。

### 4.3 修复 POSE_FPS 节流时间基准

涉及文件：

- `app/services/pose_service.py`
- `tests/test_pose_service.py`

问题：

修复前，`PoseService` 把 `_last_run_at` 记录在推理结束时间。假设：

- `POSE_WORKER_FPS=3`
- `POSE_FPS=3`
- 单次姿态推理耗时约 300ms

worker 下一次 tick 可能已经接近 333ms 间隔，但因为 `_last_run_at` 是推理结束时间，系统会误以为“刚刚跑过”，于是跳过，记为 `pose_fps_throttle`。

结果就是：配置看起来是 3 FPS，实际有效姿态 FPS 可能被推理耗时砍掉一大截。

修复：

- `_last_run_at` 改为记录推理开始时间。
- 节流基准和 worker tick 调度基准保持一致。

验证结果：

- 修复后正常节奏 replay 中 A/B/C 的 `published_pose_available_ratio` 从修复前的 `0.5` 提升到 `1.0`。
- `pose_fps_throttle` 消失。

### 4.4 provider A/B 脚本增强

涉及文件：

- `scripts/benchmark_pose_providers.py`
- `tests/test_benchmark_pose_providers.py`

主要改动：

- 默认 provider 扩展为：`yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx`
- 支持 `--providers`
- 支持 `--device cpu|cuda:0`
- 支持高默认 `--pose-fps`，避免离线 replay 被运行时节流污染
- 输出 `pose_valid_rate`
- 输出 `pose_frame_ratio`
- 输出 `pose_object_frame_ratio`
- 输出 `skip_reasons`
- 输出 `pose_quality_counts`

还修复了一个评估漏洞：

原来的 `--max-frames-per-video` 实际按原始帧号停止。比如 `frame_stride=20`、`max=80` 时，只采 4 帧。拿 4 帧判断 provider，结论太薄。

现在 `--max-frames-per-video` 表示“最多采样帧数”，stride 后会采满指定样本量再停。

### 4.5 live `/status` runtime probe

新增文件：

- `scripts/probe_pose_runtime_status.py`
- `tests/test_probe_pose_runtime_status.py`

用途：

对真实运行中的 FastAPI `/status` 进行连续采样，计算运行时增量。

输出重点：

- `runtime_deltas`
- `skip_reason_delta`
- `runtime_pose_valid_rate`
- `runtime_inference_success_rate`
- `latest_result_pose_available_ratio`
- gate 判断

当前本机结果：

- 本机 live `/status` 未响应。
- `evaluations/pose_runtime_profile_current_short_20260705.json` 中 `ok_samples=0`
- 错误为连接被拒绝。

结论：

这台机器当前不能完成真实服务 A/B，只能做 CPU/offline/replay 证据。真实服务 probe 仍是生产闸门。

### 4.6 离线运行时 replay 工具

新增文件：

- `scripts/replay_pose_runtime_profiles.py`
- `tests/test_replay_pose_runtime_profiles.py`

这个工具是本轮非常关键的补充。

它和普通离线 provider benchmark 不同。它会把视频帧送进：

1. 真实 person detector
2. 真实 tracker
3. `PoseWorkerService._tick()`
4. `ResultPublisherService._build_result()`

所以它能复现以下问题：

- worker 是否跳过姿态？
- detection frame 是否 stale？
- tracking frame 是否和 detection 不同步？
- pose 结果是否进入 `RealtimeResultStore`？
- publisher 是否因为 TTL 过期而丢掉姿态？
- 最终发布结果里是否有可见骨架？

支持的控制参数：

- `--profiles A,B,C`
- `--device cpu|cuda:0`
- `--provider`
- `--replay-fps`
- `--publish-delay-ms`
- `--detection-age-offset-ms`
- `--tracking-lag-frames`

这让我们不用启动完整 FastAPI，也能在本地复现运行时的关键损耗点。

### 4.7 时序导出支持 pose-aware 数据

涉及文件：

- `app/temporal/schemas.py`
- `app/temporal/target_feature_extractor.py`
- `scripts/export_temporal_sequences.py`
- `scripts/export_dataset_temporal_sequences.py`
- `tests/test_target_feature_extractor.py`
- `tests/test_export_dataset_temporal_sequences.py`

改动：

- `TargetFeature` 增加 `pose_quality_level`
- `TargetFeature` 增加 `pose_rejected_reason`
- 导出脚本支持 `--enable-pose`
- 导出脚本支持 `--device`
- 批量导出脚本支持 `--label-filter all|fall|non_fall`
- 批量导出脚本支持重复 `--video-id`

目的：

全量重导前可以先做平衡抽样，例如只导若干 fall 和若干 ADL，而不是人工拼命令。人工拼命令在这种链路里很危险，漏一个参数就能生成一批看似正常、实际脏掉的数据。

### 4.8 姿态时序数据检查器

新增文件：

- `scripts/check_pose_temporal_sequences.py`
- `tests/test_check_pose_temporal_sequences.py`

检查内容：

- 是否有 JSONL 文件
- 是否有行
- `pose_available_true_ratio`
- `known_pose_quality_ratio`
- 向量维度是否正确
- `pose_track_mismatch` 是否被错误当成可用姿态
- label 分布
- dataset 分布

用途：

禁止旧的全 `unknown` 姿态数据继续进入 LSTM。

### 4.9 LSTM manifest 增加 `--require-pose`

新增或修改文件：

- `scripts/build_temporal_v6_lstm_training_manifest.py`
- `tests/test_temporal_v6_lstm_training_manifest.py`

新增能力：

- `--require-pose`
- `pose_training_gate`
- 如果 pose gate 失败，`train_command=null`
- CLI 返回非 0，阻止误训练

gate 检查：

- `pose_available_true_ratio`
- `known_pose_quality_ratio`
- `mismatch_available_rows`
- `pose_quality_counts`
- `pose_rejected_reason_counts`

这一步的意义很大：以后不能再拿“有姿态字段名但没有姿态证据”的数据去训练 pose LSTM。

### 4.10 新增姿态优化 readiness 总闸门

新增文件：

- `scripts/check_pose_optimization_readiness.py`
- `tests/test_check_pose_optimization_readiness.py`

用途：

把计划中的四个生产 gate 串成一个总检查：

1. 真实 runtime probe
2. CUDA provider A/B
3. 全量 pose-aware 时序数据检查
4. `--require-pose` LSTM manifest

默认命令：

```powershell
python scripts\check_pose_optimization_readiness.py --output evaluations\pose_optimization_readiness_20260705.json
```

当前默认生产检查结果：

- `overall_ready=false`
- `failed_gates=["runtime","provider","temporal_data","lstm_manifest"]`

原因：

- `runtime_profile_missing`
- `provider_ab_missing`
- `temporal_pose_check_missing`
- `pose_lstm_manifest_missing`

这不是坏消息，而是诚实消息：现在生产证据还没跑完，总闸门不允许把 dev smoke 包装成生产 ready。

使用当前 dev 证据检查：

```powershell
python scripts\check_pose_optimization_readiness.py --runtime-profile evaluations\pose_runtime_profile_B_check_20260705.json --provider-ab evaluations\pose_provider_ab_cpu_dev_20260705.json --temporal-check evaluations\pose_temporal_sequences_check_dev_20260705.json --lstm-manifest data\temporal_v6_training\lstm_v6_pose_dev_training_manifest.json --output evaluations\pose_optimization_readiness_dev_current_20260705.json
```

结果：

- `temporal_data` 通过
- `lstm_manifest` 通过
- `runtime` 失败，因为 live `/status` 未响应
- `provider` 失败，因为当前是 CPU/dev 证据，不是 CUDA 生产证据

### 4.11 新增阶段化 pose 优化 pipeline runner

新增文件：

- `scripts/run_pose_optimization_pipeline.py`
- `tests/test_run_pose_optimization_pipeline.py`

用途：

把生产 gate 的执行顺序固定下来，避免工作人员跳过前置检查直接导数据或训练。

默认 dry-run：

```powershell
python scripts\run_pose_optimization_pipeline.py --dry-run --summary evaluations\pose_optimization_pipeline_dry_run_20260705.json
```

当前已生成：

- `evaluations/pose_optimization_pipeline_dry_run_20260705.json`

dry-run 中包含 7 个阶段：

1. `runtime_probe`
2. `provider_ab`
3. `temporal_export_ur_fall`
4. `temporal_export_gmdcsa24`
5. `temporal_pose_check`
6. `lstm_pose_manifest`
7. `readiness`

真正执行时：

```powershell
python scripts\run_pose_optimization_pipeline.py --summary evaluations\pose_optimization_pipeline_20260705.json
```

runner 会在任一阶段失败时停止。默认使用 `cuda:0` 和正式输出路径，所以当前 CPU-only 开发机只生成 dry-run，不冒充生产执行。

## 5. 已完成的配置改动

### 5.1 当前 `.env` 已调到保守 B 档

当前配置：

- `POSE_PROVIDER=yolo11_legacy`
- `YOLO11_POSE_MODEL_PATH=models/pose_yolo_batch001_003_yolo11s_best.pt`
- `POSE_FPS=3`
- `POSE_WORKER_FPS=3`
- `POSE_RESULT_TTL_MS=800`
- `POSE_MAX_FRAME_AGE_MS=800`
- `POSE_MAX_TRACKING_FRAME_DELTA=2`

说明：

- 没有直接把 `POSE_MAX_TRACKING_FRAME_DELTA` 改成 3。
- C 档虽然在 tracking lag 3 帧压测里通过，但 delta 放宽会增加错绑风险。
- 当前更稳妥的策略是先用 B 档解决 TTL 和 frame-age 脆弱性。
- 只有真实 `/status` 持续出现 `frame_tracking_desync`，并且 `pose_track_mismatch` 没有升高时，再考虑 C 档。

### 5.2 默认配置同步

涉及文件：

- `.env.example`
- `app/core/config.py`

同步内容：

- `POSE_RESULT_TTL_MS=800`
- `POSE_MAX_FRAME_AGE_MS=800`

目的：

避免没有 `.env` 或新部署环境又掉回 500ms 的脆弱默认值。

## 6. 已生成的评估证据

### 6.1 当前基线报告

文件：

- `docs/pose_runtime_baseline_20260705.md`
- `evaluations/pose_runtime_baseline_20260705.json`

当前基线显示：

- `POSE_WORKER_FPS=3`
- `POSE_RESULT_TTL_MS=800`
- `POSE_MAX_FRAME_AGE_MS=800`
- `POSE_MAX_TRACKING_FRAME_DELTA=2`

但旧 E2E 仍然显示：

- `pose_valid=0.3`
- `pose_fps=0.67`
- `skipped_due_to_busy=137`

注意：

旧 E2E 的 provider 是 `yolo`，当前 `.env` 是 `yolo11_legacy`。这也是为什么必须用当前配置重跑真实服务 baseline。

### 6.2 CPU provider A/B

文件：

- `evaluations/pose_provider_ab_cpu_dev_20260705.json`

命令：

```powershell
python scripts\benchmark_pose_providers.py --providers yolo11_legacy,yolo --device cpu --limit-fall 2 --limit-non-fall 2 --frame-stride 10 --max-frames-per-video 5 --output evaluations\pose_provider_ab_cpu_dev_20260705.json
```

结果摘要：

| provider | sampled_frames | pose_frames | pose_valid_rate | avg_latency_ms | avg_skeleton_confidence |
|---|---:|---:|---:|---:|---:|
| yolo11_legacy | 20 | 15 | 1.0 | 298.30 | 0.9745 |
| yolo | 20 | 15 | 1.0 | 127.73 | 0.8758 |

解释：

- 离线小样本上两个 provider 都能挂上姿态。
- 这说明模型不是完全瘫痪。
- CPU 上 `yolo11_legacy` 更慢，`yolo` 更快。
- 这不是生产 provider 结论，因为生产必须看 CUDA 和真实服务调度。

### 6.3 pose-aware dev 时序数据

数据目录：

- `data/temporal_sequences_pose_dev`

检查文件：

- `evaluations/pose_temporal_sequences_check_dev_20260705.json`

结果：

- `jsonl_files=4`
- `rows=26`
- `pose_available_true_rows=10`
- `pose_available_true_ratio=0.3846`
- `known_pose_quality_ratio=1.0`
- `vector_dim_errors=0`
- `mismatch_available_rows=0`
- `pose_quality_counts={"high_confidence": 10, "pose_absent": 16}`

解释：

- 姿态字段已经能进入时序向量。
- 质量字段不是 `unknown`。
- mismatch 没有被错误当成可用姿态。
- 这批数据太小且 fall/non_fall 不均衡，只能证明管道，不可用于正式训练。

### 6.4 pose LSTM dev manifest

文件：

- `data/temporal_v6_training/lstm_v6_pose_dev_training_manifest.json`

结果：

- `pose_training_gate.passed=true`
- `pose_available_true_ratio=0.3846`
- `known_pose_quality_ratio=1.0`
- `trainable_input_count=3`
- `skipped_unusable_input_count=1`

解释：

`--require-pose` 机制有效。0 行文件会被跳过，脏姿态数据不会静悄悄混进训练。

### 6.5 replay 正常节奏 after-fix

文件：

- `evaluations/pose_runtime_replay_profiles_cpu_fall01_paced_after_throttle_fix_20260705.json`

结果：

| profile | pose_valid_rate | published_pose_available_ratio | skip_reasons | gate |
|---|---:|---:|---|---|
| A | 1.0 | 1.0 | `{}` | pass |
| B | 1.0 | 1.0 | `{}` | pass |
| C | 1.0 | 1.0 | `{}` | pass |

解释：

修复 `POSE_FPS` 节流时间基准后，正常节奏下姿态能稳定进入发布结果。

### 6.6 replay TTL 700ms 压测 after-fix

文件：

- `evaluations/pose_runtime_replay_profiles_cpu_fall01_ttl700_after_throttle_fix_20260705.json`

结果：

| profile | pose_valid_rate | published_pose_available_ratio | gate |
|---|---:|---:|---|
| A | 1.0 | 0.0 | fail |
| B | 1.0 | 1.0 | pass |
| C | 1.0 | 1.0 | pass |

解释：

A 档不是没算出姿态，而是 500ms TTL 把已经算出的姿态扔掉了。B/C 的 800ms/1000ms 更能承受运行时发布延迟。

### 6.7 replay frame-age 700ms 压测 after-fix

文件：

- `evaluations/pose_runtime_replay_profiles_cpu_fall01_age700_after_throttle_fix_20260705.json`

结果：

| profile | pose_valid_rate | published_pose_available_ratio | skip reason | gate |
|---|---:|---:|---|---|
| A | 0.0 | 0.0 | `pose_frame_stale=6` | fail |
| B | 1.0 | 1.0 | `{}` | pass |
| C | 1.0 | 1.0 | `{}` | pass |

解释：

500ms frame age 对稍微排队的帧过于苛刻。800ms 能明显改善该问题。

### 6.8 replay tracking lag 3 帧压测 after-fix

文件：

- `evaluations/pose_runtime_replay_profiles_cpu_fall01_lag3_after_throttle_fix_20260705.json`

结果：

| profile | pose_valid_rate | published_pose_available_ratio | skip reason | gate |
|---|---:|---:|---|---|
| A | 0.0 | 0.0 | `frame_tracking_desync=6` | fail |
| B | 0.0 | 0.0 | `frame_tracking_desync=6` | fail |
| C | 1.0 | 1.0 | `{}` | pass |

解释：

tracking 落后 3 帧时，delta=2 会挡住姿态。C 档 delta=3 能通过。但是否切 C 要看真实系统中的 `pose_track_mismatch`，不能只看 replay 通过。

## 7. 已编写的工作人员文档

### 7.1 姿态模型基础说明

文件：

- `docs/pose_detection_model_guide_20260705.md`

用途：

给工作人员理解当前姿态检测模型、质量、性能和问题。

### 7.2 姿态检测与系统/其他模型关系

文件：

- `docs/pose_detection_system_relationships_20260705.md`

用途：

解释姿态检测和 detection、tracking、fall hint、temporal/LSTM、fusion、主系统告警之间的关系。

### 7.3 姿态低性能问题分析

文件：

- `docs/pose_low_performance_problem_analysis_20260705.md`

用途：

集中分析为什么当前系统中姿态效果差，避免把所有问题都归咎于模型。

### 7.4 姿态运行时诊断手册

文件：

- `docs/pose_runtime_diagnostics_runbook_20260705.md`

用途：

给工作人员执行 runtime A/B、provider A/B、pose-aware 时序重导和 LSTM gate。

### 7.5 姿态优化执行状态与下一步计划

文件：

- `docs/pose_optimization_execution_status_20260705.md`

用途：

记录本轮具体实现进展、证据、压测结论和下一步。

### 7.6 本文档

文件：

- `docs/pose_goal_work_summary_20260705.md`

用途：

总览目标期间实际做过的事，便于先整体了解。

## 8. 已运行测试

最近一次相关回归命令：

```powershell
python -m pytest tests\test_run_pose_optimization_pipeline.py tests\test_check_pose_optimization_readiness.py tests\test_replay_pose_runtime_profiles.py tests\test_temporal_v6_lstm_training_manifest.py tests\test_check_pose_temporal_sequences.py tests\test_target_feature_extractor.py tests\test_export_dataset_temporal_sequences.py tests\test_temporal_service.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_pose_service.py tests\test_fall_feature_builder.py tests\test_end_to_end_pipeline.py
```

结果：

- `45 passed`
- 4 个 torchvision/Pillow 既有弃用警告

说明：

本轮姿态运行时诊断、replay 工具、provider A/B、时序导出、LSTM manifest gate、pose service 行为和端到端基础流程均通过当前相关测试。

## 9. 当前结论

### 9.1 已证明的事情

1. 当前姿态问题不能简单判为模型本体问题。
2. 旧运行时配置 500ms TTL/frame-age 确实脆。
3. `POSE_FPS` 节流时间基准存在实际损耗，已修复。
4. B 档配置能解决 replay 中的 TTL/frame-age 脆弱性。
5. tracking lag 3 帧时 C 档有效，但存在错绑风险，不能无脑上线。
6. pose-aware 时序导出链路已经能跑通。
7. `--require-pose` gate 能阻止旧脏数据进入 LSTM 训练。
8. CPU 小样本下 provider 能出姿态，说明模型不是完全瘫痪。
9. readiness 总闸门能阻止 dev/CPU/缺失证据被误判为生产就绪。
10. pipeline runner 能把生产 gate 固定为顺序执行，失败即停。

### 9.2 尚未证明的事情

1. 真实 FastAPI 服务在当前 B 档下是否满足 `runtime_pose_valid_rate >= 0.70`。
2. CUDA 下哪个 provider 最适合生产。
3. 全量 `data/temporal_sequences_pose_v1` 是否能通过 pose gate。
4. `bbox+motion+pose` LSTM 是否优于 `bbox+motion` baseline。
5. C 档 delta=3 是否会引入 `pose_track_mismatch` 或 ADL 误报。
6. 当前姿态模型是否需要重训。

## 10. 当前建议

### 10.1 当前推荐运行配置

保守 B 档：

```env
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=800
POSE_MAX_FRAME_AGE_MS=800
POSE_MAX_TRACKING_FRAME_DELTA=2
```

理由：

- replay TTL 压测中 B 通过，A 失败。
- replay frame-age 压测中 B 通过，A 失败。
- B 没有放宽 frame delta，错绑风险小于 C。

### 10.2 什么时候切 C

只有当真实 `/status` 中持续出现：

- `frame_tracking_desync`

并且没有明显出现：

- `pose_track_mismatch`
- ADL false alarm 上升

才考虑切 C：

```env
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=1000
POSE_MAX_FRAME_AGE_MS=800
POSE_MAX_TRACKING_FRAME_DELTA=3
```

### 10.3 什么情况下才重训姿态模型

只有当以下 gate 都完成后，才应该认真考虑重训：

1. 真实 runtime gate 通过。
2. CUDA provider A/B 完成。
3. pose-aware 全量时序数据重导完成。
4. LSTM pose 对照训练完成。
5. 错误集中仍然来自骨架质量，而不是 runtime skip、TTL、tracking mismatch 或下游使用错误。

如果这些条件没满足就重训，基本就是拿训练当遮羞布。

## 11. 下一步必须执行的生产闸门

### 11.1 真实服务 runtime probe

启动服务后执行：

```powershell
python scripts\probe_pose_runtime_status.py --profile-name B --duration-seconds 60 --interval-seconds 2 --output evaluations\pose_runtime_profile_B_20260705.json
```

如果需要对比 C：

```powershell
python scripts\probe_pose_runtime_status.py --profile-name C --duration-seconds 60 --interval-seconds 2 --output evaluations\pose_runtime_profile_C_20260705.json
```

重点看：

- `runtime_pose_valid_rate`
- `latest_result_pose_available_ratio`
- `skip_reason_delta`
- `busy`
- `pose_frame_stale`
- `frame_tracking_desync`
- `pose_track_mismatch`

### 11.2 CUDA provider A/B

在有 CUDA 的机器上执行：

```powershell
python scripts\benchmark_pose_providers.py --providers yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx --device cuda:0 --output evaluations\pose_provider_ab_20260705.json
```

不要只看速度，也不要只看截图。必须看：

- `pose_valid_rate`
- `pose_frame_ratio`
- `pose_object_frame_ratio`
- `pose_quality_counts`
- `skip_reasons`
- `avg_latency_ms`

### 11.3 全量 pose-aware 时序重导

runtime 和 provider gate 通过后执行：

```powershell
python scripts\export_dataset_temporal_sequences.py --dataset ur_fall --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\export_dataset_temporal_sequences.py --dataset gmdcsa24 --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\check_pose_temporal_sequences.py --input-dir data\temporal_sequences_pose_v1 --output evaluations\pose_temporal_sequences_check_20260705.json
```

### 11.4 pose LSTM manifest

```powershell
python scripts\build_temporal_v6_lstm_training_manifest.py --base-dir data\temporal_sequences_pose_v1 --residual-dir data\temporal_v6_training\residual_reviewed --output data\temporal_v6_training\lstm_v6_pose_training_manifest.json --model-version v6_pose --epochs 20 --stride 4 --require-pose
```

如果 `pose_training_gate.passed=false` 或 `train_command=null`，禁止训练。

### 11.5 LSTM 对照训练

必须训练并比较两组：

1. `bbox+motion`
2. `bbox+motion+pose`

比较指标：

- fall recall
- ADL false positive
- alarm delay
- duplicate alarm
- slow fall recall
- residual FN/FP

## 12. 风险与注意事项

### 12.1 CPU 结果不能代表生产

当前机器：

- `torch.cuda.is_available() = False`

所以 CPU smoke 和 replay 只能证明链路和相对问题，不能替代 CUDA 生产评估。

### 12.2 当前 live 服务未响应

短 probe 文件：

- `evaluations/pose_runtime_profile_current_short_20260705.json`

结果：

- `ok_samples=0`
- 连接被拒绝

说明真实服务 A/B 尚未完成。

### 12.3 `.env` 已改，但生产仍需重启服务

当前 `.env` 已调到 B 档，但运行中的服务如果没有重启，不会自动使用新配置。

### 12.4 工作树很脏

当前仓库有大量既有修改和未跟踪文件。本轮没有回滚用户或其他流程产生的改动。后续提交前应按模块分组审查，不要粗暴全量提交。

## 13. 总结

本轮工作已经把姿态检测优化从“感觉模型不好”推进到“有诊断、有回放、有数据 gate、有运行时修复、有当前推荐配置”的状态。

最重要的实际修复是：

- 修掉 `POSE_FPS` 按推理结束时间节流导致的有效帧率损耗。
- 将 TTL/frame-age 从 500ms 提升到 800ms 的保守 B 档。
- 建立 replay 工具证明 A 档确实会在 TTL/frame-age 压测中失败。
- 建立 pose-aware 时序数据和 LSTM `--require-pose` gate，避免旧脏数据继续污染训练。

当前还不能宣布目标完成，因为生产级验证还缺：

- 真实服务 runtime probe
- CUDA provider A/B
- 全量 pose-aware 时序重导
- 正式 LSTM 对照训练
- 必要时的姿态 hard set 和重训

但现在已经不再是“盲调模型”。下一步该做什么、用什么指标判断、哪些事情不能急着做，都已经落到代码和文档里了。
