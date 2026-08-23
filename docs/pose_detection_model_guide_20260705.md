# 姿态检测模型说明文档

生成日期：2026-07-05  
工作区：`D:\Program\vision_service`

本文用于帮助工作人员理解当前系统里的姿态检测模型：它是什么、输入输出是什么、有哪些候选模型、质量和性能如何、什么时候会失效，以及排障时应该看哪些字段。

## 当前结论

当前系统启用姿态检测：

```env
ENABLE_POSE=true
POSE_PROVIDER=yolo11_legacy
YOLO11_POSE_MODEL_PATH=models/pose_yolo_batch001_003_yolo11s_best.pt
YOLO_POSE_DEVICE=cuda:0
POSE_WORKER_FPS=2
POSE_RESULT_TTL_MS=500
```

当前真实运行的姿态 provider 是 `yolo11_legacy`。它使用 `models/pose_yolo_batch001_003_yolo11s_best.pt` 做全帧 YOLO pose 推理，再把推理出的骨架候选匹配回系统已有的 `track_id`。它不是独立判定跌倒的模型，而是给后续时序模型、状态机、融合规则、前端展示提供人体关键点证据。

一句话评价：当前姿态模型能用，而且速度相对轻，但不是“质量铁板一块”的模型。它在 link-match 评估里表现不错，可 `pose mAP50-95` 低于 `yolo11n-pose.pt` 基线；系统运行中还存在姿态跳帧、姿态过期、和 track 不同步的问题。工作人员不能把“有骨架画出来”误解成“姿态证据稳定可靠”。

## 姿态模型在系统里解决什么问题

姿态检测输出人体 17 个关键点，用于回答这些问题：

- 人体是不是低姿态：头部、髋部是否已经落到 bbox 下半部。
- 躯干角度是否异常：肩髋连线是否接近横向或倾倒。
- 骨架是否可信：关键点数量、置信度、是否落在目标框内。
- 当前骨架是否属于这个 track：通过姿态框和跟踪框的 IoU、中心距离、关键点落框比例匹配。
- UI 是否能画出骨架：前端 overlay 使用 keypoints 绘制骨架、局部框和高亮。

姿态不是最终裁判。它只是证据源之一。最终告警仍由目标检测、跌倒提示检测、跟踪、LSTM、状态机、fusion guard 共同决定。

## 当前启用模型

| 项目 | 当前值 |
|---|---|
| Provider | `yolo11_legacy` |
| 模型路径 | `models/pose_yolo_batch001_003_yolo11s_best.pt` |
| 文件大小 | 约 `19.24 MB` |
| 修改时间 | `2026-06-30 05:59:36` |
| 输入图像 | 全帧 BGR 图像 |
| 推理尺寸 | 默认 `640` |
| 置信度阈值 | 默认 `YOLO11_POSE_CONF=0.12`，当前 `.env` 未显式设置 |
| 设备 | `YOLO11_POSE_DEVICE` 未显式设置时继承 `YOLO_POSE_DEVICE=cuda:0` |
| 半精度 | 默认 `YOLO11_POSE_HALF=true`，CUDA 时启用 |
| 平滑 | 默认 `YOLO11_POSE_SMOOTHING=true` |

注意：`.env` 里设置了 `YOLO_POSE_CONFIDENCE=0.25`，但当前 provider 是 `yolo11_legacy`，核心阈值来自 `YOLO11_POSE_CONF`，默认是 `0.12`。这一点很容易误会。

## 输出格式

姿态模型最终挂到每个 `DetectedObject.pose` 字段上，典型结构如下：

```json
{
  "track_id": 12,
  "source_track_id": 12,
  "source_bbox": [x1, y1, x2, y2],
  "pose_bbox": [x1, y1, x2, y2],
  "pose_track_match_score": 0.73,
  "pose_frame_seq": 12345,
  "pose_timestamp": "2026-07-05T...",
  "keypoints": [
    {"name": "nose", "x": 100.0, "y": 80.0, "confidence": 0.91}
  ],
  "skeleton_confidence": 0.98,
  "debug": {
    "rejected_reason": null,
    "pose_match_iou": 0.57,
    "keypoint_inside_bbox_ratio": 0.96,
    "torso_inside_bbox": true
  }
}
```

系统使用 COCO-17 关键点：

| 索引 | 名称 |
|---:|---|
| 0 | `nose` |
| 1 | `left_eye` |
| 2 | `right_eye` |
| 3 | `left_ear` |
| 4 | `right_ear` |
| 5 | `left_shoulder` |
| 6 | `right_shoulder` |
| 7 | `left_elbow` |
| 8 | `right_elbow` |
| 9 | `left_wrist` |
| 10 | `right_wrist` |
| 11 | `left_hip` |
| 12 | `right_hip` |
| 13 | `left_knee` |
| 14 | `right_knee` |
| 15 | `left_ankle` |
| 16 | `right_ankle` |

下游一般只把置信度大于等于 `0.2` 的关键点当作可见关键点。膝盖和脚踝在 `yolo11_legacy` 中还会被额外严格处理，低于 `0.35` 的下肢点会被置为不可用，避免低姿态场景里用烂下肢点误导判断。

## Provider 类型

系统支持多个姿态 provider：

| Provider | 实现 | 主要特点 | 当前状态 |
|---|---|---|---|
| `yolo11_legacy` | `app/pose/yolo11_legacy_pose_estimator.py` | 全帧 YOLO pose，再匹配回 track；支持平滑 | 当前启用 |
| `yolo` / `yolo_pose` | `app/pose/yolo_pose_estimator.py` | 对目标 bbox 裁剪后跑 YOLO pose | 可用候选 |
| `branch4_legacy` | `app/pose/branch4_legacy_pose_estimator.py` | 旧版目标裁剪逻辑 | 历史候选 |
| `rtmpose_onnx` / `rtmpose` | `app/pose/rtmpose_onnx_estimator.py` | RTMPose ONNX top-down | 候选，当前路径需整理 |
| `mmpose` | `app/pose/rtmpose_estimator.py` | MMPose/RTMPose Python 栈 | 候选，重且依赖复杂 |
| `mock` | `app/pose/mock_pose_estimator.py` | 测试用假姿态 | 只适合测试 |
| `disabled_placeholder` | `app/pose/placeholders.py` | 姿态关闭时挂空占位 | 关闭姿态时使用 |

## `yolo11_legacy` 的工作方式

当前 provider 的流程如下：

1. 从跟踪结果里选出 `label == "person"` 且有 `track_id` 的目标。
2. 对整帧运行 YOLO pose。
3. 收集所有 pose candidate，每个 candidate 至少需要 5 个有效关键点。
4. 对每个 tracked person 计算候选匹配分数。
5. 通过阈值后，把 candidate 的 keypoints 挂到对应 `track_id`。
6. 对同一 track 的关键点做短时平滑，减少骨架抖动。
7. 输出 `PoseResult` 和 debug 字段。

匹配分数主要由这些因素组成：

| 因素 | 作用 |
|---|---|
| 姿态框和跟踪框 IoU | 骨架位置是否和人框重合 |
| 中心距离 | 骨架中心是否离人框中心太远 |
| 关键点落框比例 | 关键点是否大多落在目标框内 |
| skeleton confidence | 骨架自身置信度 |
| YOLO box confidence | 模型自己的检测置信度 |
| 躯干是否在框内 | 肩、髋等核心点是否合理 |

默认拒绝条件：

- `pose_track_match_score < 0.30`
- IoU 太低且中心距离太远
- 关键点落框比例 `< 0.35`
- 躯干不在框内且 IoU 低于阈值

这套逻辑的好处是能把全帧检测出的多个人体骨架绑定到正确 track；坏处是依赖跟踪框质量。如果人框错了，姿态匹配也会跟着偏。

## 当前模型指标

文件：`models/pose_yolo_batch001_003_yolo11s_metrics.json`

| 指标 | 基线 `yolo11n-pose.pt` | 当前模型 `pose_yolo_batch001_003_yolo11s_best.pt` | 差值 |
|---|---:|---:|---:|
| box precision | 0.948805 | 0.998415 | +0.049610 |
| box recall | 1.0 | 1.0 | 0 |
| box mAP50 | 0.980476 | 0.995 | +0.014524 |
| box mAP50-95 | 0.620302 | 0.764129 | +0.143827 |
| pose precision | 0.948805 | 0.998415 | +0.049610 |
| pose recall | 1.0 | 1.0 | 0 |
| pose mAP50 | 0.980476 | 0.995 | +0.014524 |
| pose mAP50-95 | 0.883491 | 0.848643 | -0.034848 |
| inference | 16.36 ms | 11.75 ms | 更快 |

解读：

- 当前模型在 bbox 相关指标和粗粒度 pose mAP50 上更好。
- 细粒度关键点质量 `pose mAP50-95` 反而低于基线。
- 推理速度更好，是当前模型的明确优点。
- 不应把当前模型宣传成“全面优于基线”，它更像是速度和场景适配上的折中。

## Link-Match 指标

文件：`models/pose_yolo_batch001_003_yolo11s_link_match_metrics.json`

测试集规模：`40` 张图。这个规模不大，只能说明趋势，不能当最终认证。

当前模型结果：

| 指标 | 数值 |
|---|---:|
| matched_rate | 1.0 |
| detached_rate | 0.0 |
| mean_candidate_iou | 0.571828 |
| mean_inside_ratio | 0.960294 |
| mean_torso_inside_ratio | 1.0 |
| mean_skeleton_confidence | 0.981012 |
| mean_keypoint_recall | 1.0 |
| mean_mean_kp_distance_ratio | 0.034471 |

解读：

- 姿态和人框绑定质量在这 40 张图上不错。
- `mean_inside_ratio`、`mean_torso_inside_ratio` 都说明关键点大多在正确人框里。
- 但 `items=40` 太少，尤其对真实场景的遮挡、多人重叠、低光、半身出画、远距离老人不够覆盖。

## Provider 性能对比

文件：`evaluations/phase10_pose_provider_comparison_001.json`

| Provider | 视频数 | 姿态帧 | 采样帧 | 平均延迟 | 平均骨架置信度 |
|---|---:|---:|---:|---:|---:|
| `yolo` | 8 | 7 | 32 | 47.24 ms | 0.8985 |
| `rtmpose_onnx` | 8 | 8 | 32 | 177.36 ms | 0.8222 |
| `mmpose_finetuned` | 8 | 8 | 32 | 224.64 ms | 0.9111 |

解读：

- YOLO pose 是实时优先选项，延迟最低。
- RTMPose ONNX 覆盖更稳，但延迟约为 YOLO 的 3.7 倍。
- MMPose 微调版骨架置信度最高，但平均延迟最重。
- 当前系统已经会因为 busy 跳过姿态推理，所以直接切更重模型会放大调度问题。

## 姿态运行调度

姿态并不是主检测线程直接同步跑。当前有独立 `PoseWorkerService`：

- `POSE_WORKER_FPS=2` 控制姿态 worker 循环频率。
- `POSE_FPS=3` 控制单 camera 内 PoseService 的最小推理间隔。
- 姿态依赖最近 tracking 快照和 detection frame。
- 如果 detection frame 与 tracking frame 相差超过 `POSE_MAX_TRACKING_FRAME_DELTA=2`，拒绝。
- 如果 detection frame 年龄超过 `POSE_MAX_FRAME_AGE_MS=500`，拒绝。
- 如果推理锁被占用，且 `POSE_SKIP_WHEN_INFERENCE_BUSY=true`，直接跳过本次姿态。
- 如果连续慢推理超过阈值，会打开 circuit breaker，冷却 `10000 ms`。

这意味着“没有姿态”不一定是模型没识别出来，也可能是：

- 没有 tracking；
- tracking 和 detection 不同步；
- frame 太旧；
- 推理锁忙；
- provider 被关闭；
- 模型加载失败；
- 姿态结果被匹配规则拒绝。

## 质量门槛与拒绝原因

常见 debug 字段：

| 字段 | 含义 |
|---|---|
| `rejected_reason` | 姿态被拒绝的原因 |
| `keypoint_inside_bbox_ratio` | 关键点落在目标框内比例 |
| `candidate_iou` / `pose_match_iou` | 姿态框与目标框重合度 |
| `pose_match_center_distance_ratio` | 姿态中心与目标中心距离比例 |
| `torso_inside_bbox` | 肩髋等躯干点是否在框内 |
| `skeleton_confidence` | 骨架平均置信度 |
| `pose_frame_seq` | 姿态使用的图像帧序号 |
| `tracking_frame_seq` | 匹配的跟踪帧序号 |
| `pose_frame_age_ms` | 姿态帧年龄 |
| `pose_model_path` | 实际加载的模型路径 |

常见拒绝原因：

| 原因 | 解释 |
|---|---|
| `no_tracking` | 没有可用跟踪对象 |
| `frame_tracking_desync` | detection frame 和 tracking frame 不同步 |
| `pose_frame_stale` | 姿态可用图像太旧 |
| `no_keypoints` | 模型没输出关键点 |
| `pose_track_match_low_score` | 姿态候选无法可靠绑定 track |
| `pose_track_mismatch` | 输出 track 与对象 track 不一致 |
| `low_skeleton_confidence` | 骨架置信度太低 |
| `keypoints_outside_bbox` | 关键点大多不在目标框内 |
| `candidate_bbox_mismatch` | 姿态框和目标框不匹配 |
| `torso_outside_bbox` | 躯干关键点不在目标框内 |

## 当前模型的主要问题

1. 评估样本偏少  
   Link-match 只有 40 张图，provider 对比只有 8 个视频、32 个采样帧。这些指标适合做方向判断，不适合做上线背书。

2. 当前模型不是全面超越基线  
   当前 YOLO11s 模型速度更好、框指标更好，但 `pose mAP50-95` 低于 `yolo11n-pose.pt`。关键点精细程度存在损失。

3. 姿态有效率受系统调度影响  
   旧 e2e 记录里 `pose_valid=0.3`，并出现大量 busy skip。这不是单纯换模型能解决的，需要看 worker FPS、推理锁、GPU 占用、frame 同步。

4. 配置容易误读  
   当前 provider 是 `yolo11_legacy`，但 `.env` 里更多显式配置是 `YOLO_POSE_*`。部分配置不会按工作人员直觉生效。

5. RTMPose 路径不干净  
   `.env.example` 和 README 中提到的部分 RTMPose ONNX 路径当前不存在。`rtmpose-m-body7-256x192.zip` 里有 `end2end.onnx`，但还没有解压到推荐运行路径。

## 工作人员排障清单

先看状态接口或日志里的 PoseStatus：

- `pose_enabled` 是否为 true。
- `pose_provider` 是否是预期的 `yolo11_legacy`。
- `pose_model_path` 是否指向 `models/pose_yolo_batch001_003_yolo11s_best.pt`。
- `last_error` 是否为空。
- `skipped_due_to_busy` 是否持续增长。
- `pose_frame_seq` 和 `tracking_frame_seq` 差值是否超过 2。
- `pose_frame_age_ms` 是否超过 500。
- `rejected_reason` 是否频繁出现。

再看目标对象里的 pose：

- `keypoints` 是否为空。
- `skeleton_confidence` 是否过低。
- `source_track_id` 是否等于对象 `track_id`。
- `pose_bbox` 是否明显偏离 `source_bbox`。
- `debug.keypoint_inside_bbox_ratio` 是否过低。

最后看系统层面：

- 人体检测是否漏人。
- ByteTrack 是否频繁换 ID。
- GPU 是否被检测模型和姿态模型抢占。
- 前端看到骨架消失时，确认是不是结果 TTL 到期，而不是模型突然变差。

## 建议

- 把 `YOLO11_POSE_CONF`、`YOLO11_POSE_IMGSZ`、`YOLO11_POSE_HALF`、`YOLO11_POSE_SMOOTHING` 显式写入 `.env`，减少误解。
- 用真实摄像头回放重新评估 `pose_valid`、`skipped_due_to_busy`、`frame_tracking_desync` 和 `pose_frame_stale` 分布。
- 建立一份至少覆盖多人、遮挡、坐下、弯腰、蹲跪、躺卧、跌倒、半身出画的姿态测试集。
- 如果考虑 RTMPose，需要先解决模型路径、ONNX 解压、worker 调度和延迟预算，再谈替换。
- 不建议只看骨架是否“画得漂亮”。系统真正需要的是：关键点是否稳定进入 LSTM 和 fusion，且不会把 ADL 动作误导成跌倒。

## 参考文件

- `app/services/pose_service.py`
- `app/services/pose_worker_service.py`
- `app/pose/yolo11_legacy_pose_estimator.py`
- `app/pose/yolo_pose_estimator.py`
- `app/pose/schemas.py`
- `app/pose/placeholders.py`
- `app/temporal/target_feature_extractor.py`
- `app/temporal/feature_vectorizer.py`
- `models/pose_yolo_batch001_003_yolo11s_metrics.json`
- `models/pose_yolo_batch001_003_yolo11s_link_match_metrics.json`
- `evaluations/phase10_pose_provider_comparison_001.json`
