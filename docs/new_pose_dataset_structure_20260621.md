# New Pose Dataset Structure

日期: `2026-06-21`

仓库: `D:\Program\vision_service`

## 目标

本文件定义新 Pose 数据资产的目录边界，保证后续采集、抽帧、标注、训练彼此解耦，并且不污染当前 `no-pose placeholder runtime`。

## 一级目录

建议统一使用以下三层数据目录:

1. `datasets/new_pose_raw/`
2. `datasets/new_pose_frames/`
3. `datasets/new_pose_coco/`

职责划分:

- `new_pose_raw` 只保存原始采集材料
- `new_pose_frames` 只保存从 raw 抽取的图像和抽帧清单
- `new_pose_coco` 只保存标注转换后的训练输入

## Raw 目录规范

推荐结构:

```text
datasets/new_pose_raw/
  camera_01/
    session_YYYYMMDD_HHMMSS_action/
      video.mp4
      preview.gif
      metadata.json
      action_script.md
      notes.md
      status_samples.jsonl
      integration_latest_samples.jsonl
      frames_optional/
      qa_report.md
```

说明:

- `video.mp4` 是原始采集视频
- `preview.gif` 是快速回看预览
- `metadata.json` 是该 session 的标准元数据
- `action_script.md` 记录本次采集动作脚本
- `notes.md` 记录现场备注和异常
- `status_samples.jsonl` 保存采样状态
- `integration_latest_samples.jsonl` 保存集成侧采样
- `frames_optional/` 仅允许保存临时补充帧，不代替后续正式抽帧目录
- `qa_report.md` 保存该 session 的原始质检结论

## Frames 目录规范

推荐结构:

```text
datasets/new_pose_frames/
  camera_01/
    session_YYYYMMDD_HHMMSS_action/
      images/
      frame_manifest.jsonl
```

说明:

- `images/` 由抽帧脚本自动生成
- `frame_manifest.jsonl` 记录图像与原视频、时间戳、动作标签的映射
- 不允许直接手工把 raw 视频帧散落到其他位置

## COCO 目录规范

推荐结构:

```text
datasets/new_pose_coco/
  images/
  annotations/
  train.json
  val.json
  test.json
  dataset_report.md
```

说明:

- `images/` 存放训练引用图像
- `annotations/` 存放中间标注文件
- `train.json` / `val.json` / `test.json` 为最终 COCO 拆分文件
- `dataset_report.md` 记录分布、质检和泄漏检查

## 命名约束

Session 统一命名为:

```text
session_YYYYMMDD_HHMMSS_action
```

例如:

```text
session_20260621_153000_standing_front
session_20260621_161500_fall_simulated_side
```

命名要求:

- 时间使用本地采集时间
- `action` 必须来自标准动作列表
- 不允许自由拼写导致动作标签漂移

## Raw 数据保护规则

1. `new_pose_raw` 中的视频不允许人工重编码覆盖原文件。
2. 如果要裁剪、抽帧、转码，必须产出到 `new_pose_frames` 或其他下游目录。
3. `metadata.json` 必须存在，且 RTSP 地址必须脱敏。
4. raw 数据默认仅本地使用，不允许直接外传。
5. 不记录真实姓名、身份证、手机号等无关个人信息。

## 与当前 no-pose 链路的关系

本目录结构只用于数据工作流，不代表启用真实 Pose。

当前正式默认仍必须保持:

- `ENABLE_POSE=false`
- `POSE_PROVIDER=disabled_placeholder`

本文件不要求:

- 启用 Pose runtime
- 修改 `8000` 服务
- 修改前端或跌倒判断逻辑
