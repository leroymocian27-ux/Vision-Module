# RobotAssistTask 前端流程

实现位置：主系统 `frontend/vue-dashboard/src/components/RobotAssistPanel.vue`。

```text
活动跌倒告警 -> 社区人员选择告警 -> 填写老人、房间、固定观察点
-> 创建 AWAITING_APPROVAL -> 审批 -> QUEUED -> 后续 Adapter 状态回传
```

## UI 边界

- 仅 community/admin 可看到创建、审批、取消动作。
- family/elder 不显示控制入口。
- 缺少告警、incident、老人、房间或固定观察点时，创建失败，不猜测数据。
- `adapter_mode=mock` 显示“模拟执行”；不等同真实机器狗移动。
- 不展示 RTSP、内部 IP、Token、路径、速度或导航坐标。
- Qwen 不显示为判定结果或自动派遣来源。

主系统未重启，因此 API 请求、WebSocket 状态刷新、角色会话、窄屏截图均为 `NOT_RUN`。
