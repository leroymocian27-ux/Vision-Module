# Vision Service 面向主系统的接口基线与可选增强能力说明

更新时间：2026-06-16 18:30:59 +08:00

## 1. 文档定位

本文档用于说明当前 Vision Service 面向主系统的真实对接基线。

本文档的目标不是要求主系统立即切换到 Vision Service 新增的所有增强能力，而是：

1. 明确主系统当前默认依赖的基础契约
2. 明确 Vision Service 额外提供但主系统当前尚未默认接入的可选增强能力
3. 避免联调人员把“Vision Service 已实现能力”误认为“主系统当前正式基线”

## 2. 当前结论

当前主系统已经可以按“主系统主动读取 Vision Service 状态与结果”的模式接入。

主系统当前默认依赖的基础契约是：

1. `GET /healthz`
2. `GET /status?camera_id=...`
3. `GET /stream/source?camera_id=...`
4. `GET /integration/results/{camera_id}/latest`

如果 Vision Service 采用“确认跌倒后主动推送到主系统”的链路，主系统当前稳定支持：

1. `POST /api/v1/video-bridge/fall-events`

除此之外，Vision Service 当前还额外提供了若干增强能力，例如：

1. `GET /integration/fall-alerts/{camera_id}/poll`
2. `/status.polling_alert`

以上增强能力当前不是主系统默认依赖基线；如果未来主系统接入，可以简化弹窗判断、事件去重和前端展示逻辑。

## 3. 当前是否可用

## 3.1 接口能力层

从接口能力角度看，当前面向主系统的基础契约已经可用。

已完成的内容包括：

1. 基础接口路由已实现
2. 主系统关心的关键字段已对齐
3. `incident_id` 在同一持续跌倒事件中保持稳定
4. `snapshot_url` 可随确认跌倒事件一起输出
5. 兼容保留主动推送主系统的告警链路

## 3.2 部署运行层

部署运行层是否“全部可用”，仍取决于现场环境：

1. Vision Service 进程是否已重启到最新代码
2. 摄像头流是否已实际连通
3. 主系统是否能访问 Vision Service 监听地址与端口
4. `camera_id` 是否与主系统配置一致
5. `VISION_SERVICE_PUBLIC_BASE_URL` 是否配置为主系统可访问地址

因此更准确的结论是：

1. 代码与接口契约层：可用
2. 现场联通与部署层：仍需按环境确认

## 4. 主系统当前真实接入边界

## 4.1 主系统内部代理接口

主系统当前对外暴露的以下接口：

1. `GET /api/v1/vision/health`
2. `GET /api/v1/vision/status`
3. `GET /api/v1/vision/source`
4. `GET /api/v1/vision/results/latest`

这些接口属于主系统自己的代理层接口，不是 Vision Service 需要直接实现的路径。

Vision Service 只需要提供真实源接口：

1. `/healthz`
2. `/status`
3. `/stream/source`
4. `/integration/results/{camera_id}/latest`

## 4.2 主系统当前告警接收基线

如果 Vision Service 需要主动把确认跌倒事件推送给主系统，则当前主系统支持：

1. `POST /api/v1/video-bridge/fall-events`

这条链路当前仍然保留，可继续作为兼容或正式告警接入方式。

## 5. 主系统默认依赖的基础契约

## 5.1 `GET /healthz`

用途：

1. 判断 Vision Service 是否存活

成功示例：

```json
{
  "status": "ok"
}
```

## 5.2 `GET /status`

查询参数：

1. `camera_id`：可选

用途：

1. 获取完整运行状态
2. 判断摄像头是否在线
3. 判断检测链路是否稳定
4. 观察最近一次跌倒判断摘要

主系统当前应重点关注的基础字段：

1. `cameras[].camera_id`
2. `cameras[].connected`
3. `cameras[].stream_state`
4. `cameras[].frame_age_ms`
5. `cameras[].capture_fps`
6. `detection[].loaded`
7. `latest_result.fall_state`
8. `latest_result.risk_level`
9. `latest_result.fall_prob`
10. `latest_result.fall_score`
11. `latest_result.incident_id`
12. `latest_result.snapshot_url`

说明：

1. `/status` 仍然是综合状态接口
2. 当前主系统默认不需要依赖 `polling_alert` 才能完成基础联调

## 5.3 `GET /stream/source`

查询参数：

1. `camera_id`：默认 `camera_01`

用途：

1. 查询当前视频源运行态

主系统当前应重点关注的基础字段：

1. `camera_id`
2. `running`
3. `main_stream_state`
4. `analysis_stream_state`
5. `main_connected`
6. `analysis_connected`
7. `main_frame_age_ms`
8. `analysis_frame_age_ms`
9. `main_capture_fps`
10. `analysis_capture_fps`
11. `message`

调试字段：

1. `main_rtsp_url_masked`
2. `analysis_rtsp_url_masked`

说明：

1. RTSP masked URL 当前保留为调试与排障字段
2. 主系统当前不应把 RTSP 地址本身作为核心业务契约中心

## 5.4 `GET /integration/results/{camera_id}/latest`

用途：

1. 获取某摄像头最新一次结构化分析结果
2. 这是主系统当前最关键的只读业务接口

未就绪时：

1. 返回 `404`
2. 返回体：`{"detail":"VISION_RESULT_NOT_READY"}`

当前返回结构包含两部分：

### A. 主系统建议直接消费的摘要字段

1. `camera_id`
2. `stream_name`
3. `source`
4. `service_state`
5. `camera_lost`
6. `capture_stale`
7. `frame_age_ms`
8. `source_fps`
9. `analysis_fps`
10. `fall_detected`
11. `fall_state`
12. `risk`
13. `risk_level`
14. `fall_prob`
15. `fall_score`
16. `track_id`
17. `incident_id`
18. `bbox`
19. `snapshot_url`
20. `snapshot_path`
21. `timestamp`
22. `alarm_confirmed`

### B. 原始扩展字段

1. `target`
2. `scores`
3. `injury`
4. `metadata`
5. `objects`
6. `detector`

字段语义说明：

1. `incident_id`：当前对同一持续跌倒事件保持稳定，适合作为主系统幂等键
2. `snapshot_url`：只有在成功生成快照时才有值
3. `objects`：保留原始识别结果，主系统如需更细粒度分析可继续读取
4. `metadata`：保留原始跌倒判定、告警预览、时序结果等扩展内容

## 6. Vision Service 额外提供的可选增强能力

以下能力已经由 Vision Service 实现，但当前不是主系统默认依赖基线。

## 6.1 `GET /integration/fall-alerts/{camera_id}/poll`

用途：

1. 直接告诉调用方当前是否应弹窗
2. 支持调用方传入 `last_incident_id` 去重

当前状态：

1. Vision Service 已实现
2. 主系统当前未默认接入

适合未来接入的场景：

1. 主系统希望减少本地弹窗去重逻辑
2. 主系统希望直接获取 `should_popup`
3. 主系统希望把“事件新旧判断”下沉到 Vision Service

## 6.2 `/status.polling_alert`

用途：

1. 在 `/status` 中附带一个弹窗判断摘要

当前状态：

1. Vision Service 已实现
2. 主系统当前未默认依赖

说明：

1. 这是可选增强字段，不应写成主系统当前正式基线字段

## 7. 联调和兼容接口

以下接口当前主要用于联调、演示或兼容验证：

1. `GET /fall-events/snapshots/{filename}`
2. `GET /alerting/status`
3. `POST /alerting/endpoint`
4. `POST /alerting/simulation/send-once`
5. `POST /alerting/simulation/start`
6. `POST /alerting/simulation/stop`

说明：

1. 它们不是主系统当前默认只读状态消费基线的一部分
2. 但可继续用于现场验证和模拟联调

## 8. 配置项说明

## 8.1 Vision Service 侧变量

以下变量属于 Vision Service 自己的部署配置：

1. `VISION_SERVICE_PUBLIC_BASE_URL`
2. `MAIN_SYSTEM_ALERT_ENABLED`
3. `MAIN_SYSTEM_BASE_URL`
4. `MAIN_SYSTEM_FALL_EVENT_PATH`
5. `MAIN_SYSTEM_ALERT_TOKEN`
6. `MAIN_SYSTEM_ALERT_TOKEN_HEADER`

说明：

1. 这些变量属于 Vision Service 进程
2. 不应和主系统自己的配置变量混写

## 8.2 主系统侧变量

主系统当前真实使用的变量命名应以主系统仓库为准。

根据主系统给出的对齐反馈，当前主系统关注的是：

1. `VISION_SERVICE_BASE_URL`
2. `VISION_SERVICE_CAMERA_ID`
3. `VISION_SERVICE_POLL_ENABLED`
4. `VISION_SERVICE_TIMEOUT_SECONDS`
5. `VISION_SERVICE_PUSH_TOKEN`

说明：

1. 上述变量属于主系统，不属于 Vision Service
2. 联调时应明确区分两组变量归属

## 9. 主系统是否必须修改

## 9.1 不修改也可以工作

如果主系统继续按当前基础基线工作，只依赖：

1. `/healthz`
2. `/status`
3. `/stream/source`
4. `/integration/results/{camera_id}/latest`

那么主系统不需要因为本次 Vision Service 的增强能力而被迫修改。

## 9.2 可选优化方向

如果未来主系统希望进一步简化弹窗逻辑，可以选择新增接入：

1. `GET /integration/fall-alerts/{camera_id}/poll`

但这属于可选增强，不是当前联调前提。

## 10. 测试说明

## 10.1 Vision Service 仓库内已验证

以下验证是在 Vision Service 仓库内完成的：

1. 最新结果接口返回主系统所需的摘要字段
2. `incident_id` 在持续跌倒事件中保持稳定
3. 轮询增强接口对新事件和已处理事件的行为正确
4. 持续跌倒结束后增强告警状态会清理
5. 端到端结果发布链路未回归
6. 模拟告警接口未回归

执行命令：

```powershell
python -m pytest tests\test_fall_alert_polling_api.py tests\test_end_to_end_pipeline.py tests\test_alerting_manual_send.py -q
```

结果：

1. `10` 个相关测试通过

## 10.2 主系统侧联调验证

主系统侧是否已经把以下项纳入其自身仓库测试，应以主系统仓库为准：

1. `/api/v1/vision/health`
2. `/api/v1/vision/status`
3. `/api/v1/vision/source`
4. `/api/v1/vision/results/latest`
5. `POST /api/v1/video-bridge/fall-events`

本文档不将 Vision Service 仓库测试表述成主系统仓库测试结论。

## 11. 最终建议

给主系统的最终建议是：

1. 当前正式对接基线继续以基础契约为准：
   - `/healthz`
   - `/status`
   - `/stream/source`
   - `/integration/results/{camera_id}/latest`
2. 主系统内部继续保留自己的 `/api/v1/vision/*` 代理层即可
3. `POST /api/v1/video-bridge/fall-events` 仍可作为主动告警链路继续使用
4. `GET /integration/fall-alerts/{camera_id}/poll` 和 `/status.polling_alert` 当前视为可选增强，不是主系统当前默认基线

一句话结论：

Vision Service 当前代码已经可以满足主系统“主动读取跌倒检测模块状态与结果”的方案；增强能力可以保留，但面向主系统的正式文档应优先对齐当前主系统真实依赖的基础契约。
