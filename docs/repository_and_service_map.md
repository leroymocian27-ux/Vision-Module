# 代码库与服务映射

日期：2026-07-19  
审计方式：只读文件与本机 loopback GET。

| 模块 | 已确认位置/入口 | 已确认能力 | 当前限制 |
| --- | --- | --- | --- |
| Vision Service | `camera_79/app/main.py` | FastAPI、实时流、Fusion、事件旁路、Delivery、Ollama adapter。 | 工作树已有大量未提交变更；真实配置与运行实例存在漂移。 |
| 主系统 | `health(5-19)/backend/main.py` | AlarmRecord、AlarmService、`/ws/alarms`、角色和前端告警面板。 | RobotAssistTask 域和机器人 API 尚不存在；未确认可修改授权和版本标签。 |
| 前端 | `health(5-19)/frontend/vue-dashboard` | 告警面板、WebSocket 客户端、角色 UI。 | 未实现机器人任务卡、审批和时间线。 |
| Qwen/Ollama | Vision `app/events/vlm_adapter.py` | loopback text-only advisory provider、fallback。 | 烟测为 REVISE；媒体输入关闭。 |
| Go2 | 预期开发位置本机未发现。 | 无。 | DDS、SDK、设备事实和控制均 BLOCKED_EXTERNAL_DEPENDENCY。 |

## 运行服务观察

本次观察到 loopback `8000`、`8011`、Ollama `11434` 均有监听；仅对 Vision
`8000` 进行了 GET 健康检查。没有启动、停止、重启或连接外部服务。

## 版本事实

- Vision Git 分支：`main`；最近提交：`494e430`；工作树非干净。
- 主系统目录未在本次审计中确认 Git 元数据，不能宣称其当前 commit。
- 所有后续修改必须以实际文件和独立测试作为证据，不假设运行实例对应当前工作树。
