# 特性开关矩阵

| 能力 | 默认 | 允许的第一版模式 | 额外门禁 |
| --- | --- | --- | --- |
| 事件旁路 | 关闭 | 临时 isolated demo / dry-run | 不影响 Fusion、WS、WebRTC、REST |
| DeliveryOutbox | 关闭 | dry-run / loopback mock | 真实 post 需要人工批准与合同 |
| Qwen advisory | 关闭 | localhost 文本 JSON | 异步、Schema、fallback、无媒体 |
| Qwen 媒体输入 | 关闭 | 不允许 | 隐私批准后仍需单独验收 |
| Robot Assist | 关闭 | `mock` | 主系统审批和任务合同 |
| 自动派遣 | 关闭 | 不允许 | 独立政策与安全 Gate |
| Go2 只读 | 关闭 | 经批准诊断 | `APPROVE_GO2_READ_ONLY` |
| Go2 控制 | 关闭 | 不允许 | `APPROVE_GO2_CONTROL` + 物理安全清单 |
| Go2 低层控制 | 关闭 | 永不允许 | 启动即拒绝 |

任何开关都不授权外部行为；授权、合同、测试证据和对应 Gate 缺一不可。
