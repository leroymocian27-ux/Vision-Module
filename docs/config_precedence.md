# 配置优先级与运行真相

`Settings` 在进程启动期间确定有效值。运行时服务不读取 `.env.example`，因此
`.env.example` 只是安全模板，不是当前实例的真相源。

| 来源类别 | 含义 | 可否覆盖低优先级 |
| --- | --- | --- |
| `default` | 代码默认值 | 是 |
| `project_env_file` | 项目 `.env` | 是 |
| `explicit_env_file` | `VISION_SERVICE_ENV_FILE` 指定文件 | 是 |
| `process_env` | 启动服务时已有环境变量 | 是，且优先级最高 |

## 运维规则

1. 任何重启前采集 `/status.configuration` 的安全摘要。
2. 不在文档、日志或前端暴露原始环境变量。
3. 每一次临时实例只使用会话级变量、隔离 SQLite 和归档目录。
4. 真实 `8000` 的重启和运行时重验必须等待 `APPROVE_RESTART_VISION`。
5. 出现文件配置与状态不一致时，以运行状态为事实，先记录后修复，不通过猜测覆盖。
