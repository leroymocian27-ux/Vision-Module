# 三模块集成事实与假设基线

日期：2026-07-19  
阶段：Phase 0 只读审计  
证据规则：每一项均明确区分运行时事实、代码事实、文档事实和未验证假设。

## 已验证事实

| 范围 | 事实 | 证据类型 |
| --- | --- | --- |
| Vision 实时链路 | `FallFusionService`、WebRTC、WebSocket、REST 与 `FallEventReporterService` 均在现有代码中存在。 | CODE_ONLY + 运行时状态摘要 |
| Vision 事件旁路 | 事件、证据归档、DeliveryOutbox、关键帧安全开关和 Ollama advisory 代码存在，默认配置关闭。 | CODE_ONLY |
| 本机 Vision | `127.0.0.1:8000/healthz` 和 `/status` 于本次审计返回 HTTP 200。 | 运行时 GET |
| 运行时性能 | 当次状态摘要显示 capture 约 10.39 FPS、detect 约 0.18 FPS。该单点样本不是长稳或性能验收。 | 运行时 GET |
| 主系统源码 | 已识别到主系统代码库，具有 `AlarmRecord`、告警去重、`/ws/alarms` 和既有跌倒事件摄入代码。 | CODE_ONLY |
| RobotAssistTask | Vision 和已审计主系统中均未发现独立 RobotAssistTask 领域、任务 API 或机器人适配器。 | CODE_ONLY |
| Go2 | 文档指定的 Go2 开发目录本机不可见，不能推断 SDK、DDS、相机或控制能力。 | 本机文件系统检查 |

## 仅文档或代码支持，尚未运行验收

- 真实摄像头 RTSP、真实算法 `fallen_confirmed`、真实六图完整性、真实主系统 POST 均未验收。
- Qwen/Ollama 仅允许本机文本 advisory；现有 smoke 为 `REVISE`，不构成准入。
- DeliveryOutbox 的 SQLite/dry-run 和 loopback mock 已有测试证据，但不等于主系统 staging 或生产投递。
- Go2 网络可达、DDS 回包、lowstate/sportstate、ROS2、摄像头和真实控制均未验证。

## 默认假设

1. 第一版仅支持人工审批后的 `fall_scene_check`。
2. 第一版使用固定房间观察点，不计算老人实时坐标，不靠近老人。
3. MockRobotAdapter 可以作为软件闭环验收，必须始终标记 `adapter=mock` 和 `simulated=true`。
4. Qwen 只能生成 advisory，不能改写 `fallen_confirmed`、告警等级或机器人执行决定。

## 禁止宣称

- “真实 Go2 已联动”
- “真实摄像头已经稳定验收”
- “真实主系统已经正式收到 DeliveryOutbox 告警”
- “Qwen 已参与跌倒第一判定”
- “Mock 任务等同机器狗真实移动”
