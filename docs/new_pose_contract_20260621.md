# New Pose Contract

日期: `2026-06-21`

仓库: `D:\Program\vision_service`

契约版本: `new_pose_v1`

## 1. 目的

先定义统一接口，再训练模型、写 Adapter、接前端。模型格式不能反向污染系统架构。

本契约用于:

- 新 Pose provider 输出
- Adapter 和 provider 之间的边界
- Frontend display-only 渲染
- Shadow feature 记录
- 后续受控融合的输入

本契约不用于:

- 直接生成 `fallen_confirmed`
- 直接生成 `incident_id`
- 直接生成正式告警

## 2. 与 placeholder 的兼容要求

新 Pose 输出必须保留与现有 placeholder 兼容的核心字段形状，保证:

- `pose` 字段始终存在固定结构
- 即使 `pose_available=false` 也能返回完整字段
- Result / Status / WebSocket / Frontend 不因字段缺失崩溃

最小兼容字段:

- `pose_provider`
- `track_id`
- `source_track_id`
- `source_bbox`
- `pose_bbox`
- `pose_frame_seq`
- `pose_timestamp`
- `keypoints`
- `skeleton_confidence`
- `debug`

## 3. 坐标与关键点规范

### 3.1 关键点格式

统一采用 `COCO17`:

0. `nose`
1. `left_eye`
2. `right_eye`
3. `left_ear`
4. `right_ear`
5. `left_shoulder`
6. `right_shoulder`
7. `left_elbow`
8. `right_elbow`
9. `left_wrist`
10. `right_wrist`
11. `left_hip`
12. `right_hip`
13. `left_knee`
14. `right_knee`
15. `left_ankle`
16. `right_ankle`

### 3.2 坐标口径

必须明确:

- `x` / `y` 为原图坐标，不是 crop 内坐标
- 单位为像素
- `source_bbox` 为原图 `person bbox`
- `crop_bbox` 为执行 pose 推理时使用的 ROI bbox
- `pose_bbox` 为基于有效关键点计算出的姿态包围框

### 3.3 置信度口径

- `confidence` 范围为 `0.0 ~ 1.0`
- `skeleton_confidence` 为整套骨架的聚合质量分数
- `quality_score` 为后处理质量分数，不等于模型原始概率

## 4. 有效点规则

`valid=false` 的点:

- 不参与前端绘制
- 不参与 `pose_bbox` / `pose_bounds` 计算
- 不参与下游姿态特征计算
- 允许保留在 `keypoints` 中用于 debug

推荐原因字段:

- `low_confidence`
- `edge_clamped`
- `out_of_frame`
- `missing_from_model`
- `quality_gate_rejected`
- `restoration_error`

## 5. 输入契约

新 Pose Adapter 的输入至少应包含:

```json
{
  "camera_id": "camera_01",
  "frame_seq": 12345,
  "timestamp": "2026-06-21T03:24:04.702+00:00",
  "runtime_profile": "current_camera_live",
  "pose_provider": "new_pose_v1",
  "track_id": 8,
  "source_bbox": [100.0, 80.0, 260.0, 340.0],
  "crop_bbox": [88.0, 64.0, 272.0, 352.0],
  "previous_pose": null
}
```

## 6. 输出契约

标准输出结构:

```json
{
  "pose_provider": "new_pose_v1",
  "pose_enabled": true,
  "pose_available": false,
  "track_id": 8,
  "source_track_id": 8,
  "source_bbox": [100.0, 80.0, 260.0, 340.0],
  "crop_bbox": [88.0, 64.0, 272.0, 352.0],
  "pose_bbox": null,
  "keypoint_format": "coco17",
  "keypoint_count": 17,
  "valid_keypoint_count": 0,
  "visible_keypoint_count": 0,
  "filtered_keypoints_count": 0,
  "dropped_keypoints_count": 0,
  "dropped_reasons": {},
  "keypoints": [],
  "skeleton_confidence": 0.0,
  "quality_score": 0.0,
  "pose_frame_seq": 12345,
  "pose_timestamp": "2026-06-21T03:24:04.702+00:00",
  "debug": {
    "adapter": "new_pose_adapter",
    "model_name": "TBD",
    "model_version": "TBD",
    "roi_crop": true,
    "coordinate_restored": true,
    "postprocess_version": "v1",
    "shadow_only": true,
    "use_for_fall": false,
    "fallback_used": false
  }
}
```

## 7. Shadow-only 约束

新 Pose 初期必须满足:

- `shadow_only=true`
- `use_for_fall=false`

同时明确禁止:

- 新 Pose 直接输出 `fallen_confirmed`
- 新 Pose 直接输出 `alarm_confirmed=true`
- 新 Pose 直接生成 `incident_id`
- 新 Pose 直接触发 `snapshot`

## 8. Frontend 使用规则

前端只允许:

- 当 `pose_provider=new_pose_v1`
- 且 `pose_available=true`
- 且关键点 `valid=true`
- 且 `confidence` 达到渲染阈值

才绘制骨架。

前端禁止:

- 使用无效点连线
- 复用旧 pose cache
- 将 stale pose 画到新 bbox
- 用 pose 是否可见来直接影响 fall state 展示

## 9. Debug 字段建议

为后续评估与问题定位，建议 `debug` 至少包含:

- `adapter`
- `adapter_version`
- `model_name`
- `model_version`
- `roi_crop`
- `crop_bbox`
- `source_bbox`
- `coordinate_restored`
- `inference_ms`
- `valid_keypoint_count`
- `visible_keypoint_count`
- `quality_score`
- `shadow_only`
- `use_for_fall`
- `fallback_used`
- `error`

## 10. 推荐 schema 文件

对应的独立 schema 文件:

- [app/pose/new_pose_schema.py](/D:/Program/vision_service/app/pose/new_pose_schema.py)

该文件只定义契约，不改变当前默认 provider 选择逻辑。

## 11. 验收记录

【Phase 2 New Pose Contract Result】

contract_doc:
[docs/new_pose_contract_20260621.md](/D:/Program/vision_service/docs/new_pose_contract_20260621.md)

keypoint_format:
`COCO17`

schema_added:
`PASS`

placeholder_compatible:
`PASS`

shadow_only_default:
`PASS`

recommended_action:
`ReadyForDatasetPlan`
