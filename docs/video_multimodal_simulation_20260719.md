# 用户视频多模态处理与主系统对接模拟记录

## 1. 本次边界

- 输入视频：`a8f91f5ad1a879903e20a1d92610d782.mp4`（用户本机提供）。
- 视频属性：1280x720、30 FPS、111 帧、约 3.7 秒，HEVC 视频与 AAC 音频。
- 未修改实际 `.env`，未重启 8000，未请求真实主系统，也未启用 DeliveryOutbox 的真实 POST。
- 千问只调用本机 Ollama `http://127.0.0.1:11434` 的 `qwen-vision-cn:latest`。本次仅将关键帧图片字节发给本机模型；没有发送 RTSP、账号、路径、`keyframe_url`、`incident_id`、`track_id` 或 token。
- 本文包含两类结论，不能混用：真实算法离线处理结果，以及为了检查接口内容而生成的 synthetic confirmed 对接样例。

## 2. 真实算法处理结果

离线处理走的是 Detection、Tracking、Pose、Temporal 和现有 `FallFusionService` 的真实逻辑，未人为改写跌倒判定。

| 项目 | 结果 |
| --- | --- |
| 人体检测 | OK |
| 跟踪 | OK |
| 姿态 | OK（4 帧姿态成功） |
| FallFusion 最高状态 | `normal` |
| `fallen_confirmed` 帧数 | 0 |
| 实际 incident_id | 无 |
| 实际告警 | 未产生 |
| 结论 | 该视频不能作为真实跌倒确认验收素材 |

真实结果文件：[offline summary](D:/Program/camera-service/camera_79/logs/qwen_video_simulation_20260719/vision/offline_eval_a8f91f5ad1a879903e20a1d92610d782_summary.json)。带检测框的视频：[boxed video](D:/Program/camera-service/camera_79/logs/qwen_video_simulation_20260719/vision/a8f91f5ad1a879903e20a1d92610d782_boxed.mp4)。

## 3. 千问关键帧语义结果

为验证本机多模态链路，使用同一视频中事件窗口内可用的 4 张关键帧调用本机 Qwen。模型任务是 advisory-only，不参与或改写 FallFusion 的第一次判定。

| 项目 | 结果 |
| --- | --- |
| provider / model | `ollama_qwen` / `qwen-vision-cn:latest` |
| 状态 | `completed` |
| 图像数量 | 4 |
| 处理耗时 | 27603.877 ms |
| 场景摘要 | 室内地面铺设瓷砖并放置紫色瑜伽垫，背景可见柜子与门。 |
| 姿态摘要 | 人物先背对镜头站立于瑜伽垫上，随后跪坐或蹲坐在瑜伽垫中央。 |
| 动作摘要 | 从站立姿态转变为下蹲或跪姿的动作过程。 |
| 误报提示 | 可能为有意识的健身训练，例如瑜伽，而非意外跌倒。 |
| 置信解释 | 基于连续两帧中身体重心明显下降且接触点改变的特征进行判断。 |
| advisory 结论 | 应辅助人工复核，不能单独发起或撤销告警。 |

完整模型结构化结果：[qwen_advisory.json](D:/Program/camera-service/camera_79/logs/qwen_video_simulation_20260719/multimodal_final/event_archive/simulation_camera/vision-fall-simulation_camera-track-1-20260719115609-0001/qwen_advisory.json)。

## 4. 主系统对接模拟

为检查“确认事件 + 证据 + 千问语义”在主系统合同中的表达，额外生成了一条明确标记为 `SYNTHETIC_CONFIRMED_EVENT_OVER_USER_PROVIDED_VIDEO` 的事件。它不是视频算法的真实结论，也没有发送给任何主系统接口。

| 项目 | 值 |
| --- | --- |
| synthetic incident_id | `vision-fall-simulation_camera-track-1-20260719115609-0001` |
| 对接模式 | `dry_run` |
| 是否执行 HTTP POST | 否 |
| 事件状态 | `fallen_confirmed`（仅接口模拟） |
| 证据状态 | `degraded` |
| 可用关键帧 | T-3s、T-1s、T0、T+1s，共 4 张 |
| 缺失关键帧 | T+3s、T+5s，原因 `no_frame_near_target` |
| 机器狗字段 | 不发送；Vision payload 中不包含 `robot_advisory`，机器狗逻辑不属于 Vision 范围 |

主系统将收到的完整 dry-run 内容在：[main_system_payload_dry_run.json](D:/Program/camera-service/camera_79/logs/qwen_video_simulation_20260719/multimodal_final/main_system_payload_dry_run.json)。面向事件复核页的安全详情内容在：[public_event_payload.json](D:/Program/camera-service/camera_79/logs/qwen_video_simulation_20260719/multimodal_final/public_event_payload.json)。模拟运行总记录在：[simulation_result.json](D:/Program/camera-service/camera_79/logs/qwen_video_simulation_20260719/multimodal_final/simulation_result.json)。

### 4.1 主系统 payload 的组成

| 字段组 | 内容 | 用途 |
| --- | --- | --- |
| 事件身份 | `incident_id`、`camera_id`、`timestamp`、`source` | 幂等、关联与审计 |
| 告警结论 | `event_type`、`state`、`status`、`severity`、`risk_level`、`fall_detected` | 主系统生成或更新告警 |
| 量化证据 | `fall_prob`、`fall_score`、`bbox`、`scores` | 解释检测置信度 |
| 处置建议 | `injury`、`explanation`、`recommended_action`、`advice` | 告警详情与人工处置 |
| 证据摘要 | `metadata.evidence.evidence_status`、`keyframe_count`、`missing_reasons` | 向前端说明证据完整性；不传本地媒体地址 |
| 规则语义 | `metadata.semantic_analysis` | 保存规则侧最终结论和不确定性 |
| 千问语义 | `metadata.semantic_analysis.qwen_keyframe_advisory` | 场景、姿态、动作、误报原因、照护建议、模型耗时；仅 advisory |
| 运行标记 | `delivery_mode=dry_run`、`dry_run=true` | 明确该 payload 未实际投递 |

### 4.2 隐私与安全边界

payload 不含本地绝对路径、归档路径、RTSP URL、摄像头账号密码、token、原始模型回复或关键帧 URL。`metadata.evidence.keyframe_urls` 固定为空数组；媒体应由经过鉴权的事件详情 API 按需读取，而不是直接随告警投递。

## 5. 结论

- **真实视频处理：PASS（无跌倒）**。主链路正确完成检测、跟踪和姿态处理，FallFusion 没有把受控跪姿误判为确认跌倒。
- **本机千问关键帧语义：PASS（advisory-only）**。它给出的“受控动作，可能误报”与真实主链路结果一致。
- **主系统接口格式：PASS（dry-run 模拟）**。完整 JSON 已落地，但没有真实 HTTP POST，不能称为正式主系统联调通过。
- **六帧证据链：REVISE**。源视频过短，仅有 4/6 张真实关键帧，T+3/T+5 已明确标记缺失，不能宣称六图完整。
- **真实 fallen_confirmed 验收：NOT_RUN**。需要提供经授权、时长至少覆盖触发点前 3 秒与后 5 秒的真实跌倒回放，或真实 RTSP 场景后再执行。
