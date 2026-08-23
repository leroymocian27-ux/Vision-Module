# Vision Service 对主系统下一轮跌倒测试优化计划的配合落实情况

更新时间：2026-06-16 19:18 Asia/Shanghai

## 1. 目标

本文档说明：

1. 主系统给出的下一轮跌倒联调优化计划中
2. 哪些事项已经由 Vision Service 一侧配合落实
3. 哪些事项仍然属于主系统侧待完成动作

## 2. Vision Service 已落实的配合项

## 2.1 统一只读结果摘要

已完成：

1. `GET /integration/results/{camera_id}/latest` 返回主系统可直接消费的摘要字段
2. `/status.latest_result` 已补齐以下字段：
   - `fall_prob`
   - `fall_score`
   - `incident_id`
   - `snapshot_url`

意义：

1. 主系统即使不接入可选增强接口，也能从基础接口中读取稳定的事件摘要

## 2.2 保留并下沉事件去重能力

已完成：

1. 同一持续跌倒事件保持稳定 `incident_id`
2. 事件结束后会清理活动告警状态

意义：

1. 避免主系统把同一持续事件误判成多条新事件

## 2.3 补齐标准化 `metadata.event` 事件结构

已完成：

无论是真实正式告警、模拟告警还是验收脚本推送，当前都统一补齐了：

1. `metadata.event.incident_id`
2. `metadata.event.camera_id`
3. `metadata.event.stream_name`
4. `metadata.event.event_type`
5. `metadata.event.state`
6. `metadata.event.status`
7. `metadata.event.severity`
8. `metadata.event.risk`
9. `metadata.event.risk_level`
10. `metadata.event.fall_score`
11. `metadata.event.fall_prob`
12. `metadata.event.track_id`
13. `metadata.event.snapshot_url`
14. `metadata.event.snapshot_path`
15. `metadata.event.injury`
16. `metadata.event.multimodal_review`

意义：

1. 主系统后端和前端都不必再只依赖扁平 `metadata.*` 或 `metadata.raw_event.*`
2. 更符合主系统优化计划里提出的结构化事件要求

## 2.4 补充下一轮测试前基线快照工具

已完成：

新增脚本：

1. `scripts/capture_pretest_baseline.py`

用途：

1. 在下一轮正式测试前记录 Vision Service 当前状态
2. 记录主系统当前活动告警基线
3. 输出可归档的 JSON 快照

使用注意：

1. `--main-base` 需要显式传入当前实际暴露 `/api/v1/alarms` 和 `/api/v1/alarms/queue` 的主系统后端地址
2. 不再假设某个固定 IP 一定是主系统告警后端

意义：

1. 配合主系统完成“测试前基线快照”要求

## 2.5 增强联调监控脚本

已完成：

1. `scripts/monitor_fall_alert_e2e.py` 已兼容主系统当前 `video_fall` 告警类型

意义：

1. 下一轮联调时可以更好地区分：
   - Vision Service 是否形成事件
   - 主系统是否生成新告警

## 3. 已验证情况

Vision Service 仓库内已验证：

```powershell
python -m pytest tests\test_fall_alert_polling_api.py tests\test_end_to_end_pipeline.py tests\test_alerting_manual_send.py -q
```

结果：

1. `10` 个相关测试通过

## 4. 仍属于主系统侧待完成事项

以下内容不是 Vision Service 单侧能彻底完成的，仍需主系统侧继续处理：

## 4.1 修通 `/api/v1/vision/*` 上游读取目标

当前关键问题：

1. 主系统当前目标口径已明确为：
   - 主系统 = `192.168.8.253`
   - Vision Service = `192.168.8.254`
2. 主系统 `/api/v1/vision/*` 应稳定读取 `http://192.168.8.254:8000`
3. 当前真正剩余的问题已经从“读错目标”转为“254 上的 Vision Service 相关接口未稳定返回”

这部分必须由主系统侧继续修复。

## 4.2 统一前端跌倒告警识别类型

当前主系统计划中提出：

1. 前端识别类型与后端实际告警类型不一致

这部分需要主系统后端和前端统一，不是 Vision Service 单侧可完成项。

## 4.3 页面端弹窗逻辑和会话时间门槛

当前主系统计划中提出：

1. 页面存在只展示当前会话附近新告警的时间门槛

这部分属于主系统页面逻辑，需要主系统自身处理。

## 4.4 清理历史模拟告警

当前主系统活动告警中仍有历史模拟告警残留。

这部分属于主系统数据侧基线清理动作，需要主系统侧执行。

## 5. 下一轮建议联调顺序

建议下一轮正式测试前，按下面顺序执行：

1. 主系统先确认 `/api/v1/vision/*` 稳定读取 `192.168.8.254`
2. Vision Service 侧运行：
   - `python scripts/capture_pretest_baseline.py`
3. 主系统清点并隔离历史活动告警
4. 主系统确认前端已能识别真实跌倒告警类型
5. 再开始新的定时 2 分钟跌倒联调测试

## 6. 一句话结论

针对主系统本轮优化计划，Vision Service 一侧已经完成了“结果摘要补齐、事件结构标准化、基线快照工具、联调监控脚本增强”等可落实事项；当前剩余阻断下一轮测试成功率的关键项，主要已经转移到主系统的 Vision 代理读取、告警类型统一、活动告警基线清理与前端弹窗逻辑本身。
