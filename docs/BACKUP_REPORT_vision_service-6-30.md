# vision_service-6-30 备份说明

备份时间：2026-07-01  
源项目路径：`D:\Program\vision_service`  
目标压缩包：`D:\Program\vision_service-6-30.zip`

## 1. 备份目的

本次备份用于保存当前实时跌倒检测系统的核心状态，便于后续回档、迁移或交接给其他工作人员。

当前系统已经完成的核心内容包括：

- 视频主通道 + AI 旁路异步分析链路。
- YOLO person / YOLO Fall Hint / ByteTrack / Pose / LSTM / Fusion / 主系统告警链路。
- 前端 WebRTC + WebSocket + canvas overlay。
- Fall Hint 模型升级及指标记录。
- Person / Pose 数据集准备、标注、训练、评估脚本。
- 本地 Git 回档提交和 tag。
- 完整交接文档。

## 2. 当前 Git 状态

当前分支：

```text
feature/pose-model-qualification
```

当前本地回档提交：

```text
6c6a37a checkpoint: realtime fall pipeline and model tooling
```

当前本地回档标签：

```text
checkpoint-realtime-fall-pipeline-20260630
```

当前 GitHub 上传状态：

```text
本地 ahead 1，当前版本尚未成功推送到 GitHub。
```

原因：

```text
访问 github.com:443 出现连接超时 / connection reset。
```

本地 Git bundle 备份：

```text
backups/vision_service_checkpoint_realtime_fall_pipeline_20260630.bundle
```

## 3. 本次备份包含内容

备份包含以下核心内容：

- `app/`
- `frontend_demo/`
- `scripts/`
- `tests/`
- `tools/`
- `docs/`
- `models/`
- `backups/`
- `.env`
- `.env.example`
- `.gitignore`
- `README.md`
- `requirements.txt`
- `requirements-identity.txt`
- 项目根目录下的 YOLO 基础权重文件，例如 `yolov8n.pt`、`yolo11n-pose.pt` 等

说明：

- `.env` 被纳入本地备份，因为它是恢复当前真实运行配置的关键文件。
- `.env` 可能包含摄像头账号密码、内网地址和 token，不允许公开传播。
- `models/` 被纳入备份，因为当前系统依赖多份本地模型权重和指标文件。

## 4. 本次备份排除内容

为控制体积并避免打包训练中间产物，本次备份排除：

- `.git/`
- `.venv*`
- `.pytest_cache/`
- `__pycache__/`
- `datasets/`
- `runs/`
- `logs/`
- `data/`
- `artifacts/`
- `identity_service/data/`
- `Ultralytics/`
- `video/`

这些目录大多是数据集、训练输出、运行日志或缓存，不属于当前系统最小可恢复核心。

## 5. 恢复方式

解压：

```powershell
Expand-Archive -Path D:\Program\vision_service-6-30.zip -DestinationPath D:\Program\vision_service-6-30-restored
```

进入项目：

```powershell
cd D:\Program\vision_service-6-30-restored\vision_service
```

如果需要恢复 Git 历史，可使用 bundle：

```powershell
git clone .\backups\vision_service_checkpoint_realtime_fall_pipeline_20260630.bundle restored_from_bundle
```

或在已有仓库中查看当前回档点：

```powershell
git show checkpoint-realtime-fall-pipeline-20260630
```

## 6. 后续注意事项

1. 该 zip 是本地完整备份，包含 `.env`，不要上传到公开 GitHub。
2. 公开上传 GitHub 时，继续依赖 `.gitignore` 排除 `.env`、模型权重、数据集、runs 和 logs。
3. 当前新训练的 YOLO person 模型尚未正式接入 `.env`，实际运行仍是 `YOLO_MODEL_PATH=yolov8n.pt`。
4. 当前系统核心链路已基本完成，但 RTSP 稳定性仍需继续验证。
5. GitHub 远程上传尚未完成，网络恢复后仍需执行：

```powershell
git push origin feature/pose-model-qualification
git push origin checkpoint-realtime-fall-pipeline-20260630
```

## 7. 关键交接文档

建议恢复或交接后优先阅读：

```text
docs/PROJECT_HANDOFF_FULL_CONTEXT_2026-07-01.md
docs/HANDOFF_2026-06-29.md
docs/main_system_bridge_api_2026-06-30.md
```
