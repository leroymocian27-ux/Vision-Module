# 检测稳定性测试执行报告

- 执行日期：2026-07-06
- 执行范围：检测、跟踪、姿态、结果发布、时序/LSTM、跌倒融合、告警接口、姿态上线门禁、生产预检
- 当前结论：本机代码级稳定性通过；生产级稳定性未通过，原因是 CUDA 不可用、真实 FastAPI `/status` 不可达，生产流水线被正确拦截。

## 1. 总结论

这轮测试已经实施，不是停留在计划层面。

可以确认的部分：

| 层级 | 结论 | 说明 |
| --- | --- | --- |
| A 静态配置与启动门禁 | 通过 | FastAPI lifespan、启动脚本、deployment guard、launch safety 相关测试通过 |
| B 检测与跟踪 | 通过 | detection、tracking worker、RealtimeResultStore 单元稳定性通过 |
| C 姿态链路 | 通过 | pose service、pose worker、publisher、replay/profile 相关测试通过 |
| D 时序与融合 | 通过 | temporal、feature builder、fusion、LSTM 对比脚本相关测试通过 |
| E mock E2E | 通过 | mock camera 到告警 API 的本机链路通过 |
| 全量稳定性回归矩阵 | 通过 | `167 passed, 4 warnings` |
| F 生产预检 | 未通过 | `cuda_unavailable`、`live_status_unreachable` |
| 生产优化流水线 | 未通过 | 卡在 `production_preflight`，14 个阶段只执行 2 个，跳过 12 个 |

一句话：代码层没有明显断裂，门禁也没有摆烂；但生产证据还缺，不能宣布“检测稳定性已经生产可用”。

## 2. 已执行命令与结果

### A. 静态配置与启动门禁

```powershell
python -m pytest tests\test_app_pose_deployment_guard.py tests\test_check_pose_launch_safety.py tests\test_check_pose_deployment_guard.py tests\test_start_current_camera_pose_defaults.py -q
```

结果：

```text
25 passed in 1.15s
```

验证点：

- app 级 FastAPI lifespan 会执行姿态部署门禁。
- 启动脚本无法绕过 deployment guard。
- 显式关闭 `POSE_DEPLOYMENT_GUARD_ENABLED=false` 会被 launch safety 拦截。
- 当前默认姿态配置保持在更稳妥的基线：
  - `POSE_PROVIDER=yolo11_legacy`
  - `YOLO11_POSE_MODEL_PATH=yolo11n-pose.pt`
  - `POSE_WORKER_FPS=3`
  - `POSE_RESULT_TTL_MS=800`
  - `POSE_MAX_FRAME_AGE_MS=800`
  - `POSE_MAX_TRACKING_FRAME_DELTA=2`

### B. 检测与跟踪稳定性

```powershell
python -m pytest tests\test_detection_service.py tests\test_tracking_worker_service.py tests\test_realtime_result_store.py -q
```

结果：

```text
9 passed in 0.53s
```

结论：

- detection 写入 store 的基础路径正常。
- tracking worker 的 track 输出、保持、丢失处理没有在单测里暴露断裂。
- result store 没有出现 detection/tracking/pose/result 快照互相污染的问题。

### C. 姿态链路稳定性

```powershell
python -m pytest tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_result_publisher_service.py tests\test_check_pose_temporal_sequences.py tests\test_replay_pose_runtime_profiles.py -q
```

结果：

```text
41 passed in 1.00s
```

结论：

- `pose_absent`、`low_quality`、`pose_track_mismatch` 的质量分级逻辑通过测试。
- pose worker 对 stale detection、tracking desync、busy skip 的处理通过测试。
- publisher 对 TTL、frame alignment、pose 结果进入最终发布结果的规则通过测试。
- replay/profile 能覆盖 TTL、frame age、tracking delta 相关场景。

这说明当前不是“字段里随便塞点骨架就算成功”。系统已经开始区分真骨架、低质量骨架、错绑风险和空壳字段。

### D. 时序与融合稳定性

```powershell
python -m pytest tests\test_temporal_service.py tests\test_fall_feature_builder.py tests\test_fall_fusion.py tests\test_target_feature_extractor.py tests\test_build_pose_lstm_comparison.py tests\test_evaluate_fall_lstm_metrics.py -q
```

结果：

```text
33 passed in 0.73s
```

结论：

- `pose_available=false` 不会被当作有效骨架。
- `pose_quality_level` 能进入特征构建链路。
- pose LSTM 对比、zero-pose ablation、metrics/hash 校验脚本通过。
- 融合逻辑没有把低质量骨架直接当成强证据。

### E. Mock E2E 稳定性

```powershell
python -m pytest tests\test_end_to_end_pipeline.py tests\test_fall_alert_polling_api.py -q
```

结果：

```text
9 passed, 4 warnings in 10.21s
```

警告：

- 4 个 warning 来自 torchvision/Pillow 的弃用提示：
  - `Image.BILINEAR`
  - `Image.NEAREST`
  - `Image.BICUBIC`

这些不是本轮姿态/检测稳定性的直接失败，但属于以后升级依赖时会冒出来的维护账。

### 全量稳定性回归矩阵

```powershell
python -m pytest tests\test_detection_service.py tests\test_tracking_worker_service.py tests\test_pose_service.py tests\test_pose_worker_service.py tests\test_result_publisher_service.py tests\test_temporal_service.py tests\test_fall_feature_builder.py tests\test_fall_fusion.py tests\test_realtime_result_store.py tests\test_target_feature_extractor.py tests\test_end_to_end_pipeline.py tests\test_fall_alert_polling_api.py tests\test_app_pose_deployment_guard.py tests\test_check_pose_promotion_gate.py tests\test_check_pose_launch_safety.py tests\test_check_pose_deployment_guard.py tests\test_start_current_camera_pose_defaults.py tests\test_check_pose_evidence_package.py tests\test_check_pose_production_preflight.py tests\test_run_pose_optimization_pipeline.py tests\test_check_pose_optimization_readiness.py tests\test_check_pose_temporal_sequences.py tests\test_probe_pose_runtime_status.py tests\test_benchmark_pose_providers.py tests\test_replay_pose_runtime_profiles.py -q
```

结果：

```text
167 passed, 4 warnings in 10.89s
```

结论：

这组矩阵覆盖了核心本机代码路径、门禁脚本、证据包检查、promotion gate、runtime status probe、provider benchmark 的测试用例。它可以支撑“本机代码级稳定性通过”这个结论。

它不能支撑“生产稳定”这个结论。mock、replay、pytest 都不是 CUDA 真实摄像头长稳态证据。

## 3. 生产预检执行结果

执行命令：

```powershell
python scripts\check_pose_production_preflight.py --base-url http://127.0.0.1:8000/api/v1 --camera-id camera_01 --device cuda:0 --duration-seconds 120 --labels data\phase7_labels\phase7_video_labels.jsonl --temporal-output-dir data\temporal_sequences_pose_v1 --lstm-eval-split test --output evaluations\pose_production_preflight_20260706.json
```

结果文件：

- `evaluations\pose_production_preflight_20260706.json`

结果：

```json
{
  "passed": false,
  "blockers": [
    {
      "gate": "cuda_device",
      "blocker": "cuda_unavailable"
    },
    {
      "gate": "live_status",
      "blocker": "live_status_unreachable"
    }
  ]
}
```

关键细节：

- Python 依赖检查通过。
- 生产参数检查通过。
- 姿态 runtime 配置检查通过：
  - `pose_provider=yolo11_legacy`
  - `active_pose_model=yolo11n-pose.pt`
  - `active_pose_device=cuda:0`
- CUDA 检查失败：
  - `cuda_available=false`
  - `cuda_device_count=0`
- live status 检查失败：
  - URL：`http://127.0.0.1:8000/api/v1/status?camera_id=camera_01`
  - 错误：`http_404`

这不是小问题。生产预检的意思就是：没有 GPU、没有真实服务状态，就别假装自己已经跑过生产验证。

## 4. 生产优化流水线执行结果

执行命令：

```powershell
python scripts\run_pose_optimization_pipeline.py --mode production --device cuda:0 --duration-seconds 120 --lstm-eval-split test --summary evaluations\pose_optimization_pipeline_20260706.json
```

结果文件：

- `evaluations\pose_optimization_pipeline_20260706.json`

结果：

```json
{
  "mode": "production",
  "status": "error",
  "stage_count": 14,
  "completed_stage_count": 2,
  "executed_stage_count": 2,
  "skipped_stage_count": 12,
  "failed_stage": "production_preflight",
  "production_ready": false
}
```

已执行阶段：

| 阶段 | 结果 |
| --- | --- |
| pose_model_quality | 通过 |
| production_preflight | 失败 |

被跳过阶段：

- runtime probe
- provider A/B
- temporal export for `ur_fall`
- temporal export for `gmdcsa24`
- temporal pose check
- pose LSTM manifest
- pose LSTM train
- baseline LSTM eval
- pose LSTM eval
- zero-pose ablation eval
- pose LSTM comparison
- readiness

这个失败是正确的。生产预检没过，后面那些阶段继续跑出来的数字也不可信。

## 5. 当前模型质量门禁结果

生产流水线中的模型质量门禁通过，当前配置使用的是基线模型：

| 项目 | 值 |
| --- | --- |
| configured_model | `yolo11n-pose.pt` |
| baseline_model | `yolo11n-pose.pt` |
| candidate_model | `models/pose_yolo_batch001_003_yolo11s_best.pt` |
| baseline pose mAP50-95 | `0.883491` |
| candidate pose mAP50-95 | `0.848643` |
| delta | `-0.034848` |
| baseline recall | `1.0` |
| candidate recall | `1.0` |

结论：

当前接入基线 `yolo11n-pose.pt` 是合理的。候选模型 mAP 更低，不能靠“名字像新模型”就把它吹成更好。新不等于好，快也不等于稳。

## 6. 已有 30 分钟运行证据

已有文件：

- `evaluations\fall_hint_runtime_soak_30min_20260706.json`

该文件不是本轮刚启动生成，但可以作为当前系统近期运行证据参考。

关键指标：

| 指标 | 值 |
| --- | --- |
| duration_seconds | `1800.02` |
| sample_count | `357` |
| status_failures | `0` |
| integration_failures | `0` |
| camera_disconnect_samples | `0` |
| stream_not_connected_samples | `0` |
| frame_seq_regressions | `0` |
| max_reconnect_count | `0` |
| capture_fps mean | `10.8183` |
| detection_fps mean | `3.1883` |
| tracking_fps mean | `3.1879` |
| publish_fps mean | `9.1822` |
| publish_lag_ms p95 | `297.0` |
| pose_valid_rate mean | `0.8859` |
| pose_valid_rate min | `0.8842` |
| pose_fps mean | `0.39` |
| pose_fps p95 | `1.38` |
| reporter_error_samples | `357` |
| reporter_http2_seen | `false` |

正面信息：

- 30 分钟内本机状态采样没有失败。
- 摄像头没有断连。
- stream 没有显示未连接。
- frame sequence 没有回退。
- `pose_valid_rate` 维持在约 `0.886`，明显好于旧 E2E 中 `pose_valid=0.3` 的烂结果。

刺眼问题：

- `pose_fps mean=0.39`，这很低。即使有效率看起来不错，姿态链路的刷新频率仍然偏慢，不能让人放心地说“骨架非常跟手”。
- `reporter_error_samples=357`，说明 30 分钟采样里外部上报一直在报错。
- `reporter_http2_seen=false`，外部告警闭环没有被证明。

所以这份 soak 证据只能说：本机视觉链路能跑，姿态有效率有所改善；不能说：外部系统集成稳定、生产告警闭环稳定。

## 7. 当前稳定性判断

### 可以签的结论

- 本机代码级稳定性通过。
- 姿态链路的 TTL、frame age、tracking delta、quality level、publisher 发布规则有测试覆盖。
- 系统不会再轻易把空壳 pose payload 当成有效骨架。
- deployment guard、launch safety、promotion gate 的测试通过。
- 当前生产流水线会在证据不足时拒绝继续，这是好事。

### 不能签的结论

- 不能签“生产稳定”。
- 不能签“CUDA provider 性能达标”。
- 不能签“真实摄像头下 runtime_pose_valid_rate 稳定大于 0.70”。
- 不能签“pose-aware LSTM 已经优于 bbox+motion baseline”。
- 不能签“外部告警系统闭环稳定”。

现在如果有人拿 `167 passed` 去说“生产没问题了”，那就是把单元测试当生产验收，属于很不专业的自我安慰。

## 8. 当前主要问题

### 1. 生产环境证据缺失

生产预检失败项非常明确：

```text
cuda_unavailable
live_status_unreachable
```

这两个不过，后面的 provider A/B、runtime probe、全量 pose-aware 时序导出、LSTM 训练对照都没有资格进入正式结论。

### 2. 姿态 FPS 仍然偏低

30 分钟 soak 里：

```text
pose_fps mean = 0.39
pose_fps p95 = 1.38
```

这说明姿态并不是稳定 3 FPS 输出。当前“有效率”有改善，但刷新速度仍是短板。跌倒判断是时序问题，骨架慢半拍，后面 LSTM 和融合逻辑都会被拖累。

### 3. 外部告警上报没有闭环

30 分钟 soak 里：

```text
reporter_error_samples = 357
reporter_http2_seen = false
```

这不是姿态模型问题，但它会直接影响系统使用效果。检测做出来、报警送不出去，用户看到的就是系统不好用。

### 4. 真实 `/status` 路径仍然混乱

生产预检访问：

```text
http://127.0.0.1:8000/api/v1/status?camera_id=camera_01
```

返回：

```text
http_404
```

这意味着当前启动的服务实例、路由前缀、服务端口或真实服务状态并没有和生产预检脚本对齐。这个问题必须先修，不然 runtime 证据采不到。

## 9. 下一步执行顺序

不要急着重训姿态模型。当前最该做的是把生产证据链跑通。

1. 在有 CUDA 的机器上启动真实 FastAPI 服务。
2. 确认 `/api/v1/status?camera_id=camera_01` 返回 200，而不是 404。
3. 重新执行 `check_pose_production_preflight.py`，必须让 `passed=true`。
4. 再执行 `run_pose_optimization_pipeline.py --mode production`，让 14 个阶段完整跑完。
5. 跑 provider A/B，确认 CUDA 下哪个 provider 延迟和质量最好。
6. 导出全量 pose-aware 时序数据，确认 pose rows 不是空壳。
7. 训练并评估 bbox+motion+pose LSTM，对比 bbox+motion baseline 和 zero-pose ablation。
8. 最后跑 2 小时和 8 小时长稳态，采集 pose FPS、valid rate、stale/desync、告警误报漏报。

## 10. 交付物

本轮新增/更新的核心证据：

- `evaluations\pose_production_preflight_20260706.json`
- `evaluations\pose_optimization_pipeline_20260706.json`
- `docs\detection_stability_test_execution_20260706.md`

参考证据：

- `docs\detection_stability_test_plan_20260706.md`
- `evaluations\fall_hint_runtime_soak_30min_20260706.json`
- `evaluations\main_system_connectivity_block_20260706.json`
- `evaluations\pose_runtime_probe_detection_stability_20260706.json`

最终判断：

```text
本机 A-E 稳定性：通过
全量本机回归矩阵：通过，167 passed, 4 warnings
生产 F 稳定性：未通过
生产上线/推广：不允许
```

门禁失败不是坏事。坏事是没有证据还硬上。当前系统至少已经知道什么时候该闭嘴，这比盲目报喜强得多。
