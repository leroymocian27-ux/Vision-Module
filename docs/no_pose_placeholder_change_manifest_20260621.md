# No-Pose Placeholder Change Manifest

日期: `2026-06-21`

仓库: `D:\Program\vision_service`

当前分支: `feature/new-pose-reintegration`

基线提交: `c6da604`

## 目标

本清单用于冻结当前 `no-pose placeholder runtime` 的已知事实，作为后续新 Pose 训练与重接入工作的安全基线。后续所有新 Pose 工作都必须在不破坏这条基线的前提下推进。

## 当前运行基线

基于 `http://127.0.0.1:8000/status?camera_id=camera_01` 的最新只读检查，当前运行状态为:

- `pose.pose_enabled=false`
- `pose.pose_provider=disabled_placeholder`
- `pose.pose_pipeline_removed=true`
- `main_stream.stream_state=connected`
- `main_stream.capture_fps=9.15`
- `main_stream.frame_age_ms=47.0`
- `latest_result.latest_objects_count=0`
- `latest_result.pose_available=false`
- `polling_alert.status=no_alert`

这说明当前 `8000` 实例仍运行在安全的 `no-pose` 模式，主链路未重新接回旧骨架推理。

## 本轮确认的 no-pose 相关文件

以下文件属于当前 no-pose / placeholder 主链路的关键边界，后续新 Pose 研发不得直接破坏其默认行为:

- [app/pose/placeholders.py](/D:/Program/vision_service/app/pose/placeholders.py)
- [app/services/pose_service.py](/D:/Program/vision_service/app/services/pose_service.py)
- [app/services/pose_worker_service.py](/D:/Program/vision_service/app/services/pose_worker_service.py)
- [app/services/stream_service.py](/D:/Program/vision_service/app/services/stream_service.py)
- [app/services/temporal_service.py](/D:/Program/vision_service/app/services/temporal_service.py)
- [app/temporal/target_feature_extractor.py](/D:/Program/vision_service/app/temporal/target_feature_extractor.py)
- [app/services/result_publisher_service.py](/D:/Program/vision_service/app/services/result_publisher_service.py)
- [app/services/status_service.py](/D:/Program/vision_service/app/services/status_service.py)
- [app/schemas/status.py](/D:/Program/vision_service/app/schemas/status.py)
- [app/pose/schemas.py](/D:/Program/vision_service/app/pose/schemas.py)
- [frontend_demo/overlay.js](/D:/Program/vision_service/frontend_demo/overlay.js)
- [frontend_demo/app.js](/D:/Program/vision_service/frontend_demo/app.js)
- [scripts/start_current_camera.py](/D:/Program/vision_service/scripts/start_current_camera.py)
- [tests/test_pose_service.py](/D:/Program/vision_service/tests/test_pose_service.py)
- [tests/test_temporal_service.py](/D:/Program/vision_service/tests/test_temporal_service.py)
- [tests/test_result_publisher_service.py](/D:/Program/vision_service/tests/test_result_publisher_service.py)
- [tests/test_end_to_end_pipeline.py](/D:/Program/vision_service/tests/test_end_to_end_pipeline.py)
- [tests/test_pose_service_provider_selection.py](/D:/Program/vision_service/tests/test_pose_service_provider_selection.py)

## 默认运行约束

当前默认行为必须保持不变:

- `ENABLE_POSE=false`
- `POSE_PROVIDER=disabled_placeholder`
- 前端只显示 placeholder，不绘制真实 skeleton
- Temporal 主链路允许 bbox-only 运行
- 新 Pose 不允许直接参与 `fallen_confirmed`
- 新 Pose 不允许直接生成 `incident_id`

## 工作树风险评估

当前工作树不是干净基线，不能安全地直接制作“只包含 no-pose 改动”的提交。

原因:

- `git status --short` 显示大量已修改文件和未跟踪文件
- 其中包含 Pose、Temporal、Result、Frontend、脚本、测试、文档等多个维度
- 这些改动并不都属于本轮 no-pose 保护工作

风险等级:

- `dirty_worktree_risk=HIGH`

结论:

- 本轮适合先产出 manifest 和计划文档
- 暂不建议在当前工作树上直接整理 `refactor: disable pose pipeline and use skeleton placeholders` 独立提交

## 隔离原则

后续新 Pose 工作必须遵守:

1. 不回滚旧 Pose live runtime。
2. 不复用旧“漂移骨架”链路作为正式入口。
3. 所有新 Pose 代码必须优先放在独立目录和独立 provider / adapter 中。
4. 新 Pose 默认关闭，必须显式启用。
5. 新 Pose 先 `display-only`，再 `shadow-only`，最后才允许进入受控融合设计。

## 推荐的新工作边界

已创建的新工作目录:

- [tools/new_pose_dataset](/D:/Program/vision_service/tools/new_pose_dataset)
- [tools/new_pose_training](/D:/Program/vision_service/tools/new_pose_training)
- [tools/new_pose_eval](/D:/Program/vision_service/tools/new_pose_eval)
- [tools/new_pose_export](/D:/Program/vision_service/tools/new_pose_export)
- [models/new_pose/releases](/D:/Program/vision_service/models/new_pose/releases)
- [docs/new_pose](/D:/Program/vision_service/docs/new_pose)
- [app/pose/adapters](/D:/Program/vision_service/app/pose/adapters)
- [app/pose/providers](/D:/Program/vision_service/app/pose/providers)

## 验收记录

【Phase 0 No-Pose Baseline Protection Result】

commit_before:
`c6da604`

no_pose_changes_isolated:
`FAIL`

dirty_worktree_risk:
`HIGH`

no_pose_runtime_smoke:
`PASS`

tests:
`NOT_RUN in this turn`

recommended_action:
`ReadyForNewPoseBranch`

## 下一步

建议立即进入:

1. `docs/new_pose_reintegration_plan_20260621.md`
2. `docs/new_pose_contract_20260621.md`
3. `app/pose/new_pose_schema.py`

在这些产物完成前，不要直接恢复任何真实骨架推理到当前 live runtime。
