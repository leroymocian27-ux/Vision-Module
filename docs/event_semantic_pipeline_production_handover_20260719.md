# 生产交接前能力矩阵

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| Vision 实时 Fusion 主链 | CODE_READY_NOT_RUNTIME_VERIFIED | 既有运行与测试记录，不是本轮重启验收。 |
| 事件旁路/证据/归档 | VERIFIED_SYNTHETIC | P1、自动化测试。 |
| Delivery dry-run/mock | VERIFIED_MOCK | SQLite 与 loopback mock。 |
| Vision metadata 扩展 | CODE_READY_NOT_RUNTIME_VERIFIED | 12 项兼容/安全测试。 |
| 主系统 RobotAssistTask 后端 | CODE_READY_NOT_RUNTIME_VERIFIED | focused pytest。 |
| RobotAssistTask 前端 | CODE_READY_NOT_RUNTIME_VERIFIED | typecheck/build。 |
| Mock 完整软件闭环 | VERIFIED_MOCK | 10 项跨模块测试。 |
| Qwen advisory | CODE_READY_NOT_RUNTIME_VERIFIED | 隐私/fallback 测试；真实 smoke REVISE。 |
| 真实 RTSP/confirmed/六图 | BLOCKED_EXTERNAL_DEPENDENCY | 缺 RTSP 或授权回放。 |
| 主系统 staging/canary | BLOCKED_EXTERNAL_DEPENDENCY | 缺合同、Token、批准。 |
| Go2 DDS 只读 | BLOCKED_EXTERNAL_DEPENDENCY | 缺批准、设备事实、DDS 回包。 |
| Go2 控制 | FORBIDDEN_BY_POLICY | 需只读 PASS、书面批准与物理安全。 |

## 生产前必要条件

1. 受控重启 Vision，验收配置漂移和状态脱敏。
2. 取得授权 RTSP/回放，完成 Round A/B、真实 confirmed 和完整六图。
3. 获取主系统 staging 合同、Token、ACK 与重复语义，完成 mock -> staging -> canary。
4. 修复 Qwen 延迟/JSON，并完成本机 advisory admission。
5. 获得 Go2 型号、权限、网络与 read-only 批准；先做 DDS 只读。
6. 完成主系统与 Mock 服务 HTTP/WebSocket 运行时验收。
7. 完成鉴权、CORS、备份、恢复、审计、容量与责任人制度。

## 回滚

- 关闭事件/Delivery/VLM 开关；保留 `FallEventReporterService`。
- 停止 Robot Assist Service；主系统任务保持审计但不调度。
- `ROBOT_AUTO_DISPATCH_ENABLED=false`、`GO2_CONTROL_ENABLED=false`、`GO2_LOW_LEVEL_CONTROL_ENABLED=false`。
- 不删除 SQLite、归档或任务事件，保留用于故障分析。
