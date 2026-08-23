# 当前视觉系统模型体检报告

生成日期：2026-07-05  
工作区：`D:\Program\vision_service`

这份文档给工作人员快速了解当前系统里到底用了哪些模型、质量怎么样、性能怎么样、以及哪些地方看起来像“能跑”，实际上只是“还没炸”。

## 一句话结论

当前系统不是一个单一模型，而是一条拼接链路：通用人体检测、跌倒提示检测、姿态估计、时序 LSTM、状态机规则共同决定告警。它能跑，但质量并不干净；它有指标，但不少指标的测试集小得像试吃装；它有兜底，但兜底多到会把真实模型表现盖住。

最刺眼的问题有四个：

- 人体检测当前仍用 `yolov8n.pt` 通用模型，不是项目自训练人检模型。项目里有自训练候选，但自己的指标文件也写着“不要直接替换”。说难听点，基础入口还在吃预训练老本。
- 跌倒提示模型 `yolo_fall_hint_v2_plus_b012_best.pt` 验证集看着还行，测试集却缺 `fallen`、缺 `kneeling`，而且 `falling` 只有 1 个样本。拿这种测试集拍胸脯，等于拿一张便利贴当体检报告。
- 姿态模型 `pose_yolo_batch001_003_yolo11s_best.pt` 是当前启用的项目模型，速度不错，但 `pose mAP50-95` 比基线 `yolo11n-pose.pt` 低了 `0.034848`。它不是全面升级，只是某些场景更顺手。
- 时序模型 `fall_lstm_v5.onnx` 很小、能加载、ONNX 校验通过，但训练正样本只有 `51` 个，且当前配置允许 `TEMPORAL_FALLBACK_TO_MOCK=true`。这很危险：模型坏了也可能被 mock 兜底抹平，像把报警器接到玩具电池上。

## 当前启用模型

来自当前 `.env`：

| 模块 | 当前配置 | 模型路径 | 状态 |
|---|---|---|---|
| 人体检测 | `DETECTION_ENABLED=true` | `yolov8n.pt` | 启用，通用 COCO YOLOv8n |
| 跌倒提示检测 | `FALL_DETECTOR_ENABLED=true` | `models/yolo_fall_hint_v2_plus_b012_best.pt` | 启用，自训练 fall hint |
| 姿态检测 | `ENABLE_POSE=true`, `POSE_PROVIDER=yolo11_legacy` | `models/pose_yolo_batch001_003_yolo11s_best.pt` | 启用，自训练 YOLO11s pose |
| 时序跌倒模型 | `ENABLE_TEMPORAL=true`, `TEMPORAL_MODEL_PROVIDER=onnx_lstm` | `models/fall_lstm_v5.onnx` | 启用，ONNX LSTM |
| 身份识别 | `ENABLE_IDENTITY=false` | `buffalo_l` | 配置存在，但当前关闭 |

## 模型文件资产

| 模型 | 大小 | 修改时间 | 说明 |
|---|---:|---|---|
| `yolov8n.pt` | 6.25 MB | 2026-06-02 10:10 | 当前人体检测入口，通用模型 |
| `models/yolo_fall_hint_v2_plus_b012_best.pt` | 5.21 MB | 2026-06-29 14:16 | 当前跌倒提示模型 |
| `models/pose_yolo_batch001_003_yolo11s_best.pt` | 19.24 MB | 2026-06-30 05:59 | 当前姿态模型 |
| `models/fall_lstm_v5.onnx` | 0.08 MB | 2026-06-08 14:42 | 当前时序 LSTM |
| `models/person_yolo_batch001_yolov8n_best.pt` | 5.96 MB | 2026-06-29 17:56 | 自训练人检候选，未启用 |
| `models/rtmpose/rtmpose-l-pose-adapted-best.pth` | 106.38 MB | 2026-06-15 13:03 | MMPose/RTMPose 微调候选，未启用 |
| `models/external/rtmpose-m-body7-256x192/rtmpose-m-body7-256x192.zip` | 48.45 MB | 2026-06-27 15:36 | RTMPose ONNX SDK 压缩包，未解压到运行路径 |

## 人体检测模型

当前运行：`yolov8n.pt`

质量信息：

- 当前运行的是通用 YOLOv8n，不是针对本项目老人跌倒场景训练的专用人检模型。
- 自训练候选 `models/person_yolo_batch001_yolov8n_best.pt` 在小测试集上表现很好：`precision=1.0`、`recall=0.9977`、`mAP50=0.995`、`mAP50-95=0.732`。
- 但是这个候选只来自 `120` 张图，指标文件自己也警告：不要直接替换生产入口，需要 batch_002 hard negatives 和视频回放验证。

性能信息：

- 旧 e2e 验收中，当前 `yolov8n.pt` 检测约 `5.77 FPS`，推理延迟约 `37.09 ms`。

存在的问题：

- 当前入口模型太泛化。它能检测人，但对跌倒场景里趴卧、遮挡、低姿态、半身出画这些脏活不一定可靠。
- 自训练候选看起来漂亮，但样本量寒酸。120 张图练出来的高分，容易是“班级第一”，不是“全国统考第一”。
- 人检是整条链路的地基，地基一旦漏人，后面的姿态、LSTM、状态机再努力也只是给空气算命。

## 跌倒提示检测模型

当前运行：`models/yolo_fall_hint_v2_plus_b012_best.pt`

识别类别：

`falling`、`fallen`、`lying`、`sitting`、`bending`、`kneeling`、`standing`

质量信息：

- 训练数据：`datasets/fall_hint_v2`，共 `1334` 项。
- 验证集：`precision=0.749`、`recall=0.710`、`mAP50=0.761`、`mAP50-95=0.579`。
- 测试集：`precision=0.586`、`recall=0.667`、`mAP50=0.695`、`mAP50-95=0.523`。
- 针对 batch_012 的修复有效：`kneeling` top recall 从 `0.0` 变为 `1.0`。

性能信息：

- 该模型体积只有 `5.21 MB`，属于轻量 YOLO 分支。
- 当前运行配置：`YOLO_FALL_CONFIDENCE=0.25`、`YOLO_FALL_IMGSZ=640`、`YOLO_FALL_DEVICE=cuda:0`。

存在的问题：

- 测试集结构很难看：没有 `fallen` 和 `kneeling` 样本，`falling` 只有 1 个样本。也就是说，最关心的几类，测试集偏偏像请假了一样没来。
- batch_012 把 `kneeling` 修好了，但这更像“补了一个坑”，不能自动证明整条马路平了。
- 验证集和测试集差距明显，测试 `precision=0.586` 说明误报压力并不小。这个模型不是法官，只能算一个嗓门比较大的线索提供者。

## 姿态检测模型

当前运行：`models/pose_yolo_batch001_003_yolo11s_best.pt`

质量信息：

- 基线模型：`yolo11n-pose.pt`
- 候选模型：`models/pose_yolo_batch001_003_yolo11s_best.pt`
- 候选姿态指标：`pose_precision=0.998415`、`pose_recall=1.0`、`pose_mAP50=0.995`、`pose_mAP50-95=0.848643`。
- 基线 `pose_mAP50-95=0.883491`，候选比基线低 `0.034848`。
- link-match 测试中候选表现不错：`matched_rate=1.0`、`detached_rate=0.0`、`mean_skeleton_confidence=0.981012`、`mean_keypoint_recall=1.0`。

性能信息：

- 训练/评估中的候选推理时间：约 `11.75 ms`。
- provider 对比中，YOLO pose 平均延迟约 `47.24 ms`，RTMPose ONNX 约 `177.36 ms`，MMPose 微调版约 `224.64 ms`。
- 旧 e2e 验收里，姿态有效率只有 `pose_valid=0.3`，并出现 `skipped_due_to_busy=137`。

存在的问题：

- 当前 YOLO11s pose 并不是“全面更强”，它在关键点 `mAP50-95` 上输给了基线。别被 `mAP50=0.995` 这种好看的大字报骗了，细粒度关键点质量没有稳赢。
- 运行链路里的姿态有效率偏低。`pose_valid=0.3` 这种数字，翻译成人话就是：十次里面有七次姿态信息对告警链路帮不上忙。
- `skipped_due_to_busy=137` 暴露出调度压力。模型单次不算慢，但系统层面仍会跳帧；工作人员看到骨架偶尔消失，不要先怀疑眼睛，先怀疑队列。
- README 和 `.env.example` 里还残留多个 RTMPose 路径，其中 `models/rtmpose/rtmpose-x-body7-384x288.onnx` 当前不存在。这种配置残影很容易把排障人员带进沟里。

## 时序 LSTM 跌倒模型

当前运行：`models/fall_lstm_v5.onnx`

质量信息：

- 输入维度：`15`
- 窗口大小：`32`
- 训练配置：`epochs=30`、`batch_size=32`、`hidden_dim=64`、`stride=4`
- 训练样本：`384`
- 正样本：`51`
- 负样本：`333`
- 全窗口数：`548`
- ONNX 校验通过，最大误差 `1.49e-7`
- 当前阈值：`fall_probability=0.65`

性能信息：

- 模型大小只有 `0.08 MB`，非常轻。
- 旧 e2e 记录中 shadow ONNX LSTM 延迟约 `0.645 ms`。

存在的问题：

- 正样本只有 `51`，样本比例偏得很明显。用它学跌倒，像让一个只看过几次火灾录像的人去当消防专家。
- 指标文件主要证明“模型能导出、ONNX 输出一致”，但没有给出足够硬的独立测试准确率、召回率、误报率。能跑和靠谱是两件事。
- 当前 `.env` 里 `TEMPORAL_FALLBACK_TO_MOCK=true`。这会让模型缺失、schema 不匹配等问题被 mock 兜底吞掉。优点是系统不死，缺点是模型烂了也可能装作没事。
- 旧验收里 `temporal_confirmed_seen=0.0667`，而告警主要由 `field_fall_candidate_fusion` 之类规则确认。也就是说，LSTM 在最终告警里还不是铁证，更像旁听席上的证人。

## RTMPose / MMPose 候选

当前状态：未启用。

候选资产：

- `models/rtmpose/rtmpose-l-pose-adapted-best.pth`
- `models/rtmpose/rtmpose-l-aic-coco-384x288-state_dict.pth`
- `models/external/rtmpose-m-body7-256x192/rtmpose-m-body7-256x192.zip`

质量与性能：

- provider 对比中，`mmpose_finetuned` 平均骨架置信度 `0.9111`，高于 YOLO pose 的 `0.8985`。
- 但 `mmpose_finetuned` 平均延迟 `224.64 ms`，`rtmpose_onnx` 平均延迟 `177.36 ms`，远慢于 YOLO pose 的 `47.24 ms`。
- RTMPose-M ONNX 目前还在 zip 包里，metadata 写了内部 `end2end.onnx` 路径，但实际运行路径没有解压文件。

存在的问题：

- RTMPose 质量可能更稳，但速度账单很贵。想实时跑，先准备好吞掉延迟。
- 配置里提到的某些 RTMPose ONNX 路径不存在。工作人员照着 README 配，可能会配出一个空气模型。
- 当前系统的调度已经会跳过 YOLO pose 推理，再把更重的 RTMPose 塞进去，不调 worker 和队列就是给自己添堵。

## 端到端验收状态

旧 e2e 验收记录：

- 采样：`30` 次，持续 `60s`
- `camera_connected=1.0`
- `capture_fps_ok=1.0`
- `person_detected=0.8`
- `published_objects=0.5333`
- `track_stable=0.5333`
- `pose_valid=0.3`
- `fall_model_detected=0.0667`
- `temporal_confirmed_seen=0.0667`
- `reporter_post_success=0.8667`

这份验收的状态是 `PASSED`，但别高兴太早。它通过的是“现场链路没断”，不是“模型质量已充分认证”。同一份评估里还写了 `promotion_decision.passed=false`，原因是 frozen e2e 样本不够，`e2e_fall_count=1`、`e2e_adl_count=3`。这点样本量拿去做正式背书，基本就是把侥幸包装成结论。

## 风险排序

| 优先级 | 问题 | 影响 |
|---|---|---|
| P0 | 测试集太小且类别缺失 | 指标无法代表真实场景，容易误判模型质量 |
| P0 | `TEMPORAL_FALLBACK_TO_MOCK=true` | 模型错误可能被兜底隐藏，排障困难 |
| P1 | 姿态有效率低、跳帧多 | 姿态特征无法稳定进入时序/规则链路 |
| P1 | 当前人检仍用通用模型 | 低姿态、遮挡、跌倒姿势漏检会传染整条链路 |
| P1 | README/.env.example 中存在失效模型路径 | 工作人员按文档操作可能直接踩空 |
| P2 | 候选模型太多、命名混乱 | 维护人员难以判断哪个能用、哪个只是历史垃圾 |

## 建议动作

1. 固化一份“当前生产模型清单”，只保留当前启用、候选、废弃三类，不要让工作人员在一堆 `best.pt` 里猜命运。
2. 重新做跌倒提示模型测试集，必须覆盖 `falling`、`fallen`、`lying`、`kneeling`、`sitting`、`bending`、`standing`，每类样本别再个位数凑数。
3. 对当前 `yolov8n.pt` 和 `person_yolo_batch001_yolov8n_best.pt` 做同一批视频回放对比，再决定是否替换人检入口。
4. 单独压测姿态服务，把 `POSE_WORKER_FPS=2`、`POSE_FPS=3`、busy skip、TTL、GPU 占用一起看。现在的问题可能不只是模型，是调度像在拧巴。
5. 关闭或至少显式标记 `TEMPORAL_FALLBACK_TO_MOCK` 的生产风险。mock 可以救命，但不能装成医生。
6. 清理 README 和 `.env.example` 中不存在的 RTMPose ONNX 路径，避免工作人员把时间浪费在不存在的文件上。
7. 建立端到端验收基准：至少几十个 fall、几十个 ADL，按视频级 recall、false alarm、告警延迟出报告。现在那点验收样本，最多叫冒烟，不叫认证。

## 参考来源

- 当前运行配置：`.env`
- 姿态模型指标：`models/pose_yolo_batch001_003_yolo11s_metrics.json`
- 姿态 link-match：`models/pose_yolo_batch001_003_yolo11s_link_match_metrics.json`
- 姿态 provider 对比：`evaluations/phase10_pose_provider_comparison_001.json`
- 跌倒提示模型指标：`models/yolo_fall_hint_v2_plus_b012_metrics.json`
- 人体检测候选指标：`models/person_yolo_batch001_yolov8n_metrics.json`
- 时序 LSTM 指标：`models/fall_lstm_v5_metrics.json`
- 运行冒烟：`evaluations/phase6f_runtime_smoke_001.json`
- 端到端验收：`evaluations/phase9_e2e_acceptance_001.json`
- 完整质量闭环：`evaluations/phase9_full_accuracy_closure_001.json`
