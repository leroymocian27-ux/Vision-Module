# Fall Model Retraining Target - 2026-06-23

## Scope And Freeze Rules

本阶段进入跌倒检测模型重训前准备阶段，只做目标确认、数据审计和方案设计。

禁止事项已遵守：

- 未训练模型。
- 未覆盖、替换或移动 baseline 权重。
- 未修改 `.env`。
- 未修改生产代码。
- 未启用真实 POST。
- 未执行 `git add .` 或 `git commit`。
- 未把任何新数据直接混入训练集。

## Current Baseline

必须保留的 baseline：

- `models/yolo_fall_detector_phase9_selected.pt`

建议未来新模型命名：

- `models/yolo_fall_detector_hardneg_v1.pt`

当前 baseline 评测结论来自 `docs/labeled_dataset_validation_20260623.md` 与 `artifacts/labeled_dataset_validation_20260623/`：

| Metric | Value |
| --- | ---: |
| TP | 5 |
| FP | 5 |
| FN | 0 |
| TN | 2 |
| Precision | 0.5000 |
| Recall | 1.0000 |
| False Positive Rate | 0.7143 |

误报集中场景：

| Scene | FP |
| --- | ---: |
| walk | 1 |
| no_person | 1 |
| sit | 2 |
| squat | 1 |

结论：当前主问题不是跌倒召回不足，而是 non_fall / hard negative 被 YOLO fall detector 判成 fall 的比例过高。

## Retraining Priority

| Priority | Model / Component | Decision | Reason |
| ---: | --- | --- | --- |
| 1 | `models/yolo_fall_detector_phase9_selected.pt` | 优先微调 / 重训 | FP 直接来自 fall detector 对 hard negative 的判别边界；Recall 已满，最小改动目标应是压低 fall 类误报。 |
| 2 | Temporal / LSTM / 时序分类器 | 第二阶段考虑 | 时序可以利用 fall_start/fall_end、速度、静止持续时间压误报，但当前时间窗标注不完整，不适合先动。 |
| 3 | `yolov8n.pt` person detector | 暂不重训 | 当前评测并未显示 person detector 是主要瓶颈；误报发生在已有 person/track/pose 链路后。重训 person 会扩大风险面。 |
| 4 | `yolo11n-pose.pt` / `yolov8n-pose.pt` pose | 暂不重训 | pose 当前用于附加质量观测，误报根因不是关键点类别错误；pose 重训成本高且需关键点标注。 |
| 5 | 0-5 VisualRiskMarker | 暂不作为主训练目标 | VisualRiskMarker 更适合运行时解释和规则辅助；本阶段目标是修正 fall detector 的二分类/检测边界。 |

## Why Fall Detector First

优先重训 fall detector 的原因：

1. 评测链路 Recall=1.0、FN=0，说明跌倒召回暂时不是首要矛盾。
2. Precision=0.5、FPR=0.7143，说明当前模型对 walk、sit、squat、no_person 等负样本边界不稳。
3. person detector 与 pose 模型是上游通用感知模块，替换或重训会影响更多业务行为；fall detector 是最贴近误报类型的专用模型。
4. hard negative 数据可以直接作为 fall detector 微调的负样本；而 Temporal/LSTM 需要可靠 `fall_start_sec` / `fall_end_sec`，当前尚未具备。

## Proposed Target For hardneg_v1

建议新模型目标：

- 模型输出：继续保持现有 fall detector 接口兼容。
- 训练方式：从 `models/yolo_fall_detector_phase9_selected.pt` 微调或以其同源配置重训。
- 数据策略：增加 hard negative 负样本，不降低真实跌倒召回。
- 目标命名：`models/yolo_fall_detector_hardneg_v1.pt`。
- 验收前提：必须保留 `models/yolo_fall_detector_phase9_selected.pt` 作为对照。

建议 hardneg_v1 验收门槛：

| Metric | Gate |
| --- | --- |
| Recall | 不低于 baseline，目标 >= 0.95 |
| Precision | 高于 baseline，最低目标 >= 0.75 |
| FPR | 明显低于 baseline，第一阶段目标 <= 0.35 |
| hard_negative FPR | walk/sit/squat/bend/lie_down/no_person 分场景统计 |
| Regression | 现有 12 条验证样本必须继续保留为 held-out，不可混入训练 |

## Not Ready To Train Yet

当前还不建议直接开始训练 `hardneg_v1`，原因：

- `fall_start_sec` / `fall_end_sec` 大量缺失，尤其是本阶段验证 CSV 中 12 条全部为空。
- hard negative 覆盖不均衡：walk 多，sit/squat/bend/lie_down/no_person 明显不足。
- acceptance/logs 中有 9 个 screen/cropped/codec 录像，只适合回放或验收，不适合直接训练。
- 仍有 121 个视频标签为 unknown，需要人工确认后才能进入训练候选池。
- 当前 FP 样本应先冻结为回归测试，不能直接拿来训练，否则会污染评估。

## Next Gate

进入训练前必须完成：

1. 锁定训练 / 验证 / 测试 split，按 actor/session/source 防泄漏。
2. 对所有 fall 训练候选补齐 `fall_start_sec` / `fall_end_sec`。
3. 对 hard negative 逐条确认 scene 与 non_fall 标签。
4. 将 2026-06-23 labeled validation 12 条样本保持 held-out。
5. 补充 sit、squat、bend、lie_down_non_fall、no_person 数据后再训练。
