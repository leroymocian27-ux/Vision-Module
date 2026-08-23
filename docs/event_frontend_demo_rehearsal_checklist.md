# Event Frontend Demo Rehearsal Checklist

## 演示前检查

- [ ] 服务已启动。
- [ ] `/demo/` 可以打开。
- [ ] video 区域存在。
- [ ] overlay/canvas 存在。
- [ ] Raw Status 存在。
- [ ] Diagnostics 存在。
- [ ] Event Semantic Review / 事件复核面板存在。
- [ ] 浏览器 console 没有持续 error/warn。

## 关闭态演示检查

- [ ] 显示“事件语义链路未启用”。
- [ ] 关键帧时间轴有 6 个占位卡。
- [ ] 没有关键帧图片请求。
- [ ] console 无错误。
- [ ] video/overlay/Raw Status/Diagnostics 仍存在。

## 事件态演示检查

- [ ] `incident_id` 显示。
- [ ] `risk_level` 显示。
- [ ] `confidence` 显示。
- [ ] `explanation` 显示。
- [ ] `recommended_action` 显示。
- [ ] Delivery 状态显示。
- [ ] dry-run 显示为模拟投递，不显示为正式投递。
- [ ] VLM/规则复核状态显示。
- [ ] 6 个关键帧卡片显示。
- [ ] 关键帧图片可以加载，或缺失时显示原因。
- [ ] Timeline Image 显示图片、未提供或仅归档状态。
- [ ] 页面不显示 `target_url`、`payload_json`、`lock_token`、token/header 或本地路径。

## 演示话术边界

禁止说：

- “大模型直接判断跌倒”
- “已正式推送主系统”
- “能医疗诊断老人受伤情况”

推荐说：

- “实时检测链路先发现跌倒候选。”
- “事件链路抽取前后关键帧形成证据包。”
- “规则和大模型/本地语义模型用于辅助复核和解释。”
- “当前 Delivery 是 dry-run 或受控验收模式。”
- “原正式主系统告警链路仍保留。”

## 异常解释

没有事件：当前没有事件归档，面板显示“暂无事件归档”。

没有关键帧：关键帧缺失或未归档，卡片会显示 `missing_reason`。

图片加载失败：前端显示“关键帧不可用”，不会请求本地文件路径。

VLM 未启用：当前展示规则复核结果，VLM/Ollama 是可选辅助解释链路。

Delivery 未启用：当前没有投递状态，正式主系统告警链路仍保留。

dry-run：只表示模拟投递或受控验收，不是正式报警。

