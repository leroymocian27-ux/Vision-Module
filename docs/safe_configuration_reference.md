# Vision 安全配置参考

## 唯一加载顺序

```text
代码默认值 < 项目 .env < VISION_SERVICE_ENV_FILE 指定文件 < 进程环境变量
```

同名变量一旦已存在于进程环境，环境文件不会覆盖它。状态页只显示来源类别，不显示文件路径、Token、RTSP 或原始变量。

## 安全默认值

```dotenv
EVENT_PIPELINE_ENABLED=false
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_MODE=dry_run
EVENT_VLM_ENABLED=false
EVENT_VLM_OLLAMA_INCLUDE_IMAGES=false
QWEN_MEDIA_INPUT_ENABLED=false
ROBOT_ASSIST_ENABLED=false
ROBOT_ASSIST_MODE=mock
ROBOT_AUTO_DISPATCH_ENABLED=false
GO2_READ_ONLY_ENABLED=false
GO2_CONTROL_ENABLED=false
GO2_LOW_LEVEL_CONTROL_ENABLED=false
```

## 启动拒绝规则

- `GO2_LOW_LEVEL_CONTROL_ENABLED=true` 始终拒绝。
- Go2 控制要求机器人服务已启用且 `GO2_CONTROL_APPROVED=true`。
- Qwen 媒体输入要求 `QWEN_MEDIA_PRIVACY_APPROVED=true`；当前策略不批准。
- 启用 Delivery post 要求显式批准、目标地址和完整 token/header 配置。

这些检查不发送请求、不改变 `.env`，也不替代真实主系统的人工批准。
