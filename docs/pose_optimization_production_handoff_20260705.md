# 姿态检测优化生产交接说明

- 生成时间：2026-07-06T02:22:52.622546+00:00
- 结论级别：当前不能宣布生产可用，只能宣布门禁更硬、证据更清楚。
- 核心判断：姿态链路的问题不是单个模型拉胯，而是模型、运行时调度、骨架绑定、时序入模、生产验证一起拖后腿。

## 1. 当前状态

- 生产流水线状态：`error`，失败阶段：`production_preflight`。
- 生产预检：`passed=False`，这一步没过，后面的生产结论全都不能吹。
- 开发冒烟 readiness：`overall_ready=False`，`production_ready=False`。
- LSTM 姿态对照：`passed=False`，当前姿态 LSTM 没有证明自己比 bbox+motion baseline 更有用。

难听但重要：现在最危险的不是“姿态没有输出”，而是系统可能输出了一堆看起来像姿态证据的字段，但这些字段没有稳定、正确、有效地支撑跌倒判断。

## 2. 已有证据文件

| 证据 | 文件 | 用途 |
| --- | --- | --- |
| 生产预检 | `evaluations\pose_production_preflight_20260705.json` | 检查 CUDA、依赖、生产参数、实时 /status。 |
| 生产流水线 | `evaluations\pose_optimization_pipeline_20260705.json` | 记录生产门禁执行到哪里失败。 |
| 开发冒烟 readiness | `evaluations\pose_optimization_readiness_dev_smoke_20260705.json` | 开发证据汇总，只能说明链路形状，不能当生产证据。 |
| 开发 LSTM 对照 | `evaluations\pose_lstm_comparison_dev_smoke_20260705.json` | baseline、pose LSTM、zero-pose ablation 的直接对比。 |

## 3. 姿态模型质量门

- 校验文件：`evaluations\pose_model_quality_20260705.json`
- passed：`True`。
- baseline：`yolo11n-pose.pt`，pose mAP50-95：`0.8835`。
- candidate：`models/pose_yolo_batch001_003_yolo11s_best.pt`，pose mAP50-95：`0.8486`。
- delta pose mAP50-95：`-0.0348`。
- next_action：pose model quality gate passed; continue runtime/provider production validation

- 候选模型诊断：
  - 文件：`evaluations\pose_model_quality_yolo11s_candidate_20260705.json`
  - passed：`False`。
  - candidate：`models/pose_yolo_batch001_003_yolo11s_best.pt`，pose mAP50-95：`0.8486`。
  - blockers：`candidate_pose_map50_95_below_baseline`

刺耳但必要：候选模型更快不等于更好；如果 pose mAP50-95 低于 baseline，就不能拿它给姿态链路背书。
默认生产启动应回退到 `yolo11n-pose.pt` baseline；`pose_yolo_batch001_003_yolo11s_best.pt` 只能作为候选继续诊断，不能当默认生产增强模型。

## 4. 交接包校验

- 校验文件：`evaluations\pose_evidence_package_check_20260705.json`
- handoff_ready：`False`。
- next_action：fix production preflight first; no downstream evidence package is credible until this passes

| gate | blockers |
| --- | --- |
| `preflight` | `preflight_not_passed`, `preflight:cuda_device:cuda_unavailable`, `preflight:live_status:live_status_unreachable` |
| `pipeline` | `pipeline_status_not_ok`, `pipeline_production_ready_false`, `pipeline_has_failed_stages`, `pipeline_has_skipped_stages` |
| `pipeline_evidence_links` | `pipeline_evidence_stage_not_ok:production_preflight:failed`, `pipeline_evidence_stage_not_ok:lstm_pose_comparison:skipped`, `pipeline_evidence_stage_not_ok:readiness:skipped`, `pipeline_evidence_stage_not_ok:temporal_pose_check:skipped`, `pipeline_evidence_stage_not_ok:lstm_pose_manifest:skipped` |
| `readiness` | `readiness_overall_ready_false`, `readiness_production_ready_false`, `readiness_evidence_scope_is_not_production`, `readiness:runtime:runtime_profile_missing`, `readiness:provider:provider_ab_missing`, `readiness:temporal_data:temporal_pose_check_missing`, `readiness:lstm_manifest:pose_lstm_manifest_missing`, `readiness:lstm_comparison:pose_lstm_comparison_missing`, `readiness_non_production:evidence_consistency:runtime_pose_provider_metadata_missing`, `readiness_non_production:evidence_consistency:provider_device_metadata_missing_for_consistency`, `readiness_non_production:evidence_consistency:runtime_pose_model_metadata_missing`, `readiness_evidence_consistency_runtime_pose_provider_missing`, `readiness_evidence_consistency_runtime_pose_model_missing`, `readiness_evidence_consistency_provider_device_missing`, `readiness_evidence_consistency_provider_candidates_missing`, `readiness_evidence_consistency_passing_providers_missing` |
| `lstm_comparison` | `lstm_comparison_missing` |

## 5. 部署门禁

- 校验文件：`evaluations\pose_deployment_guard_20260705.json`
- deployment_allowed：`False`。
- active/evidence provider：`yolo11_legacy` / `None`。
- active/evidence model：`yolo11n-pose.pt` / `yolo11n-pose.pt`。
- next_action：run the production pose optimization pipeline until evidence_package.handoff_ready=true
- `scripts\start_current_camera.py` 在姿态开启且主系统告警开启时会自动执行该门禁；未通过会拒绝启动服务。
- `app\main.py` 的 FastAPI lifespan 也已接入同一套 deployment guard；直接 `uvicorn app.main:app` 也不能绕过姿态生产门禁。
- `scripts\start_phase5_test.py` 这类旧测试启动栈也已禁止回到 `POSE_RESULT_TTL_MS=500`、`POSE_MAX_FRAME_AGE_MS=500` 的脆弱默认。
- 部署门禁会比对 `.env` 实际启动的 pose provider/model 和 evidence package 中通过 readiness/model quality 的 provider/model；过审一套、启动另一套会被拦。
- 只有本地排查才允许显式使用 `--skip-pose-deployment-guard`，生产启动禁止使用这个绕过参数。

| gate | blockers |
| --- | --- |
| `evidence_package` | `pose_enabled_without_handoff_ready_evidence` |

| gate | warnings |
| --- | --- |
| `evidence_package` | `evidence_package_has_blockers` |

## 6. 启动入口安全审计

- 校验文件：`evaluations\pose_launch_safety_check_20260705.json`
- launch_safety_passed：`True`。
- next_action：launch safety passed with debug warnings; do not treat debug launch output as production evidence

| script | warnings |
| --- | --- |
| `scripts\start_phase5_test.py` | `direct_pose_launch_without_main_alert_not_production_evidence` |
| `scripts\debug_start_phase513c.py` | `pose_worker_fps_below_recommended_3`, `direct_pose_launch_without_main_alert_not_production_evidence`, `debug_pose_launch_not_production_evidence` |
| `scripts\debug_restart_matrix.py` | `pose_worker_fps_below_recommended_3`, `direct_pose_launch_without_main_alert_not_production_evidence`, `debug_pose_launch_not_production_evidence` |

## 7. 生产推广总门禁

- 校验文件：`evaluations\pose_promotion_gate_20260705.json`
- promotion_allowed：`False`。
- next_action：generate production-ready evidence first; do not promote pose until handoff_ready=true

| gate | blockers |
| --- | --- |
| `evidence_package` | `evidence_package_handoff_ready_false`, `preflight:preflight_not_passed`, `preflight:cuda_device:cuda_unavailable`, `preflight:live_status:live_status_unreachable`, `pipeline:pipeline_status_not_ok`, `pipeline:pipeline_production_ready_false`, `pipeline:pipeline_has_failed_stages`, `pipeline:pipeline_has_skipped_stages`, `pipeline_evidence_links:pipeline_evidence_stage_not_ok:production_preflight:failed`, `pipeline_evidence_links:pipeline_evidence_stage_not_ok:lstm_pose_comparison:skipped`, `pipeline_evidence_links:pipeline_evidence_stage_not_ok:readiness:skipped`, `pipeline_evidence_links:pipeline_evidence_stage_not_ok:temporal_pose_check:skipped`, `pipeline_evidence_links:pipeline_evidence_stage_not_ok:lstm_pose_manifest:skipped`, `readiness:readiness_overall_ready_false`, `readiness:readiness_production_ready_false`, `readiness:readiness_evidence_scope_is_not_production`, `readiness:runtime:runtime_profile_missing`, `readiness:provider:provider_ab_missing`, `readiness:temporal_data:temporal_pose_check_missing`, `readiness:lstm_manifest:pose_lstm_manifest_missing`, `readiness:lstm_comparison:pose_lstm_comparison_missing`, `readiness:readiness_non_production:evidence_consistency:runtime_pose_provider_metadata_missing`, `readiness:readiness_non_production:evidence_consistency:provider_device_metadata_missing_for_consistency`, `readiness:readiness_non_production:evidence_consistency:runtime_pose_model_metadata_missing`, `readiness:readiness_evidence_consistency_runtime_pose_provider_missing`, `readiness:readiness_evidence_consistency_runtime_pose_model_missing`, `readiness:readiness_evidence_consistency_provider_device_missing`, `readiness:readiness_evidence_consistency_provider_candidates_missing`, `readiness:readiness_evidence_consistency_passing_providers_missing`, `lstm_comparison:lstm_comparison_missing` |
| `deployment_guard` | `deployment_guard_deployment_allowed_false`, `evidence_package:pose_enabled_without_handoff_ready_evidence` |

- warnings：`2` 组，详见 `evaluations\pose_promotion_gate_20260705.json`。

## 8. 生产阻塞项

| gate | blocker | 影响 |
| --- | --- | --- |
| `cuda_device` | `cuda_unavailable` | 当前机器无法证明生产性能，CPU 证据只能用于开发定位。 |
| `live_status` | `live_status_unreachable` | 真实服务未连通，runtime pose_valid_rate、TTL、publisher 行为都没有生产证据。 |

生产流水线只完成 `2/14` 个阶段，跳过 `12` 个阶段，失败在 `production_preflight`。这意味着完整 runtime/provider/temporal/LSTM 生产证据尚未生成。

## 9. 开发冒烟发现

- 好消息：开发冒烟证明字段链路能跑通，pose-aware temporal 数据里确实出现了 `pose_available=true` 的行。
- 坏消息：这点不能自嗨。LSTM 对照里 pose LSTM、baseline、zero-pose ablation 指标完全一样，说明姿态特征目前没有贡献。

| 指标 | bbox+motion baseline | bbox+motion+pose LSTM | zero-pose ablation |
| --- | ---: | ---: | ---: |
| F1 | 0.75 | 0.75 | 0.75 |
| FP | 2 | 2 | 2 |
| Precision | 0.6 | 0.6 | 0.6 |
| Recall | 1 | 1 | 1 |

- LSTM 对照 blocker：`pose_lstm_not_better_than_baseline_f1`, `pose_lstm_not_better_than_zero_pose_ablation`
- dev readiness failed gates：`provider`, `lstm_comparison`, `evidence_consistency`
- temporal pose_available_true_ratio：`0.4225`。
- model quality：`passed=True`，当前校验模型是 `yolo11n-pose.pt`；这次不是拿 yolo11s 候选冒充生产增强。
- provider A/B：`passed=False`，设备是 `cpu`，最大 sampled_frames=`10`，最大 inference_attempts=`9`；CPU 小样本跑得动，不等于生产性能合格。
- LSTM manifest hash：`cf4cfb1e3bc948da0f8ff5e3cacd1280676e1d31907d62856fc30ab513017a72`。
- metrics input manifest 对齐：`True`；pose/zero-pose train_config manifest 对齐：`True`。

解释：姿态数据进入 LSTM，不等于姿态融合有效。zero-pose ablation 一样好，基本就是在告诉我们：当前时序模型还没学会用骨架，或者骨架信息质量/覆盖/标签对齐还不足以带来增益。
换句话说，dev-smoke 这次的价值是证明证据链不再散装，坏处是也证明姿态特征现在还没给 LSTM 带来实际收益。别把它包装成效果提升，那会很丢人。

## 10. 生产机执行顺序

先在有 CUDA、服务已启动、`/api/v1/status` 能访问的机器上跑预检：

```powershell
python scripts\check_pose_production_preflight.py --base-url http://127.0.0.1:8000/api/v1 --camera-id camera_01 --device cuda:0 --duration-seconds 120 --labels data\phase7_labels\phase7_video_labels.jsonl --temporal-output-dir data\temporal_sequences_pose_v1 --lstm-eval-split test --output evaluations\pose_production_preflight_20260705.json
```

预检通过后，先卡当前接入姿态模型本身的质量：

```powershell
python scripts\check_pose_model_quality.py --metrics models\pose_yolo_batch001_003_yolo11s_metrics.json --configured-model yolo11n-pose.pt --output evaluations\pose_model_quality_20260705.json
python scripts\check_pose_model_quality.py --metrics models\pose_yolo_batch001_003_yolo11s_metrics.json --configured-model models\pose_yolo_batch001_003_yolo11s_best.pt --output evaluations\pose_model_quality_yolo11s_candidate_20260705.json
```

预检过了再跑完整生产流水线：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode production --device cuda:0 --duration-seconds 120 --lstm-eval-split test --summary evaluations\pose_optimization_pipeline_20260705.json
```

默认不传 `--configured-pose-model` 时，production pipeline 会读取 `.env` 当前 `POSE_PROVIDER` 对应的姿态模型路径；如果要诊断候选模型，必须显式传入 `--configured-pose-model`，别让质量门检查一套、服务启动另一套。

这条 production pipeline 会在非 dry-run 模式下自动生成并回填后置门禁：`pose_evidence_package_check_20260705.json`、`pose_deployment_guard_20260705.json`、`pose_launch_safety_check_20260705.json`、`pose_promotion_gate_20260705.json`。
证据包还会检查每个 `status=ok` stage 的 `output` 文件是否真实存在，并要求产物修改时间不早于该 stage 的 `started_at`，防止命令返回 0 但证据文件没落盘，或拿旧 JSON 冒充本轮新证据。
生产模式退出码也受 `promotion_allowed` 约束；stage 全部跑完但总门禁没过，自动化仍应看到非零退出码。

本机只能跑开发冒烟，命令如下；它可以帮助定位链路，但不能拿去做上线背书：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode dev-smoke --summary evaluations\pose_optimization_pipeline_dev_smoke_20260705.json
```

生产机跑完后，用这条命令检查证据包能不能交接：

```powershell
python scripts\check_pose_evidence_package.py --output evaluations\pose_evidence_package_check_20260705.json
```

正式启动服务前，再跑部署门禁：

```powershell
python scripts\check_pose_deployment_guard.py --env-file .env --evidence-package evaluations\pose_evidence_package_check_20260705.json --output evaluations\pose_deployment_guard_20260705.json
```

再跑启动入口安全审计，确认没有其他脚本绕过门禁或退回脆弱姿态参数：

```powershell
python scripts\check_pose_launch_safety.py --output evaluations\pose_launch_safety_check_20260705.json
```

最后跑生产推广总门禁，只有它通过才允许进入受控生产推广：

```powershell
python scripts\check_pose_promotion_gate.py --output evaluations\pose_promotion_gate_20260705.json
```

使用当前摄像头启动脚本时，若姿态和主系统告警同时开启，脚本会自动执行同一套部署门禁；门禁不过会直接拒绝启动：

```powershell
python scripts\start_current_camera.py --enable-pose --enable-main-system-alerts
```

production dry-run 计划阶段：
- `production_preflight` -> `evaluations\pose_production_preflight_20260705.json`
- `runtime_probe` -> `evaluations\pose_runtime_profile_B_20260705.json`
- `provider_ab` -> `evaluations\pose_provider_ab_20260705.json`
- `temporal_export_ur_fall` -> `data\temporal_sequences_pose_v1\ur_fall\export_summary.json`
- `temporal_export_gmdcsa24` -> `data\temporal_sequences_pose_v1\gmdcsa24\export_summary.json`
- `temporal_pose_check` -> `evaluations\pose_temporal_sequences_check_20260705.json`
- `lstm_pose_manifest` -> `data\temporal_v6_training\lstm_v6_pose_training_manifest.json`
- `pose_lstm_train` -> `models\fall_lstm_v6_pose.onnx`
- `baseline_lstm_eval` -> `evaluations\baseline_lstm_eval_20260705.json`
- `pose_lstm_eval` -> `evaluations\pose_lstm_eval_20260705.json`
- `pose_lstm_zero_pose_eval` -> `evaluations\pose_lstm_zero_pose_eval_20260705.json`
- `lstm_pose_comparison` -> `evaluations\pose_lstm_comparison_20260705.json`
- `readiness` -> `evaluations\pose_optimization_readiness_20260705.json`

dev-smoke dry-run 计划阶段：
- `runtime_replay_dev_smoke` -> `evaluations\pose_runtime_replay_dev_smoke_20260705.json`
- `provider_ab_dev_smoke` -> `evaluations\pose_provider_ab_dev_smoke_20260705.json`
- `temporal_export_ur_fall_dev_smoke` -> `data\temporal_sequences_pose_dev_smoke\ur_fall\export_summary.json`
- `temporal_pose_check_dev_smoke` -> `evaluations\pose_temporal_sequences_check_dev_smoke_20260705.json`
- `lstm_pose_manifest_dev_smoke` -> `data\temporal_v6_training\lstm_v6_pose_dev_smoke_training_manifest.json`
- `pose_lstm_train_dev_smoke` -> `models\fall_lstm_v6_pose_dev_smoke.onnx`
- `baseline_lstm_eval_dev_smoke` -> `evaluations\baseline_lstm_eval_dev_smoke_20260705.json`
- `pose_lstm_eval_dev_smoke` -> `evaluations\pose_lstm_eval_dev_smoke_20260705.json`
- `pose_lstm_zero_pose_eval_dev_smoke` -> `evaluations\pose_lstm_zero_pose_eval_dev_smoke_20260705.json`
- `lstm_pose_comparison_dev_smoke` -> `evaluations\pose_lstm_comparison_dev_smoke_20260705.json`
- `readiness_dev_smoke` -> `evaluations\pose_optimization_readiness_dev_smoke_20260705.json`

dev-live dry-run 计划阶段：
- `runtime_probe_dev_live` -> `evaluations\pose_runtime_profile_Bcpu_dev_live_20260705.json`
- `readiness_dev_live` -> `evaluations\pose_optimization_readiness_Bcpu_dev_live_20260705.json`

## 11. 验收口径

- 生产预检必须 `passed=true`，否则别往下谈。
- 生产预检必须检查 `.env` active pose provider/model/device；模型文件不存在、pose 被关闭、active device 不是 CUDA，后面的 runtime/provider/LSTM 讨论都先闭嘴。
- live `/status` 里的 `pose_provider` 和 `pose_model_path` 必须匹配 `.env` active 配置；服务跑旧配置但接口还活着，这种假健康不能放过。
- 交接包里的 preflight、model quality、temporal pose check、LSTM manifest、LSTM comparison、readiness 必须是同一轮 production pipeline 对应 stage 的 `output`；拿旧 JSON 拼包就是证据污染。
- production pipeline 的模型质量门默认必须跟随 `.env` 当前 `POSE_PROVIDER` 的 active model；显式覆盖只用于候选诊断，不能让启动配置和质量证据各查各的。
- evidence package 不能只相信 readiness summary 自称 ready；readiness 里必须带 runtime pose provider/model、provider device、passing providers、provider model paths、configured model，并且这些字段必须互相对齐。
- 当前接入姿态模型必须通过 model quality gate；pose mAP50-95 低于 baseline 的候选，即使更快，也不能作为生产增强证据。
- deployment guard 必须确认 `.env` 的 `POSE_PROVIDER` 与 handoff evidence 里的 runtime pose provider 一致；模型一致但 provider 换了，仍然是证据污染。
- FastAPI 服务本体启动时也必须执行 deployment guard；只保护启动脚本、不保护 `app.main`，就等于给直接 uvicorn 留后门。
- runtime 必须是真实 FastAPI 服务证据，不是 replay、mock、local smoke。
- provider A/B 必须在 CUDA 上跑，CPU 结果只能说明代码能跑，不能说明生产性能。
- provider A/B 不能只看 `pose_valid_rate`；采样帧数、姿态推理次数、平均延迟、骨架平均置信度也必须过线，否则就是小样本自嗨或慢吞吞的漂亮废物。
- runtime、provider A/B、model quality 必须描述同一套姿态配置；runtime 里缺 `pose_provider`，或者 runtime 使用的 provider 没有通过 provider A/B，都只能算半截证据。
- runtime probe 里的 `pose_model_path` 必须和 model quality 的 `configured_model` 一致；只匹配 provider 不够，模型文件不一致就是两套证据在互相冒充。
- provider A/B 的 `provider_model_paths` 也必须和 model quality 的 `configured_model` 对齐；否则 A/B 性能是在测另一套模型。
- pose-aware temporal 数据必须通过 pose gate，尤其要看 `pose_available_true_ratio`、`known_pose_quality_ratio`、`pose_track_mismatch`，以及可用骨架行是否带 `pose_runtime.pose_provider` 和 `pose_runtime.pose_model_path`。
- `--require-pose` 的 LSTM manifest 也必须二次检查可用骨架行的 `pose_runtime.pose_provider` 和 `pose_runtime.pose_model_path`；时序检查被绕过时，manifest 不能继续把脏骨架喂给训练。
- LSTM comparison 必须记录 `lstm_manifest.sha256`、`schema_hashes`、`pose_provider_counts`、`pose_model_path_counts`，并确认 metrics 的 `input_files` 与 manifest 一致，三份 metrics 自报的 `input_manifest.sha256` 必须等于 comparison 传入的 manifest，pose/zero-pose metrics 的 `train_config.input_manifest_sha256` 也必须等于同一份 manifest；否则指标漂亮也只是来源不明的散装数字。
- pose-aware temporal 生产证据不能是几十行单数据集冒烟样本；至少要覆盖 `ur_fall`、`gmdcsa24`、`fall`、`non_fall`，并达到生产级行数和可用姿态行数。
- bbox+motion+pose LSTM 必须同时打赢 bbox+motion baseline 和 zero-pose ablation，且 false positive 不能变差。
- LSTM readiness 不能只相信 comparison 文件自称 passed；必须独立看到 baseline、pose、zero-pose ablation 的 F1 和 false positive 证据。
- `low_quality` 不能直接支持告警，`pose_track_mismatch` 要当风险证据处理。
- deployment guard 必须 `deployment_allowed=true`，否则即使服务能启动，也不准把姿态链路当生产能力宣传。
- 生产启动不得使用 `--skip-pose-deployment-guard`；用了这个参数，启动结果只能算本地排查，不能算上线证据。
- launch safety 必须无 blocker；debug 启动脚本允许 warning，但其输出不能作为生产证据。
- promotion gate 必须 `promotion_allowed=true`；只通过 launch safety 或只通过 deployment guard 都不算姿态生产完成。

## 12. 下一步计划

1. 在 CUDA 生产候选机启动真实服务，先跑 production preflight，消掉 `cuda_unavailable` 和 `live_status_unreachable`。
2. 跑完整 production pipeline，生成 runtime、provider、temporal、LSTM、readiness 全套 JSON。
3. 如果 runtime 仍低于门槛，优先查 TTL、frame stale、busy lock、tracking frame delta，不要急着重训模型。
4. 如果 runtime 稳定但 LSTM 对照仍打不赢 zero-pose ablation，再回到数据质量、骨架特征表达、标签对齐和模型结构。
5. 只有生产 readiness 给出 `production_ready=true`，才允许讨论上线；在此之前，所有“效果变好了”的说法都算嘴硬。
