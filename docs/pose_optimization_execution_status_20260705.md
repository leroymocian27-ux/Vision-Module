# 姿态检测优化执行状态与下一步计划（2026-07-05）

## 结论先说

当前姿态检测接入系统后的效果差，不能简单归咎于“模型太烂”。更难听但更准确的说法是：姿态链路还没有稳定成为系统证据，直接重训模型属于把锅甩给 GPU 的廉价动作。

现在已经完成的改进是：系统开始记录姿态运行时诊断、离线 provider A/B 能输出姿态质量分布、时序数据导出能保留姿态质量字段，LSTM 训练 manifest 可以用 `--require-pose` 阻止脏姿态数据进入训练。

还没有完成的是：真实服务 A/B、CUDA provider A/B、全量 pose-aware 时序数据重导、bbox+motion 与 bbox+motion+pose LSTM 对照训练。因此当前不能宣布“姿态模型已优化完成”。

## 当前系统证据

当前 `.env` 中姿态配置已经从脆弱 A 档调整为保守 B 档：

- `POSE_PROVIDER=yolo11_legacy`
- `YOLO11_POSE_MODEL_PATH=models/pose_yolo_batch001_003_yolo11s_best.pt`
- `POSE_WORKER_FPS=3`
- `POSE_RESULT_TTL_MS=800`
- `POSE_MAX_FRAME_AGE_MS=800`
- `POSE_MAX_TRACKING_FRAME_DELTA=2`
- `YOLO_POSE_DEVICE=cuda:0`

说明：没有直接把 `POSE_MAX_TRACKING_FRAME_DELTA` 改成 3。虽然 C 档在 tracking lag 压测里通过，但放宽帧差会增加错绑风险。先用 B 档稳住 TTL 和 frame age；只有真实 `/status` 持续出现 `frame_tracking_desync`，并且 `pose_track_mismatch` 没有升高时，才切 C。

本机开发环境事实：

- `torch.cuda.is_available() = False`
- 当前机器只能做 CPU 烟测，不能替代生产 CUDA 评估。
- live `/status` 当前未响应，`scripts/probe_pose_runtime_status.py` 采样失败，错误为连接被拒绝。

已有基线文件：

- `evaluations/pose_runtime_baseline_20260705.json`
- `docs/pose_runtime_baseline_20260705.md`

基线中最刺眼的问题：

- 旧 E2E：`pose_valid=0.3`、`pose_fps=0.67`、`skipped_due_to_busy=137`。这不是“姿态偶尔不准”，这是链路在运行时经常交不上卷。
- 当前候选 `pose_yolo_batch001_003_yolo11s_best.pt` 的 `pose mAP50-95=0.848643`，低于 baseline `yolo11n-pose.pt` 的 `0.883491`。它更快，但不是更准。
- 旧时序数据 `data/temporal_sequences_phase6d` 有姿态字段，但 `pose_available_true_rows=0`，`pose_quality_counts={"unknown": 6659}`。也就是说 LSTM 表面上吃了姿态字段，实际上吃的是空气。

## 今天新增的实现进展

### 1. 修复 provider A/B 采样上限

修复文件：

- `scripts/benchmark_pose_providers.py`
- `tests/test_benchmark_pose_providers.py`

问题：`--max-frames-per-video` 原来按原始帧号停止。比如 `frame_stride=20`、`max=80`，实际只采 4 帧。拿 4 帧判断 provider，结论薄得离谱。

现在：`--max-frames-per-video` 表示最多采样帧数。stride 后会采满指定样本量再停。

验证：

```powershell
python -m pytest tests\test_benchmark_pose_providers.py tests\test_check_pose_temporal_sequences.py tests\test_probe_pose_runtime_status.py
```

结果：`9 passed`。

### 2. 重跑 CPU 开发机 provider smoke

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

- 离线小样本上，两个 provider 都能把姿态挂回目标，说明模型不是彻底瘫痪。
- CPU 上 `yolo11_legacy` 更慢，`yolo` 更快；但这不是生产选择结论，因为生产必须看 CUDA、真实摄像头、worker 竞争和 TTL。
- 如果线上仍然 `pose_valid_rate` 很低，第一嫌疑不是“模型不会看人”，而是调度、过期、busy skip、track 对齐这几块烂泥。

### 3. 导出 pose-aware 小型时序数据

导出目录：

- `data/temporal_sequences_pose_dev`

检查命令：

```powershell
python scripts\check_pose_temporal_sequences.py --input-dir data\temporal_sequences_pose_dev --output evaluations\pose_temporal_sequences_check_dev_20260705.json
```

结果摘要：

- `jsonl_files=4`
- `rows=26`
- `pose_available_true_rows=10`
- `pose_available_true_ratio=0.3846`
- `known_pose_quality_ratio=1.0`
- `vector_dim_errors=0`
- `mismatch_available_rows=0`
- `pose_quality_counts={"high_confidence": 10, "pose_absent": 16}`

解释：

- 姿态字段已经能干净进入时序向量。
- `pose_track_mismatch` 没有被错误当成可用姿态。
- 这批数据太小、fall/non_fall 不均衡，只能证明管道，不允许拿来训练正式模型。

### 4. 生成 pose LSTM 开发 manifest

命令：

```powershell
python scripts\build_temporal_v6_lstm_training_manifest.py --base-dir data\temporal_sequences_pose_dev --residual-dir data\temporal_v6_training\residual_reviewed --output data\temporal_v6_training\lstm_v6_pose_dev_training_manifest.json --model-version v6_pose_dev --epochs 1 --stride 2 --require-pose
```

结果：

- `pose_training_gate.passed=true`
- `pose_available_true_ratio=0.3846`
- `known_pose_quality_ratio=1.0`
- `trainable_input_count=3`
- `skipped_unusable_input_count=1`

解释：`--require-pose` gate 有效。0 行文件会被跳过，脏姿态数据不会悄悄混进训练。

### 5. 增强批量导出脚本

修复文件：

- `scripts/export_dataset_temporal_sequences.py`
- `tests/test_export_dataset_temporal_sequences.py`

新增能力：

- `--label-filter all|fall|non_fall`
- `--video-id` 可重复指定

用途：全量重导前可以先做平衡抽样，例如只导 10 个 fall 和 10 个 ADL，而不是手工拼命令。手工拼命令不是工程流程，是迟早会漏参数的体力劳动。

验证：

```powershell
python -m pytest tests\test_export_dataset_temporal_sequences.py tests\test_benchmark_pose_providers.py
```

结果：`9 passed`。

### 6. 新增离线运行时回放 A/B 工具

新增文件：

- `scripts/replay_pose_runtime_profiles.py`
- `tests/test_replay_pose_runtime_profiles.py`

这个工具和普通离线 provider benchmark 不一样。它会把视频帧送进真实 detector、真实 tracker、`PoseWorkerService._tick()` 和 `ResultPublisherService._build_result()`，所以能检查 worker 是否跳过、姿态结果是否进入发布结果、TTL 是否把姿态证据吃掉。

基础命令：

```powershell
python scripts\replay_pose_runtime_profiles.py --video datasets\ur_fall\videos\fall-01.mp4 --provider yolo11_legacy --device cpu --frame-stride 10 --max-sampled-frames 6 --replay-fps 2.5 --profiles A,B,C --output evaluations\pose_runtime_replay_profiles_cpu_fall01_paced_20260705.json
```

TTL 压测命令：

```powershell
python scripts\replay_pose_runtime_profiles.py --video datasets\ur_fall\videos\fall-01.mp4 --provider yolo11_legacy --device cpu --frame-stride 10 --max-sampled-frames 6 --replay-fps 2.5 --publish-delay-ms 700 --profiles A,B,C --output evaluations\pose_runtime_replay_profiles_cpu_fall01_ttl700_20260705.json
```

TTL 压测结果：

| profile | POSE_RESULT_TTL_MS | published_pose_available_ratio | pose_valid_rate | gate |
|---|---:|---:|---:|---|
| A | 500 | 0.0 | 1.0 | fail |
| B | 800 | 1.0 | 1.0 | pass |
| C | 1000 | 1.0 | 1.0 | pass |

解释：A 不是没算出姿态，而是 700ms 发布延迟下，500ms TTL 直接把姿态结果判死刑。这个问题非常实际：线上只要 detection/tracking/pose/publish 任一环节抖一下，前端和下游就会看到“没有姿态”。

frame-age 压测命令：

```powershell
python scripts\replay_pose_runtime_profiles.py --video datasets\ur_fall\videos\fall-01.mp4 --provider yolo11_legacy --device cpu --frame-stride 10 --max-sampled-frames 6 --replay-fps 2 --detection-age-offset-ms 700 --profiles A,B,C --output evaluations\pose_runtime_replay_profiles_cpu_fall01_age700_20260705.json
```

结果摘要：

- A：`pose_frame_stale=6`，`pose_valid_rate=0.0`
- B/C：能完成姿态附着，但仍受 `POSE_FPS` 节流影响，发布可见比例只有 `0.5`

解释：`POSE_MAX_FRAME_AGE_MS=500` 很容易把稍微排队的帧直接丢掉。B/C 的 800ms 更合理，但还要结合真实服务观察 busy skip 和发布节奏。

tracking lag 压测命令：

```powershell
python scripts\replay_pose_runtime_profiles.py --video datasets\ur_fall\videos\fall-01.mp4 --provider yolo11_legacy --device cpu --frame-stride 10 --max-sampled-frames 6 --replay-fps 1.5 --tracking-lag-frames 3 --profiles A,B,C --output evaluations\pose_runtime_replay_profiles_cpu_fall01_lag3_20260705.json
```

结果摘要：

| profile | POSE_MAX_TRACKING_FRAME_DELTA | published_pose_available_ratio | skip reason | gate |
|---|---:|---:|---|---|
| A | 2 | 0.0 | frame_tracking_desync=6 | fail |
| B | 2 | 0.0 | frame_tracking_desync=6 | fail |
| C | 3 | 0.8333 | pose_fps_throttle=1 | pass |

解释：如果 tracking 相对 detection 抖到 3 帧，A/B 会直接把姿态挡在门外。C 能吸收这类轻微滞后。但这不是让大家无脑放宽 delta；delta 放宽会增加错绑风险，必须看 `pose_track_mismatch` 和 ADL false alarm。

### 7. 修复 POSE_FPS 节流时间基准

修复文件：

- `app/services/pose_service.py`
- `tests/test_pose_service.py`

问题：修复前，`PoseService` 把 `_last_run_at` 记在推理结束时间。`PoseWorkerService` 的 tick 是按 worker 周期调度的，如果 `POSE_WORKER_FPS=3`、`POSE_FPS=3`，一次推理耗时 300ms，下一次 tick 虽然距离上一次 tick 已经接近 333ms，但距离“推理结束”只有几十毫秒，于是会被误判为 `pose_fps_throttle`。

这就很糟糕：系统明明配置 3 FPS，实际有效姿态 FPS 可能被推理耗时砍半。模型还没来得及丢人，调度先把它掐住了。

现在：`_last_run_at` 改为记录推理开始时间。节流基准和 worker tick 基准一致。

验证命令：

```powershell
python -m pytest tests\test_pose_service.py tests\test_replay_pose_runtime_profiles.py
```

结果：`11 passed`。

修复后重跑正常节奏回放：

```powershell
python scripts\replay_pose_runtime_profiles.py --video datasets\ur_fall\videos\fall-01.mp4 --provider yolo11_legacy --device cpu --frame-stride 10 --max-sampled-frames 6 --replay-fps 2.5 --profiles A,B,C --output evaluations\pose_runtime_replay_profiles_cpu_fall01_paced_after_throttle_fix_20260705.json
```

结果：A/B/C 的 `published_pose_available_ratio` 都从修复前的 `0.5` 提升到 `1.0`，`pose_fps_throttle` 消失。

修复后 TTL 压测：

- A：`published_pose_available_ratio=0.0`
- B：`published_pose_available_ratio=1.0`
- C：`published_pose_available_ratio=1.0`

修复后 frame-age 压测：

- A：`pose_frame_stale=6`，`pose_valid_rate=0.0`
- B/C：`pose_valid_rate=1.0`，`published_pose_available_ratio=1.0`

修复后 tracking lag 压测：

- A/B：`frame_tracking_desync=6`
- C：`published_pose_available_ratio=1.0`

结论：节流 bug 已修，B 档足以解决 TTL/frame-age 脆弱性；C 档专门留给真实 tracking lag 超过 2 帧的场景。

## 当前问题拆解

### A. 运行时问题仍是头号嫌疑

旧 E2E 的 `skipped_due_to_busy=137` 已经很难看。`POSE_WORKER_FPS=2` 加 `POSE_RESULT_TTL_MS=500` 也很脆：worker 一慢，结果就过期；结果一过期，下游就像没看见姿态；下游没看见姿态，最后大家开始骂模型。

必须先跑真实服务 A/B：

```powershell
python scripts\probe_pose_runtime_status.py --profile-name A --duration-seconds 60 --interval-seconds 2 --output evaluations\pose_runtime_profile_A_20260705.json
python scripts\probe_pose_runtime_status.py --profile-name B --duration-seconds 60 --interval-seconds 2 --output evaluations\pose_runtime_profile_B_20260705.json
python scripts\probe_pose_runtime_status.py --profile-name C --duration-seconds 60 --interval-seconds 2 --output evaluations\pose_runtime_profile_C_20260705.json
```

建议 A/B/C：

- A：保持当前 `POSE_WORKER_FPS=2`、`POSE_RESULT_TTL_MS=500`、`POSE_MAX_FRAME_AGE_MS=500`
- B：`POSE_WORKER_FPS=3`、`POSE_RESULT_TTL_MS=800`、`POSE_MAX_FRAME_AGE_MS=800`
- C：`POSE_WORKER_FPS=3`、`POSE_RESULT_TTL_MS=1000`、`POSE_MAX_FRAME_AGE_MS=800`、`POSE_MAX_TRACKING_FRAME_DELTA=3`

通过线：

- `runtime_pose_valid_rate >= 0.70`
- busy skip 不超过目标数 10%
- `pose_frame_stale`、`frame_tracking_desync`、`pose_track_mismatch` 不应持续增长

### B. provider/model 选择还没有生产证据

CPU dev smoke 只能说明“小样本能跑”。正式选择必须跑 CUDA：

```powershell
python scripts\benchmark_pose_providers.py --providers yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx --device cuda:0 --output evaluations\pose_provider_ab_20260705.json
```

看这些指标，不要只看截图好不好看：

- `pose_valid_rate`
- `pose_frame_ratio`
- `pose_object_frame_ratio`
- `pose_quality_counts`
- `skip_reasons`
- `avg_latency_ms`
- ADL false alarm
- fall recall
- 告警延迟

### C. LSTM 目前还没真正用上姿态

旧数据 `pose_available_true_rows=0`，所以旧 LSTM 不能被描述为“融合了姿态”。它最多叫“预留了姿态字段”。这两个说法差别很大，前者像系统能力，后者像占位符。

全量重导必须在运行时和 provider gate 之后执行：

```powershell
python scripts\export_dataset_temporal_sequences.py --dataset ur_fall --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\export_dataset_temporal_sequences.py --dataset gmdcsa24 --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\check_pose_temporal_sequences.py --input-dir data\temporal_sequences_pose_v1 --output evaluations\pose_temporal_sequences_check_20260705.json
```

只有检查通过，才允许生成正式 pose LSTM manifest：

```powershell
python scripts\build_temporal_v6_lstm_training_manifest.py --base-dir data\temporal_sequences_pose_v1 --residual-dir data\temporal_v6_training\residual_reviewed --output data\temporal_v6_training\lstm_v6_pose_training_manifest.json --model-version v6_pose --epochs 20 --stride 4 --require-pose
```

## 下一步执行顺序

1. 启动真实服务，先跑 A 配置 60 秒 runtime probe。
2. 切 B/C 配置重启服务，各跑 60 秒 probe。
3. 如果 runtime gate 不过，先修 TTL、worker FPS、busy lock、frame/track 同步，不要急着训模型。
4. runtime gate 过后，跑 CUDA provider A/B。
5. 选出 provider 后，全量重导 `data/temporal_sequences_pose_v1`。
6. 运行 `check_pose_temporal_sequences.py`，不通过就禁止训练 pose LSTM。
7. 同时训练两个 LSTM：`bbox+motion` baseline 与 `bbox+motion+pose`。
8. 用同一套 v6 regression/acceptance 比较 recall、ADL false positive、告警延迟。
9. 如果 provider 和链路都过关但姿态仍差，再建立 hard set，准备重训姿态模型。

## 禁止事项

- 禁止直接宣布“重训姿态模型”。现在证据还没证明瓶颈是模型本体。
- 禁止使用 `data/temporal_sequences_phase6d` 训练 pose LSTM。那里没有真实姿态。
- 禁止只看 `pose_object_frame_ratio`。有 payload 不等于有可用骨架。
- 禁止把 `pose_track_mismatch` 当成有效姿态证据。错绑骨架比没有骨架更危险。
- 禁止用 CPU smoke 替代 CUDA 生产结论。
