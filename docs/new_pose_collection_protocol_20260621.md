# New Pose Collection Protocol

日期: `2026-06-21`

仓库: `D:\Program\vision_service`

协议版本: `new_pose_raw_session_v1`

## 目标

本协议定义新 Pose 现场采集的动作覆盖、最小采样要求、元数据标准与质量检查规则。

## 采集前约束

采集阶段必须保持:

- `runtime_profile=current_camera_live`
- `pose_enabled=false`
- `pose_provider=disabled_placeholder`

采集阶段禁止:

- 重新接入真实 Pose runtime
- 修改当前 `8000` 正式 no-pose 链路
- 边采集边调参

## 动作类别覆盖表

| action_id | action_name | purpose | duration_sec | repeats | camera_position | person_position | safety_notes | annotation_priority | expected_pose_difficulty | train | val | test | hard_case |
| --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | no_person | 建立空场负样本 | 20 | 3 | 固定 | 无人 | 无 | 中 | 低 | 否 | 是 | 是 | 是 |
| 02 | standing_front | 正面站立基线 | 30 | 3 | 固定 | 中央 | 无 | 高 | 低 | 是 | 是 | 是 | 否 |
| 03 | standing_side | 侧身站立基线 | 30 | 3 | 固定 | 中央 | 无 | 高 | 中 | 是 | 是 | 是 | 否 |
| 04 | standing_back | 背身站立基线 | 30 | 3 | 固定 | 中央 | 无 | 中 | 中 | 是 | 是 | 是 | 否 |
| 05 | walking_slow | 慢走动态样本 | 30 | 3 | 固定 | 中央至横向移动 | 保持全身入镜 | 高 | 中 | 是 | 是 | 是 | 否 |
| 06 | sitting_normal | 正常坐姿误报保护 | 30 | 3 | 固定 | 中央 | 椅子稳定 | 高 | 中 | 是 | 是 | 是 | 是 |
| 07 | sitting_side | 侧坐姿态变化 | 30 | 3 | 固定 | 中央 | 椅子稳定 | 高 | 中 | 是 | 是 | 是 | 是 |
| 08 | bending_pickup | 弯腰拾物误报保护 | 30 | 3 | 固定 | 中央 | 缓慢动作 | 高 | 高 | 是 | 是 | 是 | 是 |
| 09 | squat | 深蹲/半蹲 | 30 | 3 | 固定 | 中央 | 缓慢起落 | 高 | 高 | 是 | 是 | 是 | 是 |
| 10 | lying_side | 侧躺静态样本 | 30 | 3 | 固定 | 中央 | 软垫保护 | 高 | 高 | 是 | 是 | 是 | 是 |
| 11 | lying_back | 仰躺静态样本 | 30 | 3 | 固定 | 中央 | 软垫保护 | 高 | 高 | 是 | 是 | 是 | 是 |
| 12 | lying_prone | 俯卧静态样本 | 30 | 3 | 固定 | 中央 | 软垫保护 | 中 | 高 | 是 | 是 | 是 | 是 |
| 13 | fall_simulated_side | 模拟侧向跌倒 | 20 | 3 | 固定 | 中央 | 只做可控模拟 | 高 | 高 | 是 | 是 | 是 | 是 |
| 14 | fall_simulated_back | 模拟后仰跌倒 | 20 | 3 | 固定 | 中央 | 只做可控模拟 | 高 | 高 | 是 | 是 | 是 | 是 |
| 15 | fallen_hold | 倒地保持 | 30 | 3 | 固定 | 中央 | 软垫保护 | 高 | 高 | 是 | 是 | 是 | 是 |
| 16 | recovery_standing | 起身恢复 | 20 | 3 | 固定 | 中央 | 缓慢起身 | 高 | 高 | 是 | 是 | 是 | 是 |
| 17 | partial_occlusion | 部分遮挡 | 20 | 3 | 固定 | 中央 | 遮挡不遮头躯干全体 | 中 | 高 | 是 | 否 | 是 | 是 |
| 18 | near_edge | 靠近画面边界 | 20 | 3 | 固定 | 左侧/右侧 | 保持安全距离 | 高 | 高 | 是 | 否 | 是 | 是 |
| 19 | low_light | 低照度 | 20 | 2 | 固定 | 中央 | 保证可见 | 中 | 高 | 是 | 否 | 是 | 是 |
| 20 | far_distance | 远距离 | 20 | 3 | 固定 | 远处 | 全身入镜 | 中 | 高 | 是 | 否 | 是 | 是 |
| 21 | close_distance | 近距离 | 20 | 3 | 固定 | 近处 | 不贴镜头 | 中 | 高 | 是 | 否 | 是 | 是 |
| 22 | loose_clothes | 宽松衣物 | 20 | 2 | 固定 | 中央 | 动作保守 | 中 | 高 | 是 | 否 | 是 | 是 |
| 23 | dark_clothes | 深色衣物 | 20 | 2 | 固定 | 中央 | 光照稳定 | 中 | 中 | 是 | 否 | 是 | 是 |
| 24 | bright_clothes | 亮色衣物 | 20 | 2 | 固定 | 中央 | 光照稳定 | 中 | 中 | 是 | 否 | 是 | 是 |

## 最低采集量建议

- 每个核心动作至少 `3` 段
- 每段建议 `20` 到 `60` 秒
- `sitting` / `bending` / `squat` 必须单独采
- `fallen_hold` 至少覆盖侧躺、仰躺、俯卧
- `recovery_standing` 必须独立记录
- 跌倒动作必须为安全模拟，不做危险真摔

## 现场 metadata.json 标准

模板如下:

```json
{
  "schema_version": "new_pose_raw_session_v1",
  "session_id": "session_YYYYMMDD_HHMMSS_action",
  "camera_id": "camera_01",
  "source_url_masked": "rtsp://admin:***@192.168.x.x:10554/tcp/av0_1",
  "recorded_at": "",
  "recorded_by": "",
  "runtime_profile": "current_camera_live",
  "pose_provider": "disabled_placeholder",
  "pose_enabled": false,
  "resolution": "",
  "fps": null,
  "duration_sec": null,
  "action_labels": [],
  "primary_action": "",
  "person_count": 1,
  "scene": "indoor",
  "lighting": "normal",
  "camera_view": "",
  "person_clothing": "",
  "has_occlusion": false,
  "has_near_edge": false,
  "safety_notes": "",
  "privacy_notes": "",
  "quality_notes": "",
  "usable_for_training": null,
  "usable_for_eval": null,
  "hard_case": false
}
```

要求:

- `source_url_masked` 不能包含明文密码
- `action_labels` 必须来自标准动作列表
- `pose_provider` 必须记录为 `disabled_placeholder`
- 不记录真实姓名等敏感身份信息

## 质量检查规则

一段 raw session 至少检查:

1. 是否有 `metadata.json`
2. 是否有标准动作标签
3. 是否有 `video.mp4`
4. 是否有 `notes.md`
5. `source_url_masked` 是否脱敏
6. `duration_sec` 是否合理
7. 是否存在明显隐私泄漏
8. 是否全身基本入镜
9. 是否能识别出主要动作

## 分类原则

### A 类

适合训练候选:

- 画面清晰
- 人体完整
- 动作明确
- 有原始视频或连续帧
- 标签可明确补全

### B 类

适合评估候选:

- 可用于 visual review
- 可用于难例回放
- 但不一定满足训练级 raw 规范

### C 类

适合故障复盘:

- 只有 jsonl 或少量截图
- 缺少原视频
- 适合解释系统问题，不适合直接训练

### D 类

不建议使用:

- 动作标签混乱
- 隐私风险高
- 内容不完整
- 无法确认场景

## 推荐后续动作

1. 先按本协议手工采一轮标准 raw session。
2. 再进入 Phase 4 抽帧与筛样。
3. 再进入 Phase 5 标注规范与 QA。

在此之前，不要启用真实 Pose runtime。
