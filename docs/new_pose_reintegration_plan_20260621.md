# New Pose Re-Integration Plan

日期: `2026-06-21`

仓库: `D:\Program\vision_service`

当前分支: `feature/new-pose-reintegration`

当前正式基线: `no-pose placeholder runtime`

## 1. 计划目标

本计划的目标不是“快速把骨架画回来”，而是重新建立一套可控、可验证、可灰度、可回滚的新 Pose 研发与接入路径。

最终目标包括:

1. 为当前摄像头场景训练或适配一个新的姿态模型。
2. 让新 Pose 先用于显示与分析，再用于 shadow 特征，再考虑受控辅助跌倒判断。
3. 在整个过程中不破坏当前 `disabled_placeholder` 的正式运行链路。

## 2. 当前基线

当前正式系统已经进入 `no-pose` 模式:

- 后端不再输出真实 keypoints
- 前端不再绘制真实 skeleton
- Temporal 已支持 bbox-only 模式
- Result / Integration / Status / WebSocket 仍保持兼容字段
- 跌倒检测主链路继续运行

当前正式默认值必须保持:

- `ENABLE_POSE=false`
- `POSE_PROVIDER=disabled_placeholder`

## 3. 核心设计原则

### 3.1 与旧 Pose 彻底隔离

新 Pose 不能直接复用旧 live pose 主链路，也不能把历史“骨架漂移”实现重新设为默认 provider。

### 3.2 与正式告警解耦

新 Pose 初期只能做:

- skeleton 显示
- debug 输出
- shadow feature 记录
- 误报解释或抑制辅助

新 Pose 初期不能做:

- 直接输出 `fallen_confirmed`
- 直接设置 `alarm_confirmed=true`
- 直接生成 `incident_id`
- 直接触发 `snapshot`

### 3.3 渐进接入

新 Pose 必须按以下顺序推进:

1. 数据审计
2. 数据采集
3. 标注规范
4. 模型选择
5. 训练工程
6. 导出与推理
7. Adapter 接入
8. 前端 display-only
9. 只读评估
10. shadow feature
11. controlled fusion design
12. gated fusion experiment
13. staging acceptance
14. rollback safety

## 4. 工作空间边界

本分支中，新 Pose 工作优先使用以下目录:

- [tools/new_pose_dataset](/D:/Program/vision_service/tools/new_pose_dataset)
- [tools/new_pose_training](/D:/Program/vision_service/tools/new_pose_training)
- [tools/new_pose_eval](/D:/Program/vision_service/tools/new_pose_eval)
- [tools/new_pose_export](/D:/Program/vision_service/tools/new_pose_export)
- [models/new_pose/releases](/D:/Program/vision_service/models/new_pose/releases)
- [docs/new_pose](/D:/Program/vision_service/docs/new_pose)
- [app/pose/adapters](/D:/Program/vision_service/app/pose/adapters)
- [app/pose/providers](/D:/Program/vision_service/app/pose/providers)

约束:

- 不删除 `disabled_placeholder`
- 不把 `new_pose_v1` 设为默认 provider
- 不直接改写当前正式 no-pose 行为

## 5. 新 Pose 输入输出边界

新 Pose 的最小输入应包括:

- `frame`
- `frame_seq`
- `timestamp`
- `camera_id`
- `track_id`
- `source_bbox`
- `crop_bbox`
- `runtime_profile`
- `pose_provider`
- `optional previous_pose`

新 Pose 的统一输出应保持与 placeholder 兼容的核心字段形状:

- `pose_provider`
- `pose_enabled`
- `pose_available`
- `keypoints`
- `pose_bbox`
- `source_bbox`
- `crop_bbox`
- `track_id`
- `source_track_id`
- `pose_frame_seq`
- `pose_timestamp`
- `debug`

推荐格式:

- `keypoint_format=coco17`
- 坐标为原图像素坐标
- `valid=false` 的点不能参与绘制和特征
- `shadow_only=true` 作为新 provider 默认值

## 6. 数据计划

### 6.1 数据审计

先识别我们真正缺哪些样本，而不是直接开始训练。重点检查:

- 站立
- 坐姿
- 地面坐姿
- 跪姿
- 趴地支撑
- 侧躺 / 仰躺 / 俯卧
- 跌倒过渡
- 恢复站立
- 近边界
- 遮挡
- 光照变化

### 6.2 数据采集

建议数据根目录:

- `datasets/new_pose_raw/`
- `datasets/new_pose_frames/`
- `datasets/new_pose_coco/`

每个 session 建议保存:

- 原始视频
- 抽帧结果
- `metadata.json`
- `action_script.md`
- `status_samples.jsonl`

## 7. 标注规范

建议统一采用 COCO17，并明确:

- 不可见点不强行猜点
- 边界截断点标记为不可见或缺失
- 腿部与手臂被遮挡时必须保守标注
- 不为“骨架完整好看”而制造错误监督

## 8. 模型路线建议

当前先不锁死具体模型，只定义选择标准:

- 能稳定导出
- 能在本地实时推理
- 对 ROI crop 友好
- 对腿部、边界、侧躺场景更稳
- 能给出稳定的 per-keypoint confidence

可比较路线:

- YOLO Pose 路线
- RTMPose 路线
- 其他轻量可导出姿态模型

## 9. Adapter 接入计划

新 Pose 接入不走旧 provider 复活路线，而是新增独立 provider / adapter:

- `POSE_PROVIDER=new_pose_v1`
- `POSE_SHADOW_ONLY=true`
- `POSE_USE_FOR_FALL=false`

接入职责:

1. 基于 `target bbox` 做 ROI crop。
2. 模型输出恢复到原图坐标。
3. 统一输出新 Pose 契约。
4. 允许失败时回退到 placeholder。
5. 默认不参与 fall decision。

## 10. 前端与只读评估计划

前端分两层:

1. `disabled_placeholder` 时继续显示 placeholder。
2. `new_pose_v1 + pose_available=true` 时只做 display-only 绘制。

前端绘制必须遵守:

- 只画 `valid=true` 且 confidence 达标的点
- 任一 limb 端点无效，则不画该 limb
- 不复用旧 pose cache
- 不把 stale pose 画到新 bbox 上

## 11. shadow 与融合计划

新 Pose 的演进顺序必须是:

1. `display-only`
2. `shadow-only feature logging`
3. `assist-only / gated_assist`

禁止模式:

- `pose_direct_confirm`
- `pose_only_confirm`
- `keypoints_only_fall`

允许的长期方向:

- 帮助压制明显 upright 的误报
- 帮助解释低姿态但非跌倒的场景
- 帮助做质量门控，而不是直接替代主链路

## 12. 回滚方案

回滚必须非常简单:

- `ENABLE_POSE=false`
- `POSE_PROVIDER=disabled_placeholder`

并要求:

- 模型加载失败可 fallback
- 推理超时可 fallback
- 输出非法可 fallback
- 前端收到 fallback 不崩溃
- fall pipeline 在 pose failure 时继续生存

## 13. 本轮交付范围

本轮只完成 Phase 0/1/2 的基础产物:

1. no-pose 基线清单
2. 新 Pose 重接入计划
3. 新 Pose 输出契约
4. 独立 schema 文件

本轮不做:

- 数据采集
- 模型训练
- 导出部署
- live pose 接回
- 告警逻辑联动

## 14. 验收记录

【Phase 1 New Pose Workspace Result】

branch:
`feature/new-pose-reintegration`

created_dirs:

- `tools/new_pose_dataset/`
- `tools/new_pose_training/`
- `tools/new_pose_training/config/`
- `tools/new_pose_eval/`
- `tools/new_pose_export/`
- `models/new_pose/releases/`
- `docs/new_pose/`
- `app/pose/adapters/`
- `app/pose/providers/`

created_docs:

- [docs/new_pose_reintegration_plan_20260621.md](/D:/Program/vision_service/docs/new_pose_reintegration_plan_20260621.md)

no_pose_default_unchanged:
`PASS`

recommended_action:
`ReadyForPoseContract`
