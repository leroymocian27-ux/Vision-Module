# 姿态检测优化计划实施状态（2026-07-05）

## 1. 当前结论

本轮已经把计划从“文档建议”推进到“可执行门禁 + 本机实跑证据”。

结论很明确：

```text
dev-smoke 的 runtime/provider/pose-aware export/manifest/LSTM train/eval/zero-pose ablation/comparison/readiness 已完整执行到结论；
pose LSTM 已能训练并导出 ONNX，ONNX 校验通过，但小样本对照里只追平 baseline，也只追平姿态清零消融，没有证明姿态特征真的有用；
真实服务 CPU 短窗口 runtime 已证明 wait160 能缓解 busy，但带元数据复跑仍暴露 stale/desync；
生产 CUDA 120 秒 runtime、CUDA provider A/B、全量 pose-aware 数据、正式 LSTM 对照仍未完成；
当前最该继续打的是生产 runtime 验证和 CUDA provider/data/LSTM 闭环，不是立刻重训姿态模型。
```

更直白一点：骨架不是完全算不出来，甚至在小样本和局部服务链路里能算出来；问题是它在真实运行时很容易被 busy、tracking desync、publisher 可见性这些东西磨没。这个系统现在最缺的不是口号，是让骨架活着走到下游。

最新一次 dev-smoke 已经不再卡在“没装 ONNX、没训练产物”这种低级问题上。`onnx>=1.16` 已补齐，`models/fall_lstm_v6_pose_dev_smoke.onnx` 已导出，训练脚本的 ONNX 验证通过。并且 `train_fall_lstm.py` 已从硬编码 `0.65` 改为训练后生成阈值校准文件；dev-smoke 当前阈值校准因为没有 val 窗口，只能标记为 `scope=train`，不能当生产阈值。校准后对照结果如下：

```text
baseline bbox+motion LSTM:
precision = 0.6
recall = 1.0
f1 = 0.75
false_positive_count = 2

pose-aware bbox+motion+pose LSTM:
threshold = 0.5
precision = 0.6
recall = 1.0
f1 = 0.75
false_positive_count = 2

pose LSTM with pose features zeroed:
threshold = 0.5
precision = 0.6
recall = 1.0
f1 = 0.75
false_positive_count = 2

comparison:
passed = false
blockers = pose_lstm_not_better_than_baseline_f1,
           pose_lstm_not_better_than_zero_pose_ablation
f1_delta = 0.0
zero_pose_ablation_f1_delta = 0.0
```

这不是生产结论，样本也小得可怜；但它已经足够说明一件事：现在不能把“姿态字段已经进 LSTM”当成“姿态融合有效”。当前 pose LSTM 在 dev-smoke 里只是追平 baseline，没有带来 F1 提升，也没有减少误报；更难听的是，把姿态列清零以后结果也一模一样。换句话说，姿态特征已经坐上车了，但它可能只是坐在后排发呆。这种模型绝对不能上线。

最新 readiness 总账：

```text
overall_ready = false
production_ready = false
passed_gates = runtime, provider, temporal_data, lstm_manifest
failed_gates = lstm_comparison
blocking_reasons = pose_lstm_not_better_than_baseline_f1,
                   pose_lstm_not_better_than_zero_pose_ablation,
                   lstm_comparison_report_failed
```

证据文件：

```text
evaluations/pose_production_preflight_20260705.json
evaluations/pose_optimization_pipeline_20260705.json
evaluations/pose_optimization_pipeline_dev_smoke_20260705.json
evaluations/pose_optimization_readiness_dev_smoke_20260705.json
evaluations/baseline_lstm_eval_dev_smoke_20260705.json
evaluations/pose_lstm_eval_dev_smoke_20260705.json
evaluations/pose_lstm_zero_pose_eval_dev_smoke_20260705.json
evaluations/pose_lstm_comparison_dev_smoke_20260705.json
models/fall_lstm_v6_pose_dev_smoke.onnx
```

生产 preflight 已经接入 production pipeline 第一阶段。当前本机实跑结果是失败：

```text
passed = false
production_parameters.passed = true
duration_seconds = 120
temporal_output_dir = data\temporal_sequences_pose_v1
lstm_eval_split = test
pipeline_status = error
failed_stage = production_preflight
completed_stage_count = 1
blockers = cuda_unavailable, live_status_unreachable
next_action = run production gates on a CUDA-capable host; CPU evidence is development-only
```

这不是坏消息，这是终于把“当前机器不是生产姿态优化环境”写成机器可读的硬门。preflight 现在还会拦截短 runtime、`all/train/val` 评估 split、`dev/smoke/local/replay/mock` 输出路径，防止开发证据混进生产报告。以前这种问题容易拖到 provider A/B 或 runtime probe 里炸，现在第一步就拦住，比较省命。

本轮新增修复后，本地服务 B 档 CPU probe 从：

```text
runtime_pose_valid_rate = 0.6
latest_result_pose_available_ratio = 0.2857
blockers = pose_valid_rate_below_0.70, busy_skip_too_high, pose_frame_stale, frame_tracking_desync
```

改善到：

```text
runtime_pose_valid_rate = 0.8
latest_result_pose_available_ratio = 0.6364
blockers = busy_skip_too_high, frame_tracking_desync
```

再通过 `POSE_INFERENCE_LOCK_WAIT_MS=160` 的有界等待改善到：

```text
runtime_pose_valid_rate = 1.0
latest_result_pose_available_ratio = 0.6667
skipped_due_to_busy = 0
blockers = []
```

这不是生产通过，但它说明方向是对的：先修链路，比盲目重训模型有效得多。

## 2. 本轮已实施内容

### 2.1 dev-smoke 基础链路已可执行

命令：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode dev-smoke --summary evaluations\pose_optimization_pipeline_dev_smoke_20260705.json
```

历史结果（新增 LSTM comparison 门禁前）：

```text
mode = dev-smoke
status = ok
stage_count = 6
completed_stage_count = 6
production_ready = false
```

证据文件：

```text
evaluations/pose_optimization_pipeline_dev_smoke_20260705.json
```

阶段：

```text
runtime_replay_dev_smoke
provider_ab_dev_smoke
temporal_export_ur_fall_dev_smoke
temporal_pose_check_dev_smoke
lstm_pose_manifest_dev_smoke
readiness_dev_smoke
```

当前 pipeline 已新增 LSTM train/eval/zero-pose ablation/comparison，所以当前 dev-smoke 阶段变成：

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

当前实跑摘要：

```text
mode = dev-smoke
status = error
stage_count = 11
completed_stage_count = 11
failed_stage = lstm_pose_comparison_dev_smoke
production_ready = false
```

注意：这只是本机 CPU 小样本冒烟，不是生产验证。它证明脚本、字段、gate、文件流转没有断，并且证明 LSTM 对照门禁能把烂结果拦下来；不证明线上姿态已经稳定，更不证明 pose LSTM 已经可用。当前完整 dev-smoke 的失败是正确失败：pose LSTM 既没打过 bbox+motion baseline，也没打过姿态清零消融。

这轮还修了 dev-smoke 的两个执行性问题：

```text
dev_temporal_max_frames = 360
frame_stride = 4
```

旧的 12 帧上限在 stride=10 下连 32 帧 LSTM 窗口都凑不出来，后面的训练阶段会直接变成摆设。现在至少能形成一个窗口，不再是假冒烟。

另外 dev-smoke temporal export 不能照抄正式 split。`phase7_labels` 里 `fall-01` 是 train、`adl-01` 是 val，照抄正式 split 会让训练集只有正样本没有负样本；但也不能完全不传 `--labels`，否则 ADL subtype 会退化成 `unknown_adl`，训练脚本会因为 hard negative 质量太差而拒绝训练。最终策略是：

```text
保留 --labels，用它提供 non_fall_subtype / event metadata
同时增加 --split-override unassigned，禁止 dev-smoke 继承正式 train/val split
```

当前 dev-smoke temporal export 命令核心参数：

```text
--labels data\phase7_labels\phase7_video_labels.jsonl
--split-override unassigned
--frame-stride 4
--max-frames 360
```

这次实跑已经越过了窗口不足和 `unknown_adl` 两个坑，新的失败点变成环境依赖：

```text
failed_stage = pose_lstm_train_dev_smoke
error = onnx package is required to export fall_lstm ONNX models
```

该依赖问题已经处理：本机已安装 `onnx>=1.16`，`train_fall_lstm.py` 也已修复为训练前检查 ONNX 导出依赖，不会训练完才从 PyTorch 内部甩出一大段栈。`requirements.txt` 已补充：

```text
# onnx>=1.16
```

安装依赖后再次实跑，训练和导出通过，真正的失败点变成 LSTM 对照：

```text
failed_stage = lstm_pose_comparison_dev_smoke
baseline_lstm.f1 = 0.75
pose_lstm.threshold = 0.5
pose_lstm.f1 = 0.75
zero_pose_ablation.f1 = 0.75
blockers = pose_lstm_not_better_than_baseline_f1,
           pose_lstm_not_better_than_zero_pose_ablation
```

这才是有价值的失败。它说明现在 pipeline 已经能把“姿态字段进了模型，但模型没有变好，甚至清零姿态也没变化”这种问题抓出来，而不是继续靠感觉上线。

### 2.2 修复 dev-smoke manifest 混入旧 residual 的问题

第一次实际运行 dev-smoke 时，失败在：

```text
lstm_pose_manifest_dev_smoke
```

失败原因：

```text
base pose-aware 小样本只有 3 行；
但 manifest 又混入 data/temporal_v6_training/residual_reviewed 里的旧数据；
旧 residual 没有 pose_quality_level，导致 91 行 unknown；
known_pose_quality_ratio 从 1.0 被打到 0.0319。
```

这不是坏事，说明 `--require-pose` gate 在认真拦脏数据。真正的问题是 dev-smoke runner 不该混旧 residual。

已修复：

```text
scripts/build_temporal_v6_lstm_training_manifest.py 增加 --skip-residual
scripts/run_pose_optimization_pipeline.py 的 dev-smoke manifest 阶段使用 --skip-residual
```

新增测试覆盖：

```text
tests/test_temporal_v6_lstm_training_manifest.py
tests/test_run_pose_optimization_pipeline.py
```

修复后 manifest：

```text
include_residual = false
base_input_count = 2
residual_input_count = 0
trainable_input_count = 2
pose_training_gate.passed = true
pose_available_true_ratio = 1.0
known_pose_quality_ratio = 1.0
train_command != null
```

证据文件：

```text
data/temporal_v6_training/lstm_v6_pose_dev_smoke_training_manifest.json
```

### 2.3 本机 CPU provider 小样本通过

dev-smoke provider 结果：

```text
yolo11_legacy:
  pose_valid_rate = 1.0
  pose_frame_ratio = 0.9
  avg_latency_ms ≈ 191.62
  pose_quality_counts = {"high_confidence": 9}

yolo:
  pose_valid_rate = 1.0
  pose_frame_ratio = 0.9
  avg_latency_ms ≈ 80.69
  pose_quality_counts = {"high_confidence": 9}
```

证据文件：

```text
evaluations/pose_provider_ab_dev_smoke_20260705.json
```

解释：

CPU 小样本里 `yolo` 明显更快，但这不能替代 CUDA provider A/B。当前证据只能说明 provider 小链路能跑，不能说明生产该选谁。

### 2.4 本机 pose-aware temporal 小样本通过

结果：

```text
rows = 3
pose_available_true_rows = 3
pose_available_true_ratio = 1.0
known_pose_quality_ratio = 1.0
mismatch_available_rows = 0
pose_quality_counts = {"high_confidence": 3}
```

证据文件：

```text
evaluations/pose_temporal_sequences_check_dev_smoke_20260705.json
data/temporal_sequences_pose_dev_smoke
```

解释：

这证明新导出的 pose-aware 字段能进入时序数据，并且能被 gate 正确认出来。它不证明全量数据已经合格，因为这里只是 2 个 UR Fall 视频的小样本。

### 2.5 修复 busy 跳过污染 FPS 节流窗口

发现问题：

```text
PoseService.enrich() 在拿不到 ultralytics 推理锁时，会记录 busy；
但旧逻辑同时刷新 _last_run_at；
下一次 tick 会被 pose_fps_throttle 挡住。
```

这等于“没推理也被当成刚推理过”，非常不讲道理。在线上表现就是：

```text
busy skip 后继续 throttle；
姿态 worker tick 在跑；
但真正 inference attempt 上不去。
```

已修复：

```text
busy 分支不再刷新 _last_run_at。
```

新增测试：

```text
tests/test_pose_service.py::PoseServiceDiagnosticsTest::test_busy_skip_does_not_refresh_pose_fps_throttle_window
```

### 2.6 修复 publisher 发布窗口过窄问题

发现问题：

```text
POSE_RESULT_TTL_MS = 800
POSE_MAX_TRACKING_FRAME_DELTA = 2
```

姿态推理约 3 FPS，而视频常见 25 FPS。2 帧只约等于 80ms。结果就是：

```text
姿态结果明明还在 800ms TTL 内，
但发布阶段因为 frame delta > 2 不合并，
TTL 被过窄的帧差规则架空。
```

已修复：

```text
新增 POSE_PUBLISH_MAX_FRAME_DELTA=8
publisher 合并 pose 时使用 POSE_PUBLISH_MAX_FRAME_DELTA
pose worker 推理阶段仍使用 POSE_MAX_TRACKING_FRAME_DELTA=2
```

这个拆分很重要：

```text
算姿态时仍保守，避免 detection/tracking 错位；
发布复用时在同一 track_id 上放宽，避免新鲜骨架被白白丢掉。
```

新增测试：

```text
tests/test_result_publisher_service.py::ResultPublisherServiceTest::test_build_result_reuses_fresh_pose_with_publish_delta_window
```

配置已更新：

```text
.env
.env.example
app/core/config.py
```

## 3. 真实服务 runtime 尝试结果

### 3.1 直接探测 8000：服务未启动

命令：

```powershell
python scripts\probe_pose_runtime_status.py --profile-name B_local_check --duration-seconds 5 --interval-seconds 1 --output evaluations\pose_runtime_profile_B_local_check_20260705.json
```

结果：

```text
ok_samples = 0
error = WinError 10061 connection refused
```

证据文件：

```text
evaluations/pose_runtime_profile_B_local_check_20260705.json
```

### 3.2 临时启动真实 FastAPI 服务：RTSP 配置不可用

`.env` 当前包含：

```env
DEFAULT_RTSP_URL=rtsp://admin:***@192.168.8.254:10554/tcp/av0_0
MOCK_CAMERA_ENABLED=false
CAPTURE_BACKEND=subprocess_opencv
ENABLE_POSE=true
```

首次临时服务启动后，capture 子进程反复失败：

```text
first frame timeout
stream closed
```

随后 runtime probe 结果是：

```text
worker_tick_count 增长
inference_attempt_count = 0
skip_reason_delta = {"no_tracking": 36}
```

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_cpu_20260705.json
```

解释：

服务起来了，但没有有效视频帧和 tracking，姿态 worker 只能空转。这个结果不能证明模型差，只能证明输入流没打通。

### 3.3 mock camera 不适合姿态 runtime gate

将服务切为 mock/opencv 后，capture 不再报错，但 mock 画面只是矩形，不是真人：

```text
skip_reason_delta = {"no_tracking": 61}
runtime_pose_valid_rate = 0.0
```

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_mock_cpu_20260705.json
```

解释：

mock camera 能测服务活着，不能测姿态能力。拿它当姿态 runtime gate 是自我安慰。

### 3.4 本地视频真实服务 CPU probe：能出姿态，但 runtime gate 未过

临时服务使用本地视频：

```text
datasets/ur_fall/videos/adl-30.mp4
```

命令输出文件：

```text
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_20260705.json
```

修复前核心结果：

```text
ok_samples = 14
pose_provider = yolo11_legacy
worker_tick_count delta = 36
inference_attempt_count delta = 5
inference_success_count delta = 5
pose_target_object_count delta = 5
pose_attached_object_count delta = 3
skipped_due_to_busy delta = 8
runtime_pose_valid_rate = 0.6
runtime_inference_success_rate = 1.0
latest_result_pose_available_ratio = 0.2857
```

失败原因：

```text
busy = 8
pose_fps_throttle = 7
no_tracking = 14
no_pose_attached = 2
pose_frame_stale = 1
frame_tracking_desync = 1
```

门禁结果：

```text
gate.passed = false
blockers = [
  "pose_valid_rate_below_0.70",
  "busy_skip_too_high",
  "pose_frame_stale",
  "frame_tracking_desync"
]
```

解释：

这份证据很关键。它说明真实服务链路不是完全不能产生姿态：

```text
inference_success_rate = 1.0
pose_attached_object_count = 3
```

但它也说明当前 B 档在 CPU 服务环境下不稳定：

```text
姿态算出来了一部分；
但送到最终结果的比例太低；
busy、节流、stale、tracking desync 都在发生。
```

这正好支持当前计划的判断：优先修 runtime 稳定送达，再谈重训。

### 3.5 修复后本地视频真实服务 CPU probe

修复内容：

```text
busy 不刷新 _last_run_at
POSE_PUBLISH_MAX_FRAME_DELTA=8
```

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_publish_delta_20260705.json
```

结果：

```text
worker_tick_count delta = 30
inference_attempt_count delta = 10
inference_success_count delta = 10
pose_target_object_count delta = 10
pose_attached_object_count delta = 8
skipped_due_to_busy delta = 3
runtime_pose_valid_rate = 0.8
runtime_inference_success_rate = 1.0
latest_result_pose_available_ratio = 0.6364
```

剩余 blocker：

```text
busy_skip_too_high
frame_tracking_desync
```

对比修复前：

```text
runtime_pose_valid_rate: 0.6 -> 0.8
latest_result_pose_available_ratio: 0.2857 -> 0.6364
pose_frame_stale: 有 -> 无
```

这说明发布窗口和 busy/throttle 修复是有效的。它没有把 CPU 本地服务变成生产合格，但已经把问题从“骨架经常送不到下游”收敛到“推理锁竞争和偶发 tracking desync”。

### 3.6 已验证但不推荐的对照

#### yolo provider 对照

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_yolo_provider_20260705.json
```

结果：

```text
runtime_pose_valid_rate = 1.0
latest_result_pose_available_ratio = 0.5455
busy = 9
```

结论：

本地 CPU 下切 `POSE_PROVIDER=yolo` 没有解决运行时锁竞争，可见骨架比例反而低于修复后的 `yolo11_legacy`。不能据此切生产 provider。

#### 阻塞等待推理锁对照

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_blocking_pose_20260705.json
```

结果：

```text
busy = 0
pose_frame_stale = 3
latest_result_pose_available_ratio = 0.4545
```

结论：

`POSE_SKIP_WHEN_INFERENCE_BUSY=false` 会把 busy 变成 stale。它不是免费午餐，只是换一种坏法。

#### C 档 delta=3 对照

证据文件：

```text
evaluations/pose_runtime_profile_C_local_service_adl30_cpu_delta3_20260705.json
```

结果：

```text
runtime_pose_valid_rate = 1.0
latest_result_pose_available_ratio = 0.4545
busy = 10
frame_tracking_desync = 2
```

结论：

本地 CPU 下 C 档没有解决 desync，还让可见比例下降。C 档仍只能作为压测选项，不能无脑上线。

## 4. local-service readiness 结果

命令：

```powershell
python scripts\check_pose_optimization_readiness.py --runtime-profile evaluations\pose_runtime_profile_B_local_service_adl30_cpu_20260705.json --provider-ab evaluations\pose_provider_ab_dev_smoke_20260705.json --temporal-check evaluations\pose_temporal_sequences_check_dev_smoke_20260705.json --lstm-manifest data\temporal_v6_training\lstm_v6_pose_dev_smoke_training_manifest.json --allow-cpu-provider --output evaluations\pose_optimization_readiness_local_service_cpu_20260705.json
```

结果：

```text
overall_ready = false
passed_gates = ["provider", "temporal_data", "lstm_manifest"]
failed_gates = ["runtime"]
```

runtime blockers：

```text
pose_valid_rate_below_0.70
busy_skip_too_high
pose_frame_stale
frame_tracking_desync
runtime_pose_valid_rate_below_0.70
latest_result_pose_available_ratio_below_0.60
```

证据文件：

```text
evaluations/pose_optimization_readiness_local_service_cpu_20260705.json
```

解释：

这份 readiness 把问题压得很清楚：本机小样本 provider、temporal、manifest 都能过；runtime 过不了。现在要继续修的是服务运行时稳定性，不是把模型丢去训练炉里再烤一遍。

修复后的 readiness：

```powershell
python scripts\check_pose_optimization_readiness.py --runtime-profile evaluations\pose_runtime_profile_B_local_service_adl30_cpu_publish_delta_20260705.json --provider-ab evaluations\pose_provider_ab_dev_smoke_20260705.json --temporal-check evaluations\pose_temporal_sequences_check_dev_smoke_20260705.json --lstm-manifest data\temporal_v6_training\lstm_v6_pose_dev_smoke_training_manifest.json --allow-cpu-provider --output evaluations\pose_optimization_readiness_local_service_cpu_after_runtime_fixes_20260705.json
```

结果：

```text
overall_ready = false
passed_gates = ["provider", "temporal_data", "lstm_manifest"]
failed_gates = ["runtime"]
runtime blockers = ["busy_skip_too_high", "frame_tracking_desync"]
```

这比上一版 readiness 更干净：`pose_valid_rate_below_0.70` 和 `latest_result_pose_available_ratio_below_0.60` 已经消失。

### 4.1 新增推理锁 owner 归因后的 readiness

本轮继续补了一层诊断：`ultralytics_inference_lock` 现在会记录当前持有者，姿态 worker 拿不到锁时，`skip_reasons` 不只记录一个笼统的 `busy`，还会记录：

```text
busy_by_person_detector
busy_by_fall_detector
busy_by_pose:<provider>
```

这很重要。以前 `busy` 像一句废话：只告诉你“有人占着厕所”，不告诉你是谁。现在至少能知道是 person detector、fall detector，还是 pose 自己在把链路堵住。

实现点：

```text
app/ai/inference_guard.py
app/detection/object_detector.py
app/detection/yolo_fall_detector.py
app/services/pose_service.py
tests/test_pose_service.py
```

同时修了一个并发细节：释放 Ultralytics 锁和清空 owner 放到同一个状态锁内，避免旧持有者在释放尾声把新持有者的 owner 误清掉。诊断字段如果会撒谎，那还不如没有。

本地 GMDC 短视频 CPU B 档探针：

```powershell
python scripts\probe_pose_runtime_status.py --base-url http://127.0.0.1:8010 --profile-name B_local_service_gmdc_adl08_cpu_owner_diag_guard_fix --duration-seconds 8 --interval-seconds 1 --output evaluations\pose_runtime_profile_B_local_service_gmdc_adl08_cpu_owner_diag_guard_fix_20260705.json
```

结果：

```text
runtime_pose_valid_rate = 0.8333
runtime_inference_success_rate = 0.9091
latest_result_pose_available_ratio = 0.6667
skipped_due_to_busy = 5
skip_reason_delta = {
  "busy": 5,
  "busy_by_fall_detector": 2,
  "busy_by_person_detector": 2,
  "no_tracking": 1,
  "pose_fps_throttle": 7,
  "pose_frame_stale": 1
}
gate.passed = false
gate.blockers = ["busy_skip_too_high", "pose_frame_stale"]
```

readiness：

```powershell
python scripts\check_pose_optimization_readiness.py --runtime-profile evaluations\pose_runtime_profile_B_local_service_gmdc_adl08_cpu_owner_diag_guard_fix_20260705.json --provider-ab evaluations\pose_provider_ab_dev_smoke_20260705.json --temporal-check evaluations\pose_temporal_sequences_check_dev_smoke_20260705.json --lstm-manifest data\temporal_v6_training\lstm_v6_pose_dev_smoke_training_manifest.json --allow-cpu-provider --output evaluations\pose_optimization_readiness_local_service_cpu_owner_diag_guard_fix_20260705.json
```

结果：

```text
overall_ready = false
passed_gates = ["provider", "temporal_data", "lstm_manifest"]
failed_gates = ["runtime"]
runtime blockers = ["busy_skip_too_high", "pose_frame_stale"]
```

解释：

这份证据比前面的 ADL-30 更像“问题画像”，不是因为它证明系统好了，而是因为它把坏在哪里说得更具体：

```text
person detector 和 fall detector 都在抢同一把 Ultralytics 推理锁；
姿态 worker 的有效率在短窗口内能过 0.70；
但 busy 仍然超标，且仍可能出现 frame stale；
所以当前瓶颈仍是调度/资源竞争，不是立刻重训姿态模型。
```

注意：GMDC 视频只有十几秒，这个 probe 是短窗口 CPU 归因证据，不是 120 秒生产稳定性证明。把它说成“线上已通过”就是很会包装、也很不负责。

### 4.2 增加姿态推理锁有界等待后，busy 下降但 runtime 仍不稳定

owner 归因已经把问题指向了全局 Ultralytics 推理锁竞争。下一步没有继续写空话，而是加了一个小的调度改动：

```env
POSE_INFERENCE_LOCK_WAIT_MS=160
```

含义：

```text
POSE_SKIP_WHEN_INFERENCE_BUSY=true 仍然保留；
姿态不再无限阻塞等待推理锁；
但在判定 busy 之前，先给姿态最多 160ms 的等待窗口。
```

为什么不是直接把 `POSE_SKIP_WHEN_INFERENCE_BUSY=false`？因为前面已经试过，完全阻塞会把帧拖旧，制造 `pose_frame_stale`。那条路很粗暴，效果也不漂亮。160ms 是这轮本机 CPU 短视频对照里更稳的折中值。

实现点：

```text
app/ai/inference_guard.py 支持 timeout
app/core/config.py 增加 pose_inference_lock_wait_ms
app/services/pose_service.py 在 skip_when_busy=true 时使用有界等待
.env / .env.example 增加 POSE_INFERENCE_LOCK_WAIT_MS=160
tests/test_pose_service.py 增加有界等待和 wait=0 回退测试
```

GMDC 同源短窗口对照：

```text
无等待 owner 归因:
  runtime_pose_valid_rate = 0.8333
  latest_result_pose_available_ratio = 0.6667
  runtime_inference_success_rate = 0.9091
  skipped_due_to_busy = 5
  blockers = ["busy_skip_too_high", "pose_frame_stale"]

POSE_INFERENCE_LOCK_WAIT_MS=80:
  runtime_pose_valid_rate = 0.9167
  latest_result_pose_available_ratio = 0.7778
  runtime_inference_success_rate = 1.0
  skipped_due_to_busy = 3
  blockers = ["busy_skip_too_high", "pose_frame_stale"]

POSE_INFERENCE_LOCK_WAIT_MS=160 第一次短窗口:
  runtime_pose_valid_rate = 1.0
  latest_result_pose_available_ratio = 0.6667
  runtime_inference_success_rate = 1.0
  skipped_due_to_busy = 0
  skip_reason_delta = {"pose_fps_throttle": 11}
  blockers = []

POSE_INFERENCE_LOCK_WAIT_MS=160 带元数据复跑:
  requested_duration_seconds = 8.0
  runtime_pose_valid_rate = 1.0
  latest_result_pose_available_ratio = 0.7778
  runtime_inference_success_rate = 1.0
  skipped_due_to_busy = 1
  skip_reason_delta = {
    "busy": 1,
    "busy_by_person_detector": 1,
    "frame_tracking_desync": 2,
    "pose_fps_throttle": 5,
    "pose_frame_stale": 5
  }
  blockers = ["pose_frame_stale", "frame_tracking_desync"]
```

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_pose_lock_wait80_20260705.json
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_pose_lock_wait160_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_pose_lock_wait160_20260705.json
```

wait160 readiness（带元数据复跑后）：

```text
overall_ready = false
production_ready = false
evidence_scope = development
passed_gates = ["provider", "temporal_data", "lstm_manifest"]
failed_gates = ["runtime"]
runtime blockers = ["pose_frame_stale", "frame_tracking_desync"]
```

解释：

这证明了一个很具体的结论：

```text
本机 CPU 短窗口里，姿态低性能的重要原因之一是调度竞争；
160ms 有界等待能显著压低 busy；
但 stale/desync 仍会复发，说明运行时同步问题还没解决干净；
这比立刻重训姿态模型更直接、更便宜，也更符合当前问题画像。
```

但边界也必须写清楚：

```text
这不是生产通过；
provider、temporal、manifest 仍是 dev/CPU 小样本证据；
readiness 现在会显式写出 production_ready=false；
readiness 现在也会要求 runtime 证据带 duration metadata，并且生产 runtime 至少 120 秒、30 个 ok sample；
GMDC 视频只有十几秒；
CUDA 真实服务 120 秒 B 档 probe 仍然必须跑。
```

### 4.3 增加 detection 历史快照后，desync 收敛但 stale 仍在

继续查 `frame_tracking_desync` 时发现一个明确断点：

```text
RealtimeResultStore 之前只保存 latest detection；
pose worker 先读 tracking，再读 latest detection；
如果 detection 在 tracking 之后又前进几帧，pose 就会拿“未来 detection frame”去配旧 tracking frame；
于是 frame_tracking_desync 就被制造出来。
```

已实施：

```text
app/detection/realtime_result_store.py 增加 detection history，默认保留最近 30 个 detection frame
app/services/pose_worker_service.py 优先按 tracking.frame_seq 取对应 detection frame
tests/test_realtime_result_store.py 覆盖 detection history 与容量上限
tests/test_pose_worker_service.py 覆盖 pose worker 使用 tracking 对应 detection frame
```

本地 GMDC wait160 对照：

```text
wait160 before detection history:
  runtime_pose_valid_rate = 1.0
  latest_result_pose_available_ratio = 0.7778
  skipped_due_to_busy = 1
  skip_reason_delta = {
    "busy": 1,
    "busy_by_person_detector": 1,
    "frame_tracking_desync": 2,
    "pose_fps_throttle": 5,
    "pose_frame_stale": 5
  }
  blockers = ["pose_frame_stale", "frame_tracking_desync"]

wait160 after detection history:
  runtime_pose_valid_rate = 0.7778
  latest_result_pose_available_ratio = 0.8889
  skipped_due_to_busy = 0
  skip_reason_delta = {
    "pose_fps_throttle": 7,
    "pose_frame_stale": 2
  }
  blockers = ["pose_frame_stale"]
```

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_detection_history_wait160_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_detection_history_wait160_20260705.json
```

解释：

这次不是“全好了”，但方向很清楚：

```text
frame_tracking_desync 已从 2 降到 0；
busy 也从 1 降到 0；
当前 runtime blocker 收敛成 pose_frame_stale。
```

也就是说，下一刀不要再泛泛说“姿态模型不行”，而是继续查 detection frame 年龄、短视频 EOF、pose worker tick 时机和生产流里 detection snapshot 的新鲜度。

### 4.4 重复 stale 去重后，确认还剩真实旧帧问题

继续查 `pose_frame_stale` 时，又发现一个容易把问题放大的点：

```text
同一个 detection frame 如果已经被判定 stale，
pose worker 后续 tick 再看到同一帧时，不应该继续把 pose_frame_stale 往 gate 里堆。
```

已实施：

```text
app/services/pose_worker_service.py 记录每个 camera 最近一次 stale detection frame_seq
同一 frame_seq 的重复 stale 记为 pose_frame_stale_duplicate
只有第一次 stale 进入 pose_frame_stale blocker
tests/test_pose_worker_service.py 覆盖同一 stale detection frame 只计一次
```

本地 GMDC wait160 对照：

```text
after detection history:
  pose_frame_stale = 2
  blockers = ["pose_frame_stale"]

after stale duplicate dedupe:
  runtime_pose_valid_rate = 0.7857
  latest_result_pose_available_ratio = 0.6667
  skipped_due_to_busy = 0
  skip_reason_delta = {
    "no_pose_attached": 1,
    "pose_fps_throttle": 10,
    "pose_frame_stale": 1
  }
  blockers = ["pose_frame_stale"]
```

证据文件：

```text
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_stale_dedupe_wait160_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_stale_dedupe_wait160_20260705.json
```

解释：

这一步把重复噪声压下去了，但没有把问题“美化掉”：

```text
pose_frame_stale 从 2 降到 1；
runtime gate 仍未通过；
剩下的是至少一个真实旧 detection frame，而不是同一旧帧被反复记账。
```

这说明下一步要查的是 detection 产生速度、视频源 EOF/断连、pose worker tick 与 detection worker 之间的时序，而不是继续扩大 TTL 或把 stale 从 gate 里删掉。删 gate 很简单，也很蠢。

## 5. 当前仍未完成的生产门禁

### 5.1 真实生产 runtime B 档

仍需在真实服务、真实摄像头或正式视频源下运行：

```powershell
python scripts\probe_pose_runtime_status.py --profile-name B --duration-seconds 120 --interval-seconds 2 --output evaluations\pose_runtime_profile_B_20260705.json
```

通过标准：

```text
runtime_pose_valid_rate >= 0.70
latest_result_pose_available_ratio >= 0.60
busy/stale/desync/mismatch 不持续增长
```

### 5.2 CUDA provider A/B

当前机器：

```text
torch = 2.8.0+cpu
cuda = false
cuda_device_count = 0
```

仍需在 CUDA 机器执行：

```powershell
python scripts\benchmark_pose_providers.py --providers yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx --device cuda:0 --output evaluations\pose_provider_ab_20260705.json
```

### 5.3 全量 pose-aware temporal export

仍需执行：

```powershell
python scripts\export_dataset_temporal_sequences.py --dataset ur_fall --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\export_dataset_temporal_sequences.py --dataset gmdcsa24 --labels data\phase7_labels\phase7_video_labels.jsonl --output-dir data\temporal_sequences_pose_v1 --frame-stride 2 --enable-pose --device cuda:0
python scripts\check_pose_temporal_sequences.py --input-dir data\temporal_sequences_pose_v1 --output evaluations\pose_temporal_sequences_check_20260705.json
```

### 5.4 residual_reviewed 必须重新生成或排除

本轮已经证明旧 residual 会污染 pose manifest：

```text
pose_quality_counts 出现大量 unknown
known_pose_quality_ratio 直接崩掉
```

生产 pose LSTM 有两个选择：

1. 重新生成 pose-aware residual reviewed 数据。
2. 在 pose LSTM 初版训练中显式不混 residual，等 residual 也 pose-aware 后再合入。

不能做的事：

```text
把旧 residual 硬塞进 --require-pose manifest。
```

这会让训练数据披着 pose 的外衣，里面还是旧占位符。很难看，也很危险。

## 6. 下一步实施优先级

### P0：修 runtime 输入和调度

当前 live-service CPU 证据显示，已修掉一部分问题：

```text
pose_valid_rate 已过 0.70
latest_result_pose_available_ratio 已过 0.60
GMDC 短窗口在 POSE_INFERENCE_LOCK_WAIT_MS=160 后 busy 明显下降，但带元数据复跑仍未过 runtime gate
detection history 已把 frame_tracking_desync 从短窗口复跑中清掉，当前 blocker 收敛到 pose_frame_stale
stale duplicate dedupe 后 pose_frame_stale 从 2 降到 1，但 runtime gate 仍未通过
```

剩余问题：

```text
生产 CUDA 120 秒 runtime gate 未验证
pose_frame_stale 仍在短窗口复跑中出现，需要继续查 detection frame 年龄、短视频 EOF、检测频率和 pose tick 时机
person_detector / fall_detector 与 pose 仍共享同一把 Ultralytics 推理锁，只是现在姿态有了有界等待
```

下一步建议：

1. 在正式 CUDA 环境跑同样 B 档 runtime probe。
2. 如果 CUDA 下 busy 消失，说明本机 CPU/ultralytics 锁竞争是主因，`POSE_INFERENCE_LOCK_WAIT_MS=160` 可以作为 B 档候选配置继续观察。
3. 如果 CUDA 下仍有 busy，考虑把 fall detector、person detector、pose provider 拆进独立 worker/process 或调低竞争频率。
4. 如果 CUDA 下仍有 stale，继续查 detection 新鲜度、短视频/摄像头断流、检测频率和 pose tick 时机。
5. 继续保留 `busy_by_*` 归因；没有 owner 的 busy 统计太粗，容易把调度问题甩锅给模型。

### P1：做 CUDA provider A/B

CPU dev-smoke 里 `yolo` 更快，但生产不能用 CPU 结论选 provider。CUDA A/B 必须跑。

### P2：全量导出 pose-aware 数据

旧 `data/temporal_sequences_phase6d` 不能用于 pose LSTM。它的 `pose_quality_counts=unknown` 是硬伤，不是小瑕疵。

### P3：训练 LSTM 前强制 manifest gate

训练前必须看到：

```text
require_pose = true
pose_training_gate.passed = true
train_command != null
```

否则停止训练。

## 7. 本轮验证

已通过：

```text
python -m pytest tests\test_temporal_v6_lstm_training_manifest.py tests\test_run_pose_optimization_pipeline.py tests\test_check_pose_optimization_readiness.py
12 passed
python -m pytest tests\test_probe_pose_runtime_status.py tests\test_result_publisher_service.py tests\test_pose_service.py
27 passed
```

本轮生成/更新的关键证据：

```text
evaluations/pose_optimization_pipeline_dev_smoke_20260705.json
evaluations/pose_optimization_pipeline_dev_smoke_after_runtime_fixes_20260705.json
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_20260705.json
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_after_busy_fix_20260705.json
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_publish_delta_20260705.json
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_yolo_provider_20260705.json
evaluations/pose_runtime_profile_B_local_service_adl30_cpu_blocking_pose_20260705.json
evaluations/pose_runtime_profile_C_local_service_adl30_cpu_delta3_20260705.json
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_owner_diag_guard_fix_20260705.json
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_pose_lock_wait80_20260705.json
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_pose_lock_wait160_20260705.json
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_detection_history_wait160_20260705.json
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_stale_dedupe_wait160_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_after_runtime_fixes_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_owner_diag_guard_fix_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_pose_lock_wait160_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_detection_history_wait160_20260705.json
evaluations/pose_optimization_readiness_local_service_cpu_stale_dedupe_wait160_20260705.json
data/temporal_v6_training/lstm_v6_pose_dev_smoke_training_manifest.json
```

最终回归：

```text
python -m pytest tests\test_run_pose_optimization_pipeline.py tests\test_check_pose_optimization_readiness.py tests\test_replay_pose_runtime_profiles.py tests\test_temporal_v6_lstm_training_manifest.py tests\test_check_pose_temporal_sequences.py tests\test_target_feature_extractor.py tests\test_export_dataset_temporal_sequences.py tests\test_temporal_service.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_realtime_result_store.py tests\test_result_publisher_service.py tests\test_fall_feature_builder.py tests\test_end_to_end_pipeline.py
76 passed, 4 warnings
python -m pytest tests\test_pose_service.py tests\test_detection_service.py tests\test_end_to_end_pipeline.py tests\test_probe_pose_runtime_status.py
17 passed, 4 warnings
```

一句话收尾：

```text
当前计划已经开始落地；本机 CPU 短窗口能证明调度修复有效，但生产完成仍未被证明。
接下来别急着重训模型，先在 CUDA 真实服务里把骨架稳定送到下游。
```

## 8. 本轮继续推进：把 `pose_frame_stale` 拆成可行动的问题

上一轮停在一个不舒服但正确的位置：`stale duplicate dedupe` 以后，重复噪声压下去了，但 runtime gate 仍然有 `pose_frame_stale`。这说明问题不是“同一帧被重复记账”这么简单，至少还有一次真实 stale。继续追下去后，已经把 stale 细分为：

```text
pose_frame_stale_source_eof
pose_frame_stale_capture_disconnected
pose_frame_stale_capture_stale
pose_frame_stale_detection_lag
pose_frame_stale
pose_frame_stale_duplicate
```

实现变化：

```text
app/services/pose_worker_service.py
  - stale 时读取 source_manager.worker_status(camera_id)
  - 根据 stream_state、connected、reconnect_reason、capture frame_age_ms 归因

scripts/probe_pose_runtime_status.py
scripts/replay_pose_runtime_profiles.py
  - gate 认识新的 stale 分类
  - source_eof 和 duplicate 不直接作为 runtime blocker
  - detection_lag / capture_stale / capture_disconnected 继续作为 blocker

tests/test_pose_worker_service.py
tests/test_probe_pose_runtime_status.py
tests/test_replay_pose_runtime_profiles.py
  - 覆盖 EOF、detection lag、gate blocker 规则
```

有效样本重算结果：

```text
evaluations/pose_runtime_profile_B_local_service_gmdc_adl08_cpu_stale_classified_wait160_resummarized_20260705.json

runtime_pose_valid_rate = 1.0
runtime_inference_success_rate = 1.0
latest_result_pose_available_ratio = 0.6667
skip_reason_delta = {
  "pose_fps_throttle": 6,
  "pose_frame_stale_detection_lag": 2,
  "pose_frame_stale_duplicate": 7,
  "pose_frame_stale_source_eof": 1
}
counter_consistency_warnings = [
  "pose_attached_delta_exceeds_target_delta",
  "inference_success_delta_exceeds_attempt_delta"
]
gate.blockers = ["pose_frame_stale_detection_lag"]
```

readiness 结果：

```text
evaluations/pose_optimization_readiness_local_service_cpu_stale_classified_wait160_resummarized_20260705.json

overall_ready = false
production_ready = false
failed_gates = ["runtime"]
runtime.blockers = ["pose_frame_stale_detection_lag"]
```

解释要说清楚，别含糊：

```text
source_eof = 本地短视频源结束，能解释 probe 尾部异常，但不是这次唯一问题。
detection_lag = detection 快照没有及时供给 pose worker，这是当前 runtime blocker。
duplicate = 同一 stale 帧的重复噪声，不应把 blocker 数量吹大。
counter_consistency_warnings = /status 异步计数首尾差分竞态，不代表模型突然超过 100% 正确。
```

还额外发现一个验证流程问题：同样的 8 秒本地短视频 probe，如果服务启动后视频很快跑到 EOF，采样窗口可能只看到 `pose_frame_stale_duplicate`，没有新的 target/inference。这类结果不能拿来评价模型性能，只能说明本地短视频 probe 太短、启动时机太脆。正式验证必须用真实摄像头或足够长的视频源跑 120 秒，不要拿 8 秒 EOF 尾巴当生产证据。

本轮回归：

```text
python -m pytest tests\test_pose_worker_service.py tests\test_probe_pose_runtime_status.py tests\test_replay_pose_runtime_profiles.py tests\test_check_pose_optimization_readiness.py
19 passed

python -m pytest tests\test_run_pose_optimization_pipeline.py tests\test_check_pose_optimization_readiness.py tests\test_replay_pose_runtime_profiles.py tests\test_temporal_v6_lstm_training_manifest.py tests\test_check_pose_temporal_sequences.py tests\test_target_feature_extractor.py tests\test_export_dataset_temporal_sequences.py tests\test_temporal_service.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_realtime_result_store.py tests\test_result_publisher_service.py tests\test_fall_feature_builder.py tests\test_end_to_end_pipeline.py
81 passed, 4 warnings
```

下一步已经更明确：

1. 查 `pose_frame_stale_detection_lag`：detection interval、detector 推理耗时、tracking 更新节奏、pose worker tick 时机、RealtimeResultStore 快照刷新频率。
2. 不要立刻把 `POSE_MAX_FRAME_AGE_MS` 再调大；先证明是延迟预算不合理，而不是 detection 链路供给太慢。
3. 正式 CUDA 环境跑 120 秒 B 档 probe，看 `pose_frame_stale_detection_lag` 是否仍存在。
4. 如果 CUDA 下 detection lag 消失，说明本机 CPU/短视频 probe 是主要限制；如果仍存在，才进入 worker/process 拆分或检测频率调度优化。

## 9. 本轮继续推进：person detection 先发布，CPU/dev 保守档通过

继续查 `pose_frame_stale_detection_lag` 后，发现 `DetectionService` 里有一个很实际的堵点：

```text
旧顺序：
person detector -> fall hint detector -> update_detection

新顺序：
person detector -> update_detection -> fall hint detector -> update_fall_detection
```

这个修改的意义很直接：person detection 一算完就进入 `RealtimeResultStore`，tracking 和 pose 不再被 fall hint 推理堵住。fall hint 仍然会跑，只是不再把人框快照扣在手里。这个问题不性感，但很要命；以前那种顺序等于让姿态链路为 fall hint 的慢吞吞买单。

改动文件：

```text
app/services/detection_service.py
tests/test_detection_service.py
```

新增测试：

```text
test_person_detection_is_published_before_fall_hint_runs
```

长视频 CPU 对照源：

```text
datasets/new_pose_imports/manual_fall_20260625/session_20260625_000003_fall_candidate_ec4c9594a3fee498abcee80566372029/video.mp4
duration ~= 122.97s
```

### 9.1 提前发布 person detection 后，原 B 档仍失败

配置：

```text
FALL_DETECTOR_INTERVAL_MS=200
POSE_MAX_FRAME_AGE_MS=800
POSE_RESULT_TTL_MS=800
POSE_INFERENCE_LOCK_WAIT_MS=160
```

结果：

```text
evaluations/pose_runtime_profile_B_local_service_longvideo_cpu_detection_publish_first_wait160_20260705.json

runtime_pose_valid_rate = 0.875
latest_result_pose_available_ratio = 1.0
skipped_due_to_busy = 0
pose_frame_stale_detection_lag = 4
gate = failed
```

解释：提前发布 person detection 是必要修复，但 CPU 检测供给仍然太低，约 1.35 FPS。`latest_detection_age_ms` 会冲到 891/969ms，800ms gate 会被打穿。

### 9.2 fall hint 降频到 800ms，只能缓解，不能清零

配置：

```text
FALL_DETECTOR_INTERVAL_MS=800
POSE_MAX_FRAME_AGE_MS=800
POSE_RESULT_TTL_MS=800
```

结果：

```text
evaluations/pose_runtime_profile_B_local_service_longvideo_cpu_detection_publish_first_fall800_wait160_20260705.json

runtime_pose_valid_rate = 0.8636
latest_result_pose_available_ratio = 1.0
skipped_due_to_busy = 1
pose_frame_stale_detection_lag = 2
gate = failed
```

解释：fall hint 降频有用，但 CPU 下 person detector 仍然会造成检测供给周期超过 800ms，且会和 pose 抢 Ultralytics 推理锁。把 fall interval 当万能药，是另一种偷懒。

### 9.3 CPU/dev 保守档通过 runtime gate

配置：

```text
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

结果：

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
```

这不是生产胜利，也不是 readiness 整体通过；只是本机 CPU/dev runtime 链路终于不再被 stale 卡死。它允许继续做本地联调和 pose-aware 数据链路验证，但不能替代 CUDA 120 秒 runtime probe，更不能替代正式 LSTM 对照报告。

本轮回归：

```text
python -m pytest tests\test_detection_service.py tests\test_pose_worker_service.py tests\test_probe_pose_runtime_status.py tests\test_replay_pose_runtime_profiles.py tests\test_tracking_worker_service.py
21 passed

python -m pytest tests\test_run_pose_optimization_pipeline.py tests\test_check_pose_optimization_readiness.py tests\test_replay_pose_runtime_profiles.py tests\test_temporal_v6_lstm_training_manifest.py tests\test_check_pose_temporal_sequences.py tests\test_target_feature_extractor.py tests\test_export_dataset_temporal_sequences.py tests\test_temporal_service.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_realtime_result_store.py tests\test_result_publisher_service.py tests\test_fall_feature_builder.py tests\test_detection_service.py tests\test_tracking_worker_service.py tests\test_end_to_end_pipeline.py
88 passed, 4 warnings
```

当前更贴合实际的计划修订：

1. 本地 CPU/dev 使用 Bcpu 保守档继续验证链路，不再拿 8 秒短视频 EOF 尾巴做判断。
2. 生产 CUDA 先跑原 B 档 120 秒；如果 `pose_frame_stale_detection_lag` 消失，说明 CPU 供给不足是主因。
3. 如果 CUDA 原 B 档仍有 detection lag，再在 CUDA 上做 `FALL_DETECTOR_INTERVAL_MS=800` 和 `POSE_MAX_FRAME_AGE_MS=1000` 对照。
4. 如果 CUDA 下仍有 busy 或 detection lag，才进入 person/fall/pose 三类 Ultralytics 推理 worker/process 解耦。不要一上来就重训姿态模型，那是把工程问题伪装成训练问题。

## 10. 本轮继续推进：把 Bcpu 变成可执行入口

上一节的 Bcpu 保守档已经有证据，但如果只写在文档里，后面执行时很容易抄漏参数。现在补了两个工具入口：

```text
scripts/pose_runtime_profile_env.py
scripts/run_pose_optimization_pipeline.py --mode dev-live
```

### 10.1 Bcpu env 输出

命令：

```powershell
python scripts\pose_runtime_profile_env.py --profile Bcpu --format powershell --output evaluations\pose_runtime_profile_Bcpu_env_20260705.ps1
```

输出文件：

```text
evaluations/pose_runtime_profile_Bcpu_env_20260705.ps1
```

关键参数：

```text
DETECTION_INTERVAL_MS=200
FALL_DETECTOR_INTERVAL_MS=800
POSE_WORKER_FPS=3
POSE_SKIP_WHEN_INFERENCE_BUSY=true
POSE_INFERENCE_LOCK_WAIT_MS=160
POSE_RESULT_TTL_MS=1000
POSE_PUBLISH_MAX_FRAME_DELTA=8
POSE_MAX_FRAME_AGE_MS=1000
POSE_MAX_TRACKING_FRAME_DELTA=2
```

### 10.2 dev-live pipeline

`dev-live` 的定位：

```text
真实 FastAPI 服务 + 本地/dev 证据 + production_ready=false
```

它不同于 `dev-smoke`。`dev-smoke` 是 replay，小样本冒烟；`dev-live` 是打真实 `/status`，所以 readiness 里不会带 `--allow-replay-runtime`。

dry-run 命令：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode dev-live --profile-name Bcpu --base-url http://127.0.0.1:8010 --duration-seconds 12 --interval-seconds 1 --dry-run --summary evaluations\pose_optimization_pipeline_dev_live_bcpu_dry_run_20260705.json
```

dry-run 输出：

```text
mode = dev-live
status = dry_run
stage_count = 2
production_ready = false
```

输出文件：

```text
evaluations/pose_optimization_pipeline_dev_live_bcpu_dry_run_20260705.json
```

新增测试：

```text
tests/test_pose_runtime_profile_env.py
tests/test_run_pose_optimization_pipeline.py
```

验证：

```text
python -m pytest tests\test_run_pose_optimization_pipeline.py tests\test_pose_runtime_profile_env.py
9 passed

python -m pytest tests\test_run_pose_optimization_pipeline.py tests\test_pose_runtime_profile_env.py tests\test_check_pose_optimization_readiness.py tests\test_replay_pose_runtime_profiles.py tests\test_temporal_v6_lstm_training_manifest.py tests\test_check_pose_temporal_sequences.py tests\test_target_feature_extractor.py tests\test_export_dataset_temporal_sequences.py tests\test_temporal_service.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_realtime_result_store.py tests\test_result_publisher_service.py tests\test_fall_feature_builder.py tests\test_detection_service.py tests\test_tracking_worker_service.py tests\test_end_to_end_pipeline.py
93 passed, 4 warnings
```

这一步解决的是执行可靠性，不是生产完成。现在工作人员不需要凭手感拼 Bcpu 环境变量，也不会把 dev-live 的通过误说成 production ready。少一点手工玄学，多一点可复现证据。

## 11. 本轮继续推进：readiness 明确拦截 Bcpu 生产误用

为了防止 Bcpu 被改名冒充生产档，`check_pose_optimization_readiness.py` 现在会检查 runtime 文件名和 `summary.profile_name`。只要出现 `Bcpu`，runtime gate 即使通过，也会被标为非生产证据：

```text
runtime_profile_is_bcpu_dev_profile
```

新增测试：

```text
test_bcpu_runtime_profile_is_not_production_ready_even_with_long_probe
```

这个测试覆盖一个故意刁钻的场景：

```text
profile_name = Bcpu
requested_duration_seconds = 120
ok_samples = 60
runtime gate = passed
provider = cuda:0
temporal gate = passed
lstm manifest gate = passed
lstm comparison = passed
```

预期仍然是：

```text
overall_ready = true
production_ready = false
non_production_reasons includes runtime_profile_is_bcpu_dev_profile
```

当前 Bcpu readiness 已复算。新增 `lstm_comparison` 门禁后，这份 readiness 会被正确卡住；这不是 runtime 倒退，而是终于不允许“没有 LSTM 对照报告也说整体准备好了”。

```text
evaluations/pose_optimization_readiness_local_service_Bcpu_longvideo_cpu_detection_publish_first_fall800_age1000_wait160_20260705.json

overall_ready = false
production_ready = false
failed_gates = ["lstm_comparison"]
blocking_reasons.lstm_comparison = ["pose_lstm_comparison_missing"]
runtime non-production reasons:
  runtime_profile_looks_like_dev_or_local_evidence
  runtime_profile_is_bcpu_dev_profile
  runtime_probe_duration_below_120s
  runtime_probe_ok_samples_below_30
```

验证：

```text
python -m pytest tests\test_check_pose_optimization_readiness.py tests\test_run_pose_optimization_pipeline.py tests\test_pose_runtime_profile_env.py
15 passed

python -m pytest tests\test_build_pose_lstm_comparison.py tests\test_run_pose_optimization_pipeline.py tests\test_pose_runtime_profile_env.py tests\test_check_pose_optimization_readiness.py tests\test_replay_pose_runtime_profiles.py tests\test_temporal_v6_lstm_training_manifest.py tests\test_check_pose_temporal_sequences.py tests\test_target_feature_extractor.py tests\test_export_dataset_temporal_sequences.py tests\test_temporal_service.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_realtime_result_store.py tests\test_result_publisher_service.py tests\test_fall_feature_builder.py tests\test_detection_service.py tests\test_tracking_worker_service.py tests\test_end_to_end_pipeline.py
103 passed, 4 warnings
```

这一步的价值不是提升指标，而是堵住管理口径上的漏洞：Bcpu 是本地开发保守档，不是上线许可证。把这句话写进门禁，比写进文档更可靠。现在再加上一条：Bcpu runtime 通过，也不等于 readiness 整体通过；没有 LSTM 对照报告，就别装作姿态融合已经证明有效。

## 12. 本轮继续推进：readiness 增加 LSTM 对照门禁

这次又补了一个容易被忽略、但非常要命的门：`lstm_comparison`。之前 readiness 已经要求 pose LSTM manifest，但 manifest 只能说明“数据和训练入口看起来准备好了”，它不能说明姿态真的提升了跌倒检测。

现在 `check_pose_optimization_readiness.py` 新增：

```text
--lstm-comparison evaluations/pose_lstm_comparison_20260705.json
```

同时新增了标准生成脚本，避免工作人员手写一份看起来很像真的 comparison JSON：

```powershell
python scripts\build_pose_lstm_comparison.py `
  --baseline-metrics evaluations\baseline_lstm_eval.json `
  --pose-metrics evaluations\pose_lstm_eval.json `
  --pose-ablation-metrics evaluations\pose_lstm_zero_pose_eval.json `
  --output evaluations\pose_lstm_comparison_20260705.json
```

它会从直接指标或 confusion 中提取/计算：

```text
precision
recall
f1
false_positive_count
```

新增 `evaluate_fall_lstm_metrics.py` 后，baseline/pose/zero-pose ablation 三份 eval JSON 也由脚本标准生成：

```powershell
python scripts\evaluate_fall_lstm_metrics.py `
  --input-manifest data\temporal_v6_training\lstm_v6_pose_training_manifest.json `
  --model models\fall_lstm_v6_pose.onnx `
  --schema models\fall_lstm_v6_pose_features.json `
  --threshold-calibration models\fall_lstm_v6_pose_threshold_calibration.json `
  --split test `
  --output evaluations\pose_lstm_eval_20260705.json
```

姿态清零消融使用同一模型和同一 schema，但加上：

```text
--zero-pose-features
--output evaluations\pose_lstm_zero_pose_eval_20260705.json
```

输出会包含：

```text
event_metrics.confusion
event_metrics.fall_event_precision
event_metrics.fall_event_recall
event_metrics.fall_event_f1
event_metrics.false_positive_count
```

这一步现在不只是一个单独脚本，也已经接入 `run_pose_optimization_pipeline.py`：

```text
production:
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

dev-smoke:
  lstm_pose_manifest_dev_smoke
  pose_lstm_train_dev_smoke
  baseline_lstm_eval_dev_smoke
  pose_lstm_eval_dev_smoke
  pose_lstm_zero_pose_eval_dev_smoke
  lstm_pose_comparison_dev_smoke
  readiness_dev_smoke
```

重新生成 dry-run 后，当前阶段数是：

```text
production stage_count = 13
dev-smoke stage_count = 11
dev-live stage_count = 2
```

`dev-live` 不生成 comparison；它只检查真实 FastAPI runtime，并复用已有 dev-smoke/provider/temporal/manifest/comparison 证据。原因很简单：dev-live 的职责是看真服务 `/status`，不是临时训练或评估 LSTM。

比较报告必须证明：

```text
pose_lstm.f1 > baseline_lstm.f1
pose_lstm.false_positive_count <= baseline_lstm.false_positive_count
pose_lstm.f1 > pose_lstm_zero_pose_ablation.f1
pose_lstm.false_positive_count <= pose_lstm_zero_pose_ablation.false_positive_count
comparison.passed != false
```

否则 readiness 会阻塞，例如：

```text
pose_lstm_not_better_than_baseline_f1
pose_lstm_not_better_than_zero_pose_ablation
pose_lstm_false_positives_worse_than_baseline
pose_lstm_false_positives_worse_than_zero_pose_ablation
lstm_comparison_report_failed
```

同时，如果比较文件名带 `dev`、`smoke`、`local`、`replay`，即使 gate 通过，也只算开发证据：

```text
lstm_comparison_looks_like_dev_or_smoke_evidence
```

新增测试：

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

这一步解决的是“自我感觉良好”的问题。只要没有正式对照证明 pose LSTM 赢过 `bbox+motion` baseline，并且赢过姿态清零消融，就不能说姿态融合有效。把骨架字段塞进 LSTM 很容易，证明它真的有用才是正事；脚本只是把证据格式标准化，不会把烂结果粉饰成通过。
