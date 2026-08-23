# Vision 配置漂移报告

日期：2026-07-19  
阶段：Phase 0 只读审计  
真实环境修改：无

## 发现

现有配置加载流程在模块导入时读取项目 `.env` 并写入进程环境；其后 `Settings`
使用进程环境构造冻结 dataclass。原实现没有保留每个值来自默认值、项目环境文件、显式环境文件或进程环境的来源。

本次只读运行检查得到：

```text
GET /healthz: 200
GET /status: 200
FallEventReporterService.enabled: true
FallEventReporterService.running: true
FallEventReporterService.last_post_status: http_200
```

而安全示例基线中 `MAIN_SYSTEM_ALERT_ENABLED=false`。这证明“文件显示值”不能单独作为运行时真相。`last_post_status=http_200` 可能来自既有进程生命周期中的历史状态；本审计没有发送 POST，因此不将其描述为本次真实投递证据。

## 风险

1. 未重启前，修改后的源码和 `.env.example` 不会改变现有 `8000` 进程。
2. 文件配置、启动时环境变量、设备发现返回的 Settings 替换以及运行实例可能不一致。
3. 单纯查看 `.env` 无法证明 Delivery、Reporter、VLM 或机器人能力实际关闭。

## 已实施的治理

- 新增安全 allowlist 配置摘要：只显示布尔开关、模式和来源类别。
- 来源类别仅为 `default`、`project_env_file`、`explicit_env_file`、`process_env`，不显示路径或变量值。
- `/status.configuration` 将在获得批准的后续重启后展示有效配置、来源和启动安全错误。
- 启动前拒绝未批准的 Go2 控制、低层控制、Qwen 媒体输入，以及启用但未完整批准的 Delivery POST。

## 未执行的操作

- 未修改实际 `.env`。
- 未重启 `8000`。
- 未调用主系统、Ollama、RTSP 或 Go2。

## 后续门禁

`APPROVE_RESTART_VISION` 获批后，执行 P2 状态脱敏重启验收，重新采集 `/status.configuration` 与 Reporter 实例状态。
