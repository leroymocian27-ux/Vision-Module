# 姿态检测运行诊断手册

## 目标

这份手册用于排查当前姿态检测效果差的问题。不要一上来重训模型；先确认姿态证据有没有稳定进入系统。当前系统最危险的问题不是“模型不够聪明”，而是姿态经常没有进入下游，或者进入时已经过期、错绑、被跳过。

## 先生成基线

运行：

```powershell
python scripts\pose_runtime_baseline_report.py
```

输出：

- `evaluations/pose_runtime_baseline_20260705.json`
- `docs/pose_runtime_baseline_20260705.md`

这份基线会固定当前 `.env`、模型 hash、离线姿态指标、E2E 证据、LSTM 姿态字段覆盖情况。

## 运行时重点字段

启动系统后查询：

```text
GET /status?camera_id=camera_01
```

查看 `pose` 节点：

- `worker_tick_count`：姿态 worker 实际 tick 次数。
- `inference_attempt_count`：真正拿到推理锁并开始姿态推理的次数。
- `inference_success_count`：姿态推理正常返回的次数。
- `pose_target_object_count`：送入姿态模型的目标数量。
- `pose_attached_object_count`：成功挂上可见关键点的目标数量。
- `pose_valid_rate`：`pose_attached_object_count / pose_target_object_count`。
- `inference_success_rate`：`inference_success_count / inference_attempt_count`。
- `skipped_due_to_busy`：因为推理锁忙而跳过的次数。
- `skip_reasons`：累计失败原因分布。

## 判断规则

- `worker_tick_count` 增长，但 `inference_attempt_count` 很低：姿态 worker 在空转，优先查 tracking、frame stale、FPS throttle。
- `inference_attempt_count` 增长，但 `pose_attached_object_count` 很低：模型或 provider 匹配链路有问题，优先查 keypoints、track mismatch、bbox 对齐。
- `skipped_due_to_busy` 持续增长：不是先重训，是先处理推理锁竞争、worker FPS、TTL。
- `pose_valid_rate < 0.70`：禁止把“重训姿态模型”当主方案，先修链路。
- `skip_reasons.pose_frame_stale` 或 `skip_reasons.frame_tracking_desync` 高：当前 500 ms TTL 太脆，进入参数 A/B。
- `skip_reasons.pose_track_mismatch` 高：优先比较 full-frame provider 和 crop provider。

## 第一轮 A/B 配置

A 组保持当前配置：

```env
POSE_WORKER_FPS=2
POSE_RESULT_TTL_MS=500
POSE_MAX_FRAME_AGE_MS=500
POSE_MAX_TRACKING_FRAME_DELTA=2
```

B 组提高稳定性：

```env
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=800
POSE_MAX_FRAME_AGE_MS=800
POSE_MAX_TRACKING_FRAME_DELTA=2
```

C 组验证宽松同步：

```env
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=1000
POSE_MAX_FRAME_AGE_MS=800
POSE_MAX_TRACKING_FRAME_DELTA=3
```

比较指标：

- `pose_valid_rate`
- `frontend_visible_skeleton_ratio`
- `skipped_due_to_busy`
- `skip_reasons`
- 跌倒 recall
- ADL false alarm
- 告警延迟

每次按某一组配置启动系统后，运行：

```powershell
python scripts\probe_pose_runtime_status.py --profile-name A --duration-seconds 60 --interval-seconds 2 --output evaluations\pose_runtime_profile_A_20260705.json
python scripts\probe_pose_runtime_status.py --profile-name B --duration-seconds 60 --interval-seconds 2 --output evaluations\pose_runtime_profile_B_20260705.json
python scripts\probe_pose_runtime_status.py --profile-name C --duration-seconds 60 --interval-seconds 2 --output evaluations\pose_runtime_profile_C_20260705.json
```

输出中的 `gate.passed` 只代表运行链路是否够格进入下一步 provider/model 对比，不代表跌倒业务最终通过。若 `runtime_pose_valid_rate < 0.70`、`busy_skip_too_high`、`pose_frame_stale`、`frame_tracking_desync` 任一明显存在，继续调运行链路，不要急着重训。

## Provider A/B 命令

运行：

```powershell
python scripts\benchmark_pose_providers.py --providers yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx --output evaluations\pose_provider_ab_20260705.json
```

如果当前机器没有可用 CUDA，只做开发机 smoke 时使用：

```powershell
python scripts\benchmark_pose_providers.py --providers yolo11_legacy,yolo --device cpu --limit-fall 1 --limit-non-fall 1 --max-frames-per-video 1 --output evaluations\pose_provider_ab_smoke_20260705.json
```

默认 provider 已调整为 `yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx`。报告中重点看：

- `pose_frame_ratio`：采样帧中挂上有效可见关键点的比例。
- `pose_object_frame_ratio`：采样帧中产生过 pose payload 的比例；这个高但 `pose_frame_ratio` 低，通常说明 payload 里是空骨架或被拒绝骨架。
- `pose_valid_rate`：`pose_attached_object_count / pose_target_object_count`，这是 provider 是否真的能把姿态挂回目标的核心指标。
- `pose_quality_counts`：姿态质量等级分布，`high_confidence`/`valid` 才能作为强证据，`low_quality` 和 `pose_track_mismatch` 不能直接支撑告警。
- `skip_reasons`：姿态失败原因分布，优先看 `no_pose_attached`、`pose_track_mismatch`、`pose_fps_throttle`、`busy`。
- `avg_latency_ms`：平均推理耗时。
- `avg_skeleton_confidence`：平均骨架置信度。
- `errors`：provider 初始化、模型路径或推理异常。

不要只看哪个 provider 骨架“偶尔好看”。如果 `pose_valid_rate` 低、`pose_frame_ratio` 低、busy skip 高、ADL 误报上升，它就是不合格。

离线 provider 对比默认使用很高的 `--pose-fps`，目的是避免快速回放时被运行时节流污染。真正验证 `POSE_FPS`、`POSE_WORKER_FPS`、TTL 时，要回到实时系统或专门的运行时 A/B。

## 重导带姿态的时序数据

运行链路和 provider 过门槛后，再重导 LSTM 时序数据：

```powershell
python scripts\export_dataset_temporal_sequences.py --dataset ur_fall --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose
python scripts\export_dataset_temporal_sequences.py --dataset gmdcsa24 --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose
```

重导后的 `target_feature` 必须包含：

- `pose_available`
- `pose_confidence`
- `torso_angle`
- `head_height_ratio`
- `hip_height_ratio`
- `pose_quality_level`
- `pose_rejected_reason`

验收标准：

- `pose_available_true_rows > 0`
- `pose_quality_counts` 不能只有 `unknown`
- `pose_rejected_reason_counts` 能解释失败来源
- `pose_track_mismatch` 不能作为有效姿态证据

重导后运行：

```powershell
python scripts\check_pose_temporal_sequences.py --input-dir data\temporal_sequences_pose_v1 --output evaluations\pose_temporal_sequences_check_20260705.json
```

只有这个检查通过后，才允许进入 `bbox+motion+pose` LSTM 对照训练。

生成带姿态训练 manifest 时必须加 `--require-pose`：

```powershell
python scripts\build_temporal_v6_lstm_training_manifest.py --base-dir data\temporal_sequences_pose_v1 --residual-dir data\temporal_v6_training\residual_reviewed --output data\temporal_v6_training\lstm_v6_pose_training_manifest.json --model-version v6_pose --epochs 20 --stride 4 --require-pose
```

如果 `pose_training_gate.passed=false` 或 `train_command=null`，禁止训练 `bbox+motion+pose` LSTM。旧的 `data\temporal_sequences_phase6d` 会在这里失败，这是预期的，因为它的 `pose_available_true_rows=0` 且 `pose_quality_counts` 全是 `unknown`。

## 最终 readiness 总闸门

如果要按计划顺序执行全部生产 gate，优先使用阶段化 runner：

```powershell
python scripts\run_pose_optimization_pipeline.py --dry-run --summary evaluations\pose_optimization_pipeline_dry_run_20260705.json
```

确认命令无误、服务已启动、CUDA 可用后，再去掉 `--dry-run`：

```powershell
python scripts\run_pose_optimization_pipeline.py --summary evaluations\pose_optimization_pipeline_20260705.json
```

runner 会按以下顺序执行，并在任一阶段失败时停止：

1. `runtime_probe`
2. `provider_ab`
3. `temporal_export_ur_fall`
4. `temporal_export_gmdcsa24`
5. `temporal_pose_check`
6. `lstm_pose_manifest`
7. `readiness`

默认 runner 使用 `--device cuda:0` 和正式生产输出路径。当前开发机没有 CUDA 时，只运行 `--dry-run`；不要把 dry-run 当成通过证据。

完成真实 runtime probe、CUDA provider A/B、全量 pose-aware 时序检查、pose LSTM manifest 后，运行：

```powershell
python scripts\check_pose_optimization_readiness.py --output evaluations\pose_optimization_readiness_20260705.json
```

默认检查以下生产路径：

- `evaluations\pose_runtime_profile_B_20260705.json`
- `evaluations\pose_provider_ab_20260705.json`
- `evaluations\pose_temporal_sequences_check_20260705.json`
- `data\temporal_v6_training\lstm_v6_pose_training_manifest.json`

总闸门通过才允许进入正式 LSTM 训练和后续上线评估。它会阻止以下常见误判：

- live `/status` 没跑通，却拿离线结果说 runtime 已经稳定。
- 只有 CPU/dev provider smoke，却当成 CUDA 生产选择。
- 只有小样本 pose-aware 数据，却当成全量训练数据。
- LSTM manifest 没有 `--require-pose`，却继续训练。

如果当前只想审查开发机证据，可以显式传入 dev 文件：

```powershell
python scripts\check_pose_optimization_readiness.py --runtime-profile evaluations\pose_runtime_profile_B_check_20260705.json --provider-ab evaluations\pose_provider_ab_cpu_dev_20260705.json --temporal-check evaluations\pose_temporal_sequences_check_dev_20260705.json --lstm-manifest data\temporal_v6_training\lstm_v6_pose_dev_training_manifest.json --output evaluations\pose_optimization_readiness_dev_current_20260705.json
```

注意：这个 dev 检查失败是正常的，因为 live runtime 和 CUDA provider 还没有生产证据。失败不丢人，拿失败的证据装通过才丢人。

## 当前基线结论

当前证据显示：

- 当前 `.env` 使用 `POSE_PROVIDER=yolo11_legacy` 和 `models/pose_yolo_batch001_003_yolo11s_best.pt`。
- 旧 E2E 证据中 `pose_valid=0.3`、`pose_fps=0.67`、`skipped_due_to_busy=137`，姿态链路明显不稳。
- 当前 yolo11s 姿态候选 `pose mAP50-95=0.848643`，低于 `yolo11n-pose.pt` baseline 的 `0.883491`，只是更快，不是更好。
- `data/temporal_sequences_phase6d` 中姿态字段存在，但 `pose_available_true_rows=0`，LSTM 没有真正学到姿态。

结论很难听但必须承认：现在的姿态不是“精度差一点”，而是还没有稳定成为系统证据。先修链路，再做 provider A/B，再做数据和重训。
