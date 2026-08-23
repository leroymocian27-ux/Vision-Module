# 当前姿态检测优化计划（2026-07-05）

## 1. 结论先放前面

当前姿态检测问题不是“模型差一点”这么简单。真正的问题是一整条链路都还不够硬：模型候选不一定更准，运行时容易跳过或丢弃骨架，tracking 和 pose 可能不同步，旧 LSTM 数据根本没有吃到有效骨架，生产级验证还没闭环。

实施进展请看：

```text
docs/pose_plan_implementation_status_20260705.md
```

截至当前实施状态：`dev-smoke` 已完整执行到 readiness，但不是通过，而是被 `lstm_comparison` 正确卡住。本地 CPU 小样本里 runtime/provider/pose-aware temporal export/manifest 已通过，pose LSTM 也能训练并导出 ONNX；修复阈值硬编码后，pose-aware LSTM 使用校准阈值 `0.5`，`F1=0.75`，只追平 baseline bbox+motion LSTM 的 `F1=0.75`，也只追平姿态清零消融的 `F1=0.75`，没有证明更好。当前 blocker 是 `pose_lstm_not_better_than_baseline_f1` 和 `pose_lstm_not_better_than_zero_pose_ablation`。本地 FastAPI + 本地视频 + CPU 的短窗口 probe 证明 `POSE_INFERENCE_LOCK_WAIT_MS=160` 能缓解 busy，新增 detection history 后 `frame_tracking_desync` 已在短窗口对照中从 2 降到 0。当前主要 runtime blocker 收敛到 `pose_frame_stale`。最新 owner 归因显示，之前的 `busy` 主要来自 person detector / fall detector 与 pose 共享同一把 Ultralytics 推理锁。注意，这只是本机 CPU 开发证据，不是 CUDA 生产 120 秒稳定性证明，所以生产级姿态链路仍不能宣布完成。

所以当前计划的第一原则是：

```text
先证明骨架能稳定、正确、按质量分级地进入系统，再讨论重训姿态模型。
```

现在立刻重训模型不是优先级最高的事。否则就是把运行时、数据、训练 gate 的烂账一股脑塞给训练脚本，最后得到一个看似更忙、实际更糊的系统。

当前还有一个更刺眼的新结论：姿态字段能进入 LSTM，不代表姿态融合有效。最新 dev-smoke 里 pose LSTM 在阈值校准后只是追平 baseline，没有多抓住任何东西，也没有少报任何误报；把姿态列清零以后指标还一模一样。这种“多背了一个姿态包袱但没跑更快”的模型不能进生产，只能作为诊断样本继续拆原因。

## 2. 当前证据判断

### 2.1 线上姿态链路不稳定

旧 E2E 证据：

```text
pose_valid = 0.3
pose_fps = 0.67
skipped_due_to_busy = 137
```

这说明姿态链路不是偶发抖动，而是经常没有给下游提供可用骨架。跌倒检测需要骨架时，系统可能压根没有拿到骨架证据。

### 2.2 当前姿态模型不是确定更优

当前接入模型：

```text
models/pose_yolo_batch001_003_yolo11s_best.pt
```

已知对比：

```text
baseline yolo11n-pose.pt: pose mAP50-95 = 0.883491
candidate 当前模型:       pose mAP50-95 = 0.848643
```

当前模型可能更快，但它不是天然更准。把它叫“升级模型”可以，但把它叫“效果更好的模型”就有点自欺欺人。

### 2.3 旧 LSTM 没真正用上骨架

旧时序数据：

```text
rows = 6659
pose_available_true_rows = 0
pose_quality_counts = {"unknown": 6659}
```

这意味着旧 LSTM 名义上有姿态字段，实际上没有有效姿态输入。它不是“bbox+motion+pose”，更像“bbox+motion+一堆姿态占位符”。因此旧 LSTM 表现不能证明骨架融合有效，也不能证明骨架融合无效。

### 2.4 原运行时参数过脆

旧配置：

```env
POSE_WORKER_FPS=2
POSE_RESULT_TTL_MS=500
POSE_MAX_FRAME_AGE_MS=500
POSE_MAX_TRACKING_FRAME_DELTA=2
```

500ms TTL 和 frame age 对 detection、tracking、pose worker、publisher 组成的异步链路太苛刻。任何环节慢一点，骨架就会过期、被丢弃，最后下游看到的是空结果。

当前推荐先使用保守 B 档：

```env
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=800
POSE_MAX_FRAME_AGE_MS=800
POSE_MAX_TRACKING_FRAME_DELTA=2
POSE_PUBLISH_MAX_FRAME_DELTA=8
POSE_INFERENCE_LOCK_WAIT_MS=160
```

C 档可以验证 tracking lag，但不能无脑上线：

```env
POSE_WORKER_FPS=3
POSE_RESULT_TTL_MS=1000
POSE_MAX_FRAME_AGE_MS=800
POSE_MAX_TRACKING_FRAME_DELTA=3
POSE_PUBLISH_MAX_FRAME_DELTA=8
POSE_INFERENCE_LOCK_WAIT_MS=160
```

`POSE_MAX_TRACKING_FRAME_DELTA=3` 会提高容忍度，也会提高错绑风险。跌倒检测一旦骨架绑错人，后面的 LSTM 和告警逻辑就是在认真处理错误对象，属于很认真地犯错。

补充说明：

```text
POSE_MAX_TRACKING_FRAME_DELTA 控制 pose worker 推理时 detection/tracking 是否同步；
POSE_PUBLISH_MAX_FRAME_DELTA 控制 publisher 是否复用仍在 TTL 内的同 track 姿态。
```

不要再用同一个 2 帧阈值同时管这两件事。25 FPS 视频里 2 帧约 80ms，而姿态 worker 只有 3 FPS 左右，这会把 `POSE_RESULT_TTL_MS=800` 架空，导致新鲜骨架在发布阶段被白白丢掉。

## 3. 总体执行顺序

### 阶段 0：冻结当前基线

目标：让后续每次优化都有可对比对象。

执行：

```powershell
python scripts\pose_runtime_baseline_report.py
```

输出：

```text
evaluations/pose_runtime_baseline_20260705.json
docs/pose_runtime_baseline_20260705.md
```

验收：

- 记录当前 `.env` 姿态参数。
- 记录当前模型路径和 hash。
- 记录旧 E2E、旧 LSTM、当前 pose-aware 数据检查结果。

### 阶段 1：先修运行时链路，不先重训

目标：确认姿态 worker 是否稳定推理，结果是否能进入 publisher 和最终实时结果。

当前已经加入或完善的诊断字段：

```text
worker_tick_count
inference_attempt_count
inference_success_count
pose_target_object_count
pose_attached_object_count
pose_valid_rate
inference_success_rate
skip_reasons
pose_quality_level
busy_by_person_detector / busy_by_fall_detector / busy_by_pose:<provider>
```

重点判断：

- `worker_tick_count` 增长但 `inference_attempt_count` 很低：worker 在空转，查 tracking、frame stale、FPS throttle。
- `inference_attempt_count` 增长但 `pose_attached_object_count` 很低：模型/provider 或绑定链路有问题。
- `skipped_due_to_busy` 高：先查推理锁、worker FPS、TTL，不要急着重训。
- `busy_by_person_detector` 或 `busy_by_fall_detector` 高：说明检测链路和姿态链路在抢同一推理资源，先做调度隔离或频率控制。
- `pose_frame_stale` 高：TTL/frame age 太短。
- `frame_tracking_desync` 高：tracking 与 detection 不同步。
- `pose_track_mismatch` 高：错绑风险，不允许直接支持告警。

已修复问题：

```text
POSE_FPS throttle 的 _last_run_at 已改为记录推理开始时间，而不是推理结束时间。
busy skip 不再刷新 _last_run_at，避免一次推理锁竞争继续触发 pose_fps_throttle。
publisher 改用 POSE_PUBLISH_MAX_FRAME_DELTA 复用 TTL 内同 track 姿态，避免 2 帧对齐窗口架空 800ms TTL。
pose 获取 Ultralytics 推理锁时使用 POSE_INFERENCE_LOCK_WAIT_MS=160 的有界等待，避免检测链路刚占锁就直接把姿态跳过。
```

意义：

以前推理耗时会被错误叠加进节流间隔，配置看似 3 FPS，实际可能被砍掉一截。这个问题很阴，表面像模型慢，实际是调度时间基准不干净。

### 阶段 2：真实服务 B 档 runtime probe

目标：证明真实 FastAPI 服务里，骨架能稳定进入 `/status` 和实时结果。

生产执行前提：

- FastAPI 服务已启动。
- 摄像头或视频源链路正常。
- 当前配置使用 B 档。

执行：

```powershell
python scripts\probe_pose_runtime_status.py --profile-name B --duration-seconds 120 --interval-seconds 2 --output evaluations\pose_runtime_profile_B_20260705.json
```

通过标准：

```text
runtime_pose_valid_rate >= 0.70
latest_result_pose_available_ratio >= 0.60
runtime_inference_success_rate 接近 1.0
skip_reasons 中没有持续增长的 pose_frame_stale、frame_tracking_desync、pose_track_mismatch、busy
```

当前状态：

```text
本机 127.0.0.1:8000/api/v1/status 未响应，真实 runtime probe 还没完成。
```

这不是模型失败，也不是优化完成。它只是说明现在还没有生产 runtime 证据。

### 阶段 3：CUDA provider A/B

目标：选择生产姿态 provider，不用 CPU/dev 结果冒充生产结论。

生产执行：

```powershell
python scripts\benchmark_pose_providers.py --providers yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx --device cuda:0 --output evaluations\pose_provider_ab_20260705.json
```

重点指标：

```text
pose_valid_rate
pose_frame_ratio
pose_object_frame_ratio
avg_latency_ms
avg_skeleton_confidence
pose_quality_counts
skip_reasons
errors
```

通过标准：

- 至少一个 provider 的 `pose_valid_rate >= 0.70`。
- `pose_frame_ratio >= 0.60`。
- 不能出现明显 `pose_track_mismatch`。
- 不能有 provider 初始化或推理错误。
- 速度要能支撑 B 档 runtime。

当前 CPU/dev 结果只能说明本机脚本链路能跑，不能说明 CUDA 生产 provider 已选定。拿 CPU smoke 当生产证据，是报告里最容易混进去的水分，必须拦住。

### 阶段 4：导出全量 pose-aware 时序数据

目标：让 LSTM 真正吃到骨架，而不是吃字段名。

生产执行：

```powershell
python scripts\export_dataset_temporal_sequences.py --dataset ur_fall --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\export_dataset_temporal_sequences.py --dataset gmdcsa24 --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
```

导出后检查：

```powershell
python scripts\check_pose_temporal_sequences.py --input-dir data\temporal_sequences_pose_v1 --output evaluations\pose_temporal_sequences_check_20260705.json
```

通过标准：

```text
pose_available_true_rows > 0
known_pose_quality_ratio >= 0.95
mismatch_available_rows = 0
pose_quality_counts 不再全是 unknown
vector_dim_errors = 0
fall/non_fall、dataset 分布可解释
```

特别注意：

`pose_track_mismatch` 不能当作可用姿态。低质量骨架最多作为弱证据或风险记录，不能给告警逻辑当硬证据。

### 阶段 5：构建 pose LSTM manifest

目标：阻止脏姿态数据进入训练。

执行：

```powershell
python scripts\build_temporal_v6_lstm_training_manifest.py --base-dir data\temporal_sequences_pose_v1 --residual-dir data\temporal_v6_training\residual_reviewed --output data\temporal_v6_training\lstm_v6_pose_training_manifest.json --model-version v6_pose --epochs 20 --stride 4 --require-pose
```

通过标准：

```text
require_pose = true
pose_training_gate.passed = true
train_command != null
```

如果 `train_command=null`，禁止训练。这个禁止不是保守，是防止把垃圾数据训练成一个更自信的垃圾模型。

补充规则：

```text
如果 residual_reviewed 还不是 pose-aware 数据，不要混入 pose LSTM manifest。
```

本轮实施已经证明，旧 residual 会把 `known_pose_quality_ratio` 从 1.0 直接打崩到 0.0319。开发冒烟可以使用 `--skip-residual`；生产训练要么重新生成 pose-aware residual，要么在首版 pose LSTM 中先排除 residual。把旧 residual 硬塞进 `--require-pose` manifest，是非常会装、也非常危险的数据污染。

### 阶段 6：bbox+motion baseline 对照 bbox+motion+pose LSTM

目标：证明姿态融合真的提高跌倒检测，而不是只是多加字段让模型看起来复杂。

必须对照：

```text
bbox+motion baseline
bbox+motion+pose candidate
```

必须看：

- fall recall
- ADL false alarm
- 事件级延迟
- 误报视频清单
- 漏报视频清单
- pose_quality_level 与错误样本之间的关系
- C 档是否引入更多 `pose_track_mismatch` 或 ADL 误报

通过条件：

姿态 LSTM 必须在不明显抬高 ADL 误报的情况下，提高跌倒召回或降低延迟。否则“融合姿态”只是给系统加复杂度，不是进步。

### 阶段 7：再决定是否重训姿态模型

只有在前面门禁通过后，才判断是否需要重训姿态模型。

需要重训的证据包括：

- runtime 链路稳定，但 `pose_quality_counts` 中 `low_quality` 仍然高。
- provider A/B 都能稳定送达，但复杂跌倒姿态 mAP 或关键点质量不足。
- pose-aware LSTM 的失败样本集中表现为关键点缺失或姿态不准，而不是 TTL、tracking、数据导出问题。
- 当前 candidate 的实际业务表现弱于 baseline，且速度收益不能弥补质量损失。

不该重训的情况：

- live `/status` 都没跑通。
- CUDA provider A/B 还没做。
- 时序数据里 `pose_available_true_rows=0`。
- `pose_track_mismatch` 还在被当成可用姿态。
- LSTM manifest 没开 `--require-pose`。

这些情况下重训，就是用训练成本掩盖工程问题。

## 4. 当前新增的两条执行线

### 4.1 生产线

用于正式验证，要求 live service、CUDA、全量数据。

先查看计划：

```powershell
python scripts\run_pose_optimization_pipeline.py --dry-run --summary evaluations\pose_optimization_pipeline_dry_run_20260705.json
```

正式执行：

```powershell
python scripts\run_pose_optimization_pipeline.py --summary evaluations\pose_optimization_pipeline_20260705.json
```

阶段顺序：

```text
production_preflight
runtime_probe
provider_ab
temporal_export_ur_fall
temporal_export_gmdcsa24
temporal_pose_check
lstm_pose_manifest
pose_lstm_train
baseline_lstm_eval
pose_lstm_eval
pose_lstm_zero_pose_eval
lstm_pose_comparison
readiness
```

`production_preflight` 会先检查硬条件：

```text
CUDA 必须可用；
live /status 必须可达并暴露 pose diagnostics；
runtime duration 必须 >= 120 秒；
LSTM eval split 必须是 test；
temporal output dir 不能带 dev/smoke/local/replay/mock；
labels 和 baseline LSTM artifacts 必须存在。
```

这一步的作用是防止把 CPU 开发机、短窗口 probe、dev-smoke 输出目录、`all` split 评估结果混进生产证据。说难听点，就是先把“看起来像生产”的假证据挡在门外。

最终门禁：

```powershell
python scripts\check_pose_optimization_readiness.py --output evaluations\pose_optimization_readiness_20260705.json
```

生产推进必须看 `production_ready=true`。`overall_ready=true` 只说明传入的这些证据文件自身过 gate；如果证据来自 CPU、replay、local、dev-smoke，它可以是开发通过，但不能进入正式 LSTM 训练和后续上线评估。

### 4.2 开发冒烟线

用于当前本机条件下检查脚本、字段、gate、文件流转是否连通。它使用 CPU 和 replay，不是生产证据。

查看计划：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode dev-smoke --dry-run --summary evaluations\pose_optimization_pipeline_dev_smoke_dry_run_20260705.json
```

实际本机冒烟：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode dev-smoke --summary evaluations\pose_optimization_pipeline_dev_smoke_20260705.json
```

阶段顺序：

```text
runtime_replay_dev_smoke
provider_ab_dev_smoke
temporal_export_ur_fall_dev_smoke
temporal_pose_check_dev_smoke
lstm_pose_manifest_dev_smoke
pose_lstm_train_dev_smoke
baseline_lstm_eval_dev_smoke
pose_lstm_eval_dev_smoke
pose_lstm_zero_pose_eval_dev_smoke
lstm_pose_comparison_dev_smoke
readiness_dev_smoke
```

dev-smoke readiness 会显式使用：

```text
--allow-cpu-provider
--allow-replay-runtime
```

并且 pipeline summary 会写：

```text
production_ready = false
```

这句话非常重要：dev-smoke 全绿，只代表本机小样本链路没断，不代表系统可以上线。

新增 LSTM train/eval/zero-pose ablation/comparison 后，dev-smoke 不再只检查“manifest 是否带姿态”，还会先训练/导出 pose LSTM，评估 baseline、pose、pose 清零消融三组结果，再生成：

```text
evaluations/baseline_lstm_eval_dev_smoke_20260705.json
evaluations/pose_lstm_eval_dev_smoke_20260705.json
evaluations/pose_lstm_zero_pose_eval_dev_smoke_20260705.json
evaluations/pose_lstm_comparison_dev_smoke_20260705.json
```

缺训练数据、pose LSTM 训练产物、baseline 模型、schema、阈值、消融指标或正式对照指标时，流水线应该停在 `pose_lstm_train*`、`baseline_lstm_eval*`、`pose_lstm_eval*`、`pose_lstm_zero_pose_eval*` 或 comparison 阶段，而不是让 readiness 最后才吐一句缺文件。这个设计很刻薄，但很实用：谁还没评估，谁就别假装已经融合成功。

dev-smoke 这里还修了两个很容易把链路弄成“假可执行”的细节：

```text
--max-frames = 360
--frame-stride = 10
```

因为 LSTM 窗口是 32，`max_frames=12` 在 stride=10 下只有两三个采样点，连一个窗口都凑不出来。那不是 smoke，是烟雾弹。

同时 dev-smoke 的 temporal export 不能照抄正式 split。`phase7_labels` 里 `fall-01` 是 train，`adl-01` 是 val；如果照抄，训练阶段只有正样本没有负样本，`train_fall_lstm.py` 会正确地拒绝训练。

实跑后又发现，完全不传 `--labels` 也不对，因为 ADL subtype 会退化成 `unknown_adl`，训练脚本会因为 hard negative 质量太差而拒绝训练。当前正确做法是：

```text
--labels data\phase7_labels\phase7_video_labels.jsonl
--split-override unassigned
```

也就是说：保留 labels 提供 subtype / event metadata，但覆盖 split，让 dev-smoke 小样本自己分组。这个口径才对；前面那种“不传 labels”的方案，属于修了一个坑又挖了另一个坑。

当前 dev-smoke 已经越过了窗口不足和 `unknown_adl` 两个问题，最新真实失败点是环境缺 `onnx`：

```text
failed_stage = pose_lstm_train_dev_smoke
error = onnx package is required to export fall_lstm ONNX models
```

现在 `train_fall_lstm.py` 已经在训练前检查这个依赖，`requirements.txt` 也补了 `onnx>=1.16` 的说明。缺这个包时应该先装依赖，不要继续调姿态模型，锅不在姿态。

dev-smoke 的 manifest 阶段会使用：

```text
--skip-residual
```

原因不是偷懒，而是旧 residual 当前不是 pose-aware。它一混进去，训练 gate 应该失败，也确实已经失败过。

## 5. 推荐的当前优先级

### P0：先跑通真实服务 runtime B 档

当前最该解决的是生产 live runtime gate 还没完成。现在已经有本机短窗口 owner 归因和 `POSE_INFERENCE_LOCK_WAIT_MS=160` 对照证据，说明 CPU 环境下 person detector / fall detector 会和 pose 抢 Ultralytics 推理锁，而有界等待能显著降低 busy。别把这说成生产通过：没有真实 CUDA 服务 120 秒 runtime 证据，后面所有“模型效果”讨论都悬在空中。

行动：

```powershell
python scripts\probe_pose_runtime_status.py --profile-name B --duration-seconds 120 --interval-seconds 2 --output evaluations\pose_runtime_profile_B_20260705.json
```

失败就看：

- 服务是否启动。
- `/api/v1/status` 路由是否正确。
- camera_id 是否匹配。
- `skip_reasons` 是否集中在 busy、stale、tracking_desync、mismatch。

### P1：在 CUDA 环境做 provider A/B

不要用 CPU/dev provider 结果选生产 provider。

行动：

```powershell
python scripts\benchmark_pose_providers.py --providers yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx --device cuda:0 --output evaluations\pose_provider_ab_20260705.json
```

### P2：全量重导 pose-aware 时序数据

旧数据没有有效骨架，继续拿旧数据训练 pose LSTM 没意义。

行动：

```powershell
python scripts\export_dataset_temporal_sequences.py --dataset ur_fall --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\export_dataset_temporal_sequences.py --dataset gmdcsa24 --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\check_pose_temporal_sequences.py --input-dir data\temporal_sequences_pose_v1 --output evaluations\pose_temporal_sequences_check_20260705.json
```

### P3：构建 manifest，再训练对照 LSTM

行动：

```powershell
python scripts\build_temporal_v6_lstm_training_manifest.py --base-dir data\temporal_sequences_pose_v1 --residual-dir data\temporal_v6_training\residual_reviewed --output data\temporal_v6_training\lstm_v6_pose_training_manifest.json --model-version v6_pose --epochs 20 --stride 4 --require-pose
```

如果 manifest gate 不过，训练停止。

### P4：根据失败样本决定是否重训姿态模型

只有当前面几步都过了，且失败样本明确指向关键点质量，才进入姿态模型重训。

## 6. 质量分级原则

当前姿态质量分级：

```text
high_confidence
valid
low_quality
pose_track_mismatch
pose_absent
```

使用规则：

- `high_confidence`：可作为强姿态证据。
- `valid`：可作为有效姿态证据。
- `low_quality`：不能单独支撑告警，只能作为弱证据或辅助特征。
- `pose_track_mismatch`：不能支撑告警，必须记录风险。
- `pose_absent`：明确没有姿态，不要和旧数据里的 `unknown` 混在一起。

一句话：有 payload 不等于有骨架，有骨架不等于能告警，骨架绑错人更不能装作没事。

## 7. 风险清单

### 风险 1：C 档提高通过率但带来错绑

`POSE_MAX_TRACKING_FRAME_DELTA=3` 可能让 tracking lag 压测通过，但也可能让姿态绑到错误对象。

处理：

- C 档只做压测和对照。
- 上线前必须看 `pose_track_mismatch` 和 ADL false alarm。
- 默认仍推荐 B 档。

### 风险 2：CPU/dev 结果被误当生产结果

当前本机没有 CUDA，dev-smoke 是必要的，但它不是生产证据。

处理：

- readiness 默认拦截 CPU provider 文件。
- readiness 默认拦截 replay runtime 文件。
- 只有显式 `--allow-cpu-provider` 和 `--allow-replay-runtime` 才允许 dev-smoke 通过 `overall_ready`。
- dev/local evidence 即使 `overall_ready=true`，也必须输出 `production_ready=false`。
- pipeline summary 明确 `production_ready=false`。

### 风险 3：旧 LSTM 结论误导判断

旧 LSTM 没吃到有效骨架，所以不能拿旧 LSTM 表现判断姿态融合价值。

处理：

- 必须重导 pose-aware 数据。
- 必须通过 pose temporal gate。
- 必须用 `--require-pose` 构建 manifest。

### 风险 4：模型重训过早

如果 runtime、provider、数据、manifest 都没过，重训姿态模型会把问题变复杂。

处理：

- 重训排在阶段 7。
- 只有失败样本明确指向关键点质量时才重训。

## 8. 工作人员执行口径

对外不要说：

```text
姿态模型已经优化完成。
```

当前应该说：

```text
姿态链路已经补充诊断、质量分级、replay 复现、pose-aware 数据 gate、LSTM manifest gate 和分阶段 pipeline。
但生产级 runtime probe、CUDA provider A/B、全量 pose-aware 数据、正式 LSTM 对照训练仍未完成。
```

最短任务清单：

1. 启动真实服务，跑 B 档 runtime probe。
2. 在 CUDA 环境跑 provider A/B。
3. 全量导出 pose-aware 时序数据并过 gate。
4. 构建 `--require-pose` LSTM manifest。
5. 训练并对照 bbox+motion baseline 与 bbox+motion+pose。
6. 只有证据指向模型关键点质量时，再重训姿态模型。

## 9. 当前已补充的计划工具

本轮新增或完善：

```text
scripts/run_pose_optimization_pipeline.py
scripts/check_pose_optimization_readiness.py
tests/test_run_pose_optimization_pipeline.py
tests/test_check_pose_optimization_readiness.py
evaluations/pose_optimization_pipeline_dev_smoke_dry_run_20260705.json
```

验证结果：

```text
python -m pytest tests\test_run_pose_optimization_pipeline.py tests\test_check_pose_optimization_readiness.py
8 passed
```

dev-smoke dry-run 结果：

```text
mode = dev-smoke
status = dry_run
stage_count = 11
production_ready = false
```

这份计划的核心不是“做更多实验”，而是“每一步实验都必须能回答一个具体问题”。现在系统最需要的不是漂亮说法，而是把骨架证据从模型输出一路押送到下游训练和告警逻辑，中途谁丢、谁错绑、谁过期，就把谁揪出来。

## 10. 最新计划修订：stale 已经细分，不要再把锅糊成一团

本轮继续把 `pose_frame_stale` 拆开了。之前报告只能说“姿态帧过期”，这个诊断太粗，粗到有点偷懒：同样叫 stale，可能是短视频 EOF，可能是摄像头断流，可能是采集帧本身老了，也可能是 detection 快照没有及时进入 pose worker。现在 worker 会按来源记录：

```text
pose_frame_stale_source_eof
pose_frame_stale_capture_disconnected
pose_frame_stale_capture_stale
pose_frame_stale_detection_lag
pose_frame_stale
pose_frame_stale_duplicate
```

gate 规则也同步调整：

- `pose_frame_stale_source_eof`：解释性诊断，主要用于本地短视频 probe，不直接当作 runtime blocker。
- `pose_frame_stale_duplicate`：同一帧重复噪声，不直接当作 runtime blocker。
- `pose_frame_stale_detection_lag`、`pose_frame_stale_capture_stale`、`pose_frame_stale_capture_disconnected`、旧的 `pose_frame_stale`：继续作为 blocker。

这次 GMDC 本地短窗口有效样本重算后：

```text
runtime_pose_valid_rate = 1.0
runtime_inference_success_rate = 1.0
latest_result_pose_available_ratio = 0.6667
skip_reason_delta = {
  "pose_fps_throttle": 6,
  "pose_frame_stale_detection_lag": 2,
  "pose_frame_stale_duplicate": 7,
  "pose_frame_stale_source_eof": 1
}
gate.blockers = ["pose_frame_stale_detection_lag"]
production_ready = false
```

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_stale_classified_wait160_resummarized_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_stale_classified_wait160_resummarized_20260705.json
```

这说明当前问题已经从“姿态链路一团糟”收敛到更具体的运行时问题：`busy` 不是这次短窗口的主 blocker，`frame_tracking_desync` 已被 detection history 清掉，剩下需要盯住的是 detection 快照生产/消费延迟。下一步不要急着调大 `POSE_MAX_FRAME_AGE_MS`，那是把温度计掰弯；应该先查 detection interval、detector 推理耗时、tracking 更新节奏、pose worker tick 时机，以及本地视频 probe 是否因为源太短导致采样窗口偏到 EOF 后。

同时，`probe_pose_runtime_status.py` 已经给比例做了上限保护，并在出现异步计数口径错位时写入：

```text
counter_consistency_warnings
```

这不是模型问题，是监控采样口径问题。工作人员看见 `pose_attached_delta_exceeds_target_delta` 或 `inference_success_delta_exceeds_attempt_delta` 时，不要拿那个原始比例吹效果，也不要拿它骂模型；先承认 `/status` 计数器是异步采样，短窗口首尾差分会有竞态。

## 11. 最新实施修订：detection_lag 的锅已经找到一半

继续往下查以后，`pose_frame_stale_detection_lag` 的来源更清楚了。`DetectionService` 原来的顺序是：

```text
person detector
fall hint detector
update_detection(person result)
```

这很别扭。person detection 明明已经算完了，却要等 fall hint 也跑完才写入 `RealtimeResultStore`。在 CPU 上，fall hint 一慢，tracking 和 pose 只能继续吃旧 detection。说难听点，这不是姿态模型在装死，是上游把新鲜人框攥在手里不发。

现在已经改成：

```text
person detector
update_detection(person result)
fall hint detector
update_fall_detection(fall hint result)
```

也就是说，人框先进入下游，fall hint 继续异步意义上的“后补”。这不会让 fall hint 消失，只是不再让 fall hint 把 person detection 的新快照堵在门口。

新增测试：

```text
tests/test_detection_service.py
  test_person_detection_is_published_before_fall_hint_runs
```

本轮长视频 CPU 对照：

```text
源视频：
datasets/new_pose_imports/manual_fall_20260625/session_20260625_000003_fall_candidate_ec4c9594a3fee498abcee80566372029/video.mp4
时长约 122.97s
```

对照 1：person detection 提前发布，但保持 `FALL_DETECTOR_INTERVAL_MS=200`、`POSE_MAX_FRAME_AGE_MS=800`

```text
evaluations/pose_runtime_profile_B_local_service_longvideo_cpu_detection_publish_first_wait160_20260705.json

runtime_pose_valid_rate = 0.875
latest_result_pose_available_ratio = 1.0
skipped_due_to_busy = 0
skip_reason_delta = {
  "pose_fps_throttle": 13,
  "pose_frame_stale_detection_lag": 4
}
gate = failed
```

解释：person detection 提前发布是必要修复，但 CPU 上检测供给频率仍只有约 1.35 FPS，`latest_detection_age_ms` 会冲到 891/969ms，800ms frame-age 还是会被打穿。

对照 2：`FALL_DETECTOR_INTERVAL_MS=800`，仍保持 `POSE_MAX_FRAME_AGE_MS=800`

```text
evaluations/pose_runtime_profile_B_local_service_longvideo_cpu_detection_publish_first_fall800_wait160_20260705.json

runtime_pose_valid_rate = 0.8636
latest_result_pose_available_ratio = 1.0
skipped_due_to_busy = 1
skip_reason_delta = {
  "busy": 1,
  "busy_by_person_detector": 1,
  "pose_fps_throttle": 13,
  "pose_frame_stale_detection_lag": 2
}
gate = failed
```

解释：fall hint 降频能缓解 detection lag，但不能完全解决。CPU 上 person detector 自己也会抢 Ultralytics 推理锁，`busy_by_person_detector` 重新冒头。系统不是一个按钮坏了，是几个串行模型在一条窄路上互相挤。

对照 3：CPU/dev 保守档，`FALL_DETECTOR_INTERVAL_MS=800`、`POSE_MAX_FRAME_AGE_MS=1000`、`POSE_RESULT_TTL_MS=1000`

```text
evaluations/pose_runtime_profile_Bcpu_local_service_longvideo_cpu_detection_publish_first_fall800_age1000_wait160_20260705.json

runtime_pose_valid_rate = 0.7917
runtime_inference_success_rate = 1.0
latest_result_pose_available_ratio = 1.0
skip_reason_delta = {
  "busy": 2,
  "busy_by_person_detector": 2,
  "pose_fps_throttle": 15
}
gate = passed
```

readiness：

```text
evaluations/pose_optimization_readiness_local_service_Bcpu_longvideo_cpu_detection_publish_first_fall800_age1000_wait160_20260705.json

overall_ready = false
production_ready = false
evidence_scope = development
failed_gates = ["lstm_comparison"]
blocking_reasons.lstm_comparison = ["pose_lstm_comparison_missing"]
non_production_reasons:
  runtime_probe_duration_below_120s
  runtime_probe_ok_samples_below_30
  provider_ab_device_is_not_cuda
```

这组结果的正确解释是：

```text
CPU/dev 可以用 Bcpu 保守档继续推进链路验证；
但它不是生产结论；
没有 LSTM 对照报告时，也不是 readiness 整体通过。
```

Bcpu 建议参数：

```env
DETECTION_INTERVAL_MS=200
FALL_DETECTOR_INTERVAL_MS=800
POSE_WORKER_FPS=3
POSE_SKIP_WHEN_INFERENCE_BUSY=true
POSE_INFERENCE_LOCK_WAIT_MS=160
POSE_MAX_FRAME_AGE_MS=1000
POSE_RESULT_TTL_MS=1000
POSE_PUBLISH_MAX_FRAME_DELTA=8
POSE_MAX_TRACKING_FRAME_DELTA=2
```

生产 CUDA 仍然要跑正式 B 档，不要偷懒把 CPU/dev 参数直接说成上线参数。CUDA 如果能把 detection FPS 拉上去，`POSE_MAX_FRAME_AGE_MS=800` 可能仍然够；如果 CUDA 仍有 `pose_frame_stale_detection_lag`，再做 `FALL_DETECTOR_INTERVAL_MS` 和 `POSE_MAX_FRAME_AGE_MS` 的生产 A/B。没有 120 秒真实服务证据前，谁宣布“姿态链路完成”，谁就是在给后面埋雷。

## 12. 可执行入口：Bcpu 不再靠手抄环境变量

为了避免工作人员靠记忆拼参数，本轮把 runtime profile 环境变量固化成脚本：

```powershell
python scripts\pose_runtime_profile_env.py --profile Bcpu --format powershell --output evaluations\pose_runtime_profile_Bcpu_env_20260705.ps1
```

已生成：

```text
evaluations/pose_runtime_profile_Bcpu_env_20260705.ps1
```

内容核心是：

```powershell
$env:DETECTION_INTERVAL_MS='200'
$env:FALL_DETECTOR_INTERVAL_MS='800'
$env:POSE_WORKER_FPS='3'
$env:POSE_SKIP_WHEN_INFERENCE_BUSY='true'
$env:POSE_INFERENCE_LOCK_WAIT_MS='160'
$env:POSE_RESULT_TTL_MS='1000'
$env:POSE_PUBLISH_MAX_FRAME_DELTA='8'
$env:POSE_MAX_FRAME_AGE_MS='1000'
$env:POSE_MAX_TRACKING_FRAME_DELTA='2'
```

同时 `run_pose_optimization_pipeline.py` 增加了 `dev-live` 模式。它不会启动服务，只负责在服务已经按 Bcpu 环境启动后采样 `/status` 并跑 readiness：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode dev-live --profile-name Bcpu --base-url http://127.0.0.1:8010 --duration-seconds 12 --interval-seconds 1 --dry-run --summary evaluations\pose_optimization_pipeline_dev_live_bcpu_dry_run_20260705.json
```

dry-run 结果：

```text
mode = dev-live
stage_count = 2
production_ready = false
```

这套入口的边界很重要：

```text
dev-live = 本地真实 FastAPI 服务验证
dev-smoke = replay/小样本冒烟
production = CUDA + 真实服务 + 全量数据
```

`dev-live` 不允许 `--allow-replay-runtime`，因为它看的应该是真服务 `/status`，不是 replay。它允许 CPU provider 证据，只是为了本地联调能继续走完 readiness；它永远不应该被包装成生产通过。

## 13. 防误用补丁：Bcpu 即使跑满 120 秒也不是生产档

本轮又补了一层门禁：`check_pose_optimization_readiness.py` 现在会识别 runtime profile 名称或文件名里的 `Bcpu`。只要是 Bcpu，就会写入：

```text
runtime_profile_is_bcpu_dev_profile
```

这条规则很重要，因为否则有人可能把 Bcpu 的结果文件改成一个看起来很正式的名字，再配上 120 秒采样，就把 CPU/dev 保守档冒充成生产通过。现在这条路被堵住了。

复算当前 Bcpu readiness。注意：新增 `lstm_comparison` 门禁后，这份 readiness 不再是整体通过；它现在正确地暴露出“还没有 LSTM 对照报告”的缺口。

```text
evaluations/pose_optimization_readiness_local_service_Bcpu_longvideo_cpu_detection_publish_first_fall800_age1000_wait160_20260705.json

overall_ready = false
production_ready = false
failed_gates = ["lstm_comparison"]
blocking_reasons.lstm_comparison = ["pose_lstm_comparison_missing"]
non_production_reasons.runtime includes:
  runtime_profile_looks_like_dev_or_local_evidence
  runtime_profile_is_bcpu_dev_profile
  runtime_probe_duration_below_120s
  runtime_probe_ok_samples_below_30
```

后续口径：

```text
Bcpu 通过 = 本地 CPU/dev 链路可以继续推进
Bcpu 通过 != 生产姿态链路完成
Bcpu runtime 通过 != readiness 整体通过
```

这不是吹毛求疵，这是防止把工程调参的权宜之计包装成上线结论。那种包装短期看起来省事，长期就是事故预制菜。

## 14. 防误判补丁：pose LSTM 必须赢过 baseline 和姿态清零消融

本轮又把 `lstm_comparison` 加进 readiness gate，并进一步加入 zero-pose ablation。以前只要求有 pose LSTM manifest，这还不够；manifest 只能证明“准备训练了一个带姿态字段的模型”，不能证明这个模型真的比 `bbox+motion` baseline 更好，更不能证明它真的用了姿态特征。

现在 `check_pose_optimization_readiness.py` 会读取：

```text
evaluations/pose_lstm_comparison_20260705.json
```

并强制检查：

```text
pose_lstm.f1 > baseline_lstm.f1
pose_lstm.false_positive_count <= baseline_lstm.false_positive_count
pose_lstm.f1 > pose_lstm_zero_pose_ablation.f1
pose_lstm.false_positive_count <= pose_lstm_zero_pose_ablation.false_positive_count
comparison.passed != false
```

如果 pose LSTM 没有超过 baseline，或者没有超过姿态清零消融，会直接出现 blocker：

```text
pose_lstm_not_better_than_baseline_f1
pose_lstm_not_better_than_zero_pose_ablation
```

如果比较报告来自 dev/smoke/local 文件名，即使比较本身通过，也只能算开发证据，不能算生产证据：

```text
lstm_comparison_looks_like_dev_or_smoke_evidence
```

这条门禁的意义很直接：不要拿“我把骨架接进 LSTM 了”冒充“骨架提升了跌倒检测”。前者只是工程动作，后者才是结果。姿态融合如果没有赢过 baseline，或者没有赢过把姿态列清零的自己，那就是给系统加复杂度，不是优化。

为了避免工作人员手写 JSON，本轮新增了标准生成入口：

```powershell
python scripts\build_pose_lstm_comparison.py `
  --baseline-metrics evaluations\baseline_lstm_eval.json `
  --pose-metrics evaluations\pose_lstm_eval.json `
  --pose-ablation-metrics evaluations\pose_lstm_zero_pose_eval.json `
  --output evaluations\pose_lstm_comparison_20260705.json
```

这个脚本可以从常见评估结果里抽取或计算：

```text
precision
recall
f1
false_positive_count
confusion
```

支持的输入形态包括 `event_metrics.confusion`、`v6_event_metrics.confusion`，也支持直接给 `f1` / `false_positive_count`。它只做汇总和判定，不训练模型；也就是说，它不会替你把烂模型说成好模型。

现在这个入口也已经接入 `run_pose_optimization_pipeline.py`：

```text
production stages:
  production_preflight
  runtime_probe
  provider_ab
  temporal_export_ur_fall
  temporal_export_gmdcsa24
  temporal_pose_check
  lstm_pose_manifest
  pose_lstm_train
  baseline_lstm_eval
  pose_lstm_eval
  pose_lstm_zero_pose_eval
  lstm_pose_comparison
  readiness

dev-smoke stages:
  runtime_replay_dev_smoke
  provider_ab_dev_smoke
  temporal_export_ur_fall_dev_smoke
  temporal_pose_check_dev_smoke
  lstm_pose_manifest_dev_smoke
  pose_lstm_train_dev_smoke
  baseline_lstm_eval_dev_smoke
  pose_lstm_eval_dev_smoke
  pose_lstm_zero_pose_eval_dev_smoke
  lstm_pose_comparison_dev_smoke
  readiness_dev_smoke
```

production 默认评估并写出：

```text
evaluations/baseline_lstm_eval_20260705.json
evaluations/pose_lstm_eval_20260705.json
evaluations/pose_lstm_zero_pose_eval_20260705.json
```

dev-smoke 默认评估并写出：

```text
evaluations/baseline_lstm_eval_dev_smoke_20260705.json
evaluations/pose_lstm_eval_dev_smoke_20260705.json
evaluations/pose_lstm_zero_pose_eval_dev_smoke_20260705.json
```

没有训练数据、pose LSTM 产物、baseline 模型、schema、阈值或可评估窗口，流水线会在 `pose_lstm_train*`、`baseline_lstm_eval*`、`pose_lstm_eval*` 或 `pose_lstm_zero_pose_eval*` 阶段失败；有指标但 pose LSTM 没赢 baseline 或没赢姿态清零消融，才会在 `lstm_pose_comparison*` 阶段失败。这个失败比 readiness 末尾才发现缺文件更好，因为它清楚告诉工作人员：现在不是姿态 runtime 的锅，是 LSTM 对照证据根本还没交。

新增覆盖：

```text
tests/test_build_pose_lstm_comparison.py
tests/test_evaluate_fall_lstm_metrics.py
test_lstm_comparison_blocks_when_pose_lstm_does_not_beat_baseline
```

验证：

```text
python -m pytest tests\test_check_pose_optimization_readiness.py tests\test_run_pose_optimization_pipeline.py
13 passed

python -m pytest tests\test_build_pose_lstm_comparison.py tests\test_run_pose_optimization_pipeline.py tests\test_pose_runtime_profile_env.py tests\test_check_pose_optimization_readiness.py tests\test_replay_pose_runtime_profiles.py tests\test_temporal_v6_lstm_training_manifest.py tests\test_check_pose_temporal_sequences.py tests\test_target_feature_extractor.py tests\test_export_dataset_temporal_sequences.py tests\test_temporal_service.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_realtime_result_store.py tests\test_result_publisher_service.py tests\test_fall_feature_builder.py tests\test_detection_service.py tests\test_tracking_worker_service.py tests\test_end_to_end_pipeline.py
103 passed, 4 warnings
```

后续口径也要同步改：

```text
pose-aware manifest 通过 != pose LSTM 有收益
pose LSTM 比 baseline 和姿态清零消融都更好 + 不增加误报，才有资格进入生产评估
```
