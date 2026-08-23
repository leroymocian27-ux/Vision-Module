# Vision Service 接口文档

更新时间：2026-06-19

适用版本：

- 仓库：`D:\Program\vision_service`
- 提交：`66b5b82`
- 主要适用对象：
  - 后端开发
  - 前端开发
  - 联调工程师
  - 测试工程师

## 1. 文档目标

本文档描述 `vision_service` 当前对外暴露的接口，包括：

- HTTP API
- WebSocket 实时结果订阅
- 静态 Demo 页面
- 快照访问接口

本文档重点回答三个问题：

1. 有哪些接口
2. 每个接口的请求和响应是什么
3. 每个接口适合谁来调用

## 2. 服务入口

服务默认由 FastAPI 提供接口。

典型访问入口：

```text
http://127.0.0.1:<PORT>
```

当前现场/联调用例中，常见端口是：

```text
8000 或 8001
```

OpenAPI 页面：

```text
GET /docs
GET /openapi.json
```

前端调试页面：

```text
GET /demo
```

## 3. 接口总览

### 3.1 状态与健康

- `GET /healthz`
- `GET /status`

### 3.2 视频流控制

- `POST /stream/start`
- `GET /stream/source`
- `GET /stream/latest-frame.jpg`
- `POST /stream/switch-host`
- `POST /stream/probe`
- `POST /stream/stop`

### 3.3 WebRTC / 实时订阅

- `POST /webrtc/offer`
- `POST /webrtc/candidate`
- `WS /ws/results`

### 3.4 身份库接口

- `POST /identity/enroll`
- `GET /identity/list`
- `DELETE /identity/{person_id}`

### 3.5 结果集成接口

- `GET /integration/connection-status`
- `GET /integration/results/{camera_id}/latest`
- `GET /integration/fall-alerts/{camera_id}/poll`

### 3.6 告警与联调控制

- `GET /alerting/status`
- `POST /alerting/endpoint`
- `POST /alerting/simulation/start`
- `POST /alerting/simulation/send-once`
- `POST /alerting/simulation/stop`

### 3.7 跌倒快照

- `GET /fall-events/snapshots/{filename}`

## 4. 通用说明

### 4.1 认证

当前这些入站接口默认不要求 Token。

注意：

- `vision_service` 对外推送到主系统时，会使用 `X-Vision-Service-Token`
- 但那是出站 HTTP，不是本文档中的入站接口要求

### 4.2 Content-Type

- JSON 接口：`application/json`
- 身份注册接口：`multipart/form-data`
- 图片接口：`image/jpeg`
- WebSocket：标准 WS 协议

### 4.3 常见错误码

- `400` 参数不合法
- `404` 资源不存在或当前尚未准备好
- `409` 状态冲突，例如流已在运行、身份已存在
- `500` 编码或服务内部错误
- `503` 下游能力不可用，例如身份服务未就绪

## 5. 详细接口定义

## 5.1 `GET /healthz`

用途：

- 服务活性探针
- 容器/进程健康检查

请求参数：

- 无

响应示例：

```json
{
  "status": "ok"
}
```

调用方建议：

- 部署平台
- Nginx / API Gateway
- 运维巡检脚本

## 5.2 `GET /status`

用途：

- 获取当前运行态总览
- 排查摄像头、检测、跟踪、姿态、时序、告警链路
- 当前最重要的诊断接口

查询参数：

- `camera_id`：可选，默认查看默认摄像头或全部运行信息

响应模型：

- `VisionStatus`

顶层主要字段：

- `service_status`
- `runtime_profile`
- `cameras`
- `detection`
- `tracking`
- `identity`
- `pose`
- `behavior`
- `temporal`
- `pipeline`
- `latest_result`
- `polling_alert`
- `fall_event_reporter`
- `main_stream`
- `analysis_stream`
- `diagnostics`

重点诊断字段说明：

- `cameras[].stream_state`
  - `connected / connecting / stale / reconnecting / disconnected`
- `cameras[].capture_fps`
  - 采集帧率
- `cameras[].frame_age_ms`
  - 最新帧距当前时间的延迟
- `detection[].latest_raw_person_count`
  - 当前帧检测到的人数
- `detection[].latest_fall_model_count`
  - 当前 fall detector 输出数量
- `tracking.tracked_objects_count`
  - 跟踪输出目标数
- `pose.pose_provider`
  - 当前姿态 Provider，例如 `branch4_legacy`
- `pose.rejected_reason`
  - 当前姿态被拒绝的原因
- `temporal.fall_state`
  - 当前时序状态
- `temporal.risk_level`
  - 当前时序风险等级
- `latest_result.fall_state`
  - 当前对外发布的主状态
- `latest_result.alarm_confirmed`
  - 是否已确认告警
- `latest_result.incident_id`
  - 已确认事件编号
- `latest_result.pose_debug`
  - 骨架调试信息
- `latest_result.temporal_debug`
  - 时序调试信息

适用人群：

- 所有联调角色

## 5.3 `POST /stream/start`

用途：

- 启动指定摄像头的视频采集和处理流水线

请求体：

```json
{
  "camera_id": "camera_01",
  "rtsp_url": "rtsp://admin:***@192.168.8.252:10554/tcp/av0_1",
  "main_rtsp_url": null,
  "analysis_rtsp_url": null
}
```

字段说明：

- `camera_id`
  - 摄像头逻辑 ID
- `rtsp_url`
  - 当前单路模式的权威视频源
- `main_rtsp_url`
  - 兼容字段，单路模式下可忽略
- `analysis_rtsp_url`
  - 兼容字段，单路模式下可忽略

响应示例：

```json
{
  "camera_id": "camera_01",
  "status": "started",
  "message": "stream started",
  "main_rtsp_url": "rtsp://admin:***@192.168.8.252:10554/tcp/av0_1",
  "analysis_rtsp_url": "rtsp://admin:***@192.168.8.252:10554/tcp/av0_1"
}
```

可能状态：

- `started`
- `running`
- `restarted`

错误：

- `409` 流状态冲突或参数错误

## 5.4 `GET /stream/source`

用途：

- 查看当前流运行配置
- 查看当前单路显示源/分析源状态

查询参数：

- `camera_id`，默认 `camera_01`

响应重点字段：

- `running`
- `dual_stream_enabled`
- `display_source_current`
- `display_fallback_active`
- `main_rtsp_url_masked`
- `main_stream_state`
- `main_connected`
- `main_frame_age_ms`
- `main_capture_fps`

典型用途：

- 摄像头重连后确认当前源是否切换成功

## 5.5 `GET /stream/latest-frame.jpg`

用途：

- 获取当前最新原始画面
- 调试摄像头实时帧
- 做抓帧取证

查询参数：

- `camera_id`，默认 `camera_01`

响应：

- `image/jpeg`

响应头：

- `X-Camera-Id`
- `X-Frame-Seq`
- `X-Frame-Age-Ms`

错误：

- `404 LATEST_FRAME_NOT_AVAILABLE`
- `500 LATEST_FRAME_ENCODE_FAILED`

## 5.6 `POST /stream/switch-host`

用途：

- 摄像头 IP 或 Host 变化后快速重建 RTSP 地址
- 常用于移动热点、局域网换地址后的恢复

请求体示例：

```json
{
  "camera_id": "camera_01",
  "host": "192.168.8.252",
  "username": "admin",
  "password": "YOUR_PASSWORD",
  "port": 10554,
  "main_path": "/tcp/av0_0",
  "analysis_path": "/tcp/av0_1",
  "scheme": "rtsp"
}
```

响应：

- `StreamControlResponse`

## 5.7 `POST /stream/probe`

用途：

- 在不启动处理链路的情况下，先探测目标摄像头端口是否可达

请求体：

```json
{
  "host": "192.168.8.252",
  "port": 10554,
  "timeout_ms": 1500
}
```

响应示例：

```json
{
  "host": "192.168.8.252",
  "port": 10554,
  "reachable": true,
  "elapsed_ms": 23.41,
  "error": null
}
```

## 5.8 `POST /stream/stop`

用途：

- 停止某一路摄像头处理

请求体：

```json
{
  "camera_id": "camera_01"
}
```

响应：

- `status=stopped` 或 `status=not_found`

## 5.9 `POST /webrtc/offer`

用途：

- WebRTC 拉流协商入口

请求体：

```json
{
  "camera_id": "camera_01",
  "sdp": "<browser-offer-sdp>",
  "type": "offer"
}
```

响应体：

```json
{
  "peer_id": "peer-xxx",
  "sdp": "<vision-service-answer-sdp>",
  "type": "answer"
}
```

错误：

- `404` 摄像头不存在或 peer 建立失败

## 5.10 `POST /webrtc/candidate`

用途：

- WebRTC ICE candidate 补充

请求体：

```json
{
  "peer_id": "peer-xxx",
  "candidate": {
    "candidate": "...",
    "sdpMid": "0",
    "sdpMLineIndex": 0
  }
}
```

响应：

```json
{
  "ok": true,
  "message": "candidate added"
}
```

## 5.11 `WS /ws/results`

用途：

- 订阅实时识别结果
- 前端 Overlay 与 Demo 页面通常依赖此接口

查询参数：

- `camera_id` 可选

连接方式：

```text
ws://127.0.0.1:<PORT>/ws/results?camera_id=camera_01
```

说明：

- 服务端会把结果推送到订阅者
- 客户端需要维持连接
- 当前实现中客户端也需要持续发送文本心跳，否则连接侧可能因为无消息而难以排查

推送内容：

- `VisionResult` JSON

## 5.12 `POST /identity/enroll`

用途：

- 注册人员身份库

Content-Type：

- `multipart/form-data`

表单字段：

- `person_id`
- `person_name`
- `replace_existing`
- `files`：1 到 `identity_max_images` 张人脸图片

成功响应：

```json
{
  "person_id": "elder_001",
  "person_name": "张三",
  "faces_registered": 3,
  "status": "success"
}
```

错误：

- `400` 上传数量或图片类型不合法
- `409` 身份已存在且不允许覆盖
- `503` 身份服务未可用

## 5.13 `GET /identity/list`

用途：

- 获取当前已注册身份列表

响应示例：

```json
[
  {
    "person_id": "elder_001",
    "person_name": "张三",
    "embedding_count": 3,
    "model_name": "buffalo_l",
    "created_at": "2026-06-19T10:00:00+00:00",
    "updated_at": "2026-06-19T10:00:00+00:00"
  }
]
```

## 5.14 `DELETE /identity/{person_id}`

用途：

- 删除已注册身份

成功响应：

```json
{
  "person_id": "elder_001",
  "status": "deleted"
}
```

错误：

- `404` 身份不存在

## 5.15 `GET /integration/connection-status`

用途：

- 查看 `vision_service` 自身和主系统接收端是否在线

响应示例：

```json
{
  "vision_service": {
    "base_url": "http://10.12.14.29:8001",
    "status": "online"
  },
  "main_system": {
    "base_url": "http://192.168.8.253:8000",
    "status": "connection_error"
  },
  "camera": {
    "camera_id": "camera_01"
  },
  "timestamp": "2026-06-19T06:00:00.000+00:00"
}
```

主系统状态可能值：

- `online`
- `timeout`
- `connection_error`
- `unavailable`

## 5.16 `GET /integration/results/{camera_id}/latest`

用途：

- 获取给主系统或第三方系统消费的“最新标准结果”
- 这是当前最重要的对接读取接口

核心输出字段：

- `camera_id`
- `event_type`
- `state`
- `status`
- `service_state`
- `camera_lost`
- `capture_stale`
- `frame_age_ms`
- `source_fps`
- `analysis_fps`
- `fall_detected`
- `fall_state`
- `risk`
- `risk_level`
- `fall_prob`
- `fall_score`
- `track_id`
- `incident_id`
- `bbox`
- `target`
- `snapshot_url`
- `snapshot_path`
- `alarm_confirmed`
- `scores`
- `injury`
- `metadata`

典型用途：

- 主系统后端轮询
- 管理平台接入
- 结果存档

错误：

- `404 VISION_RESULT_NOT_READY`

## 5.17 `GET /integration/fall-alerts/{camera_id}/poll`

用途：

- 主系统前端或中转层轮询“是否有新的确认跌倒告警”

查询参数：

- `last_incident_id` 可选

响应字段：

- `status`
- `should_popup`
- `incident_id`
- `event_timestamp`
- `fall_state`
- `risk_level`
- `snapshot_url`
- `alert`

适用：

- 前端轮询弹窗
- 轻量联调

## 5.18 `GET /alerting/status`

用途：

- 查看出站告警推送配置和模拟器状态

响应字段：

- `endpoint.base_url`
- `endpoint.path`
- `endpoint.enabled`
- `simulation.running`
- `simulation.target_url`
- `simulation.sent_count`

## 5.19 `POST /alerting/endpoint`

用途：

- 动态修改主系统接收端配置

请求体：

```json
{
  "base_url": "http://192.168.8.253:8000/api/v1",
  "path": "/video-bridge/fall-events",
  "enabled": true
}
```

适用：

- 联调阶段快速切换接收端

## 5.20 `POST /alerting/simulation/start`

用途：

- 启动一个定时发送模拟跌倒告警的后台任务

请求体字段：

- `target_ip`
- `base_url`
- `path`
- `interval_seconds`
- `camera_id`
- `track_id`
- `fall_prob`

说明：

- `target_ip` 和 `base_url` 二选一
- 如果只给 `target_ip`，服务会自动拼接主系统前缀

## 5.21 `POST /alerting/simulation/send-once`

用途：

- 手工发送一次模拟跌倒事件

请求体：

```json
{
  "target_ip": "192.168.8.253",
  "camera_id": "camera_01",
  "track_id": "manual-console-probe",
  "fall_prob": 0.91
}
```

响应体：

- `ok`
- `target_url`
- `status_code`
- `response_body`
- `error`
- `sent_at`
- `incident_id`

## 5.22 `POST /alerting/simulation/stop`

用途：

- 停止模拟告警后台任务

## 5.23 `GET /fall-events/snapshots/{filename}`

用途：

- 获取已落盘的跌倒事件快照

说明：

- 仅允许访问配置快照目录下的 jpg/jpeg
- 有路径穿越保护

错误：

- `400 INVALID_SNAPSHOT_PATH`
- `404 SNAPSHOT_NOT_FOUND`
- `400 UNSUPPORTED_SNAPSHOT_TYPE`

## 6. 推荐调用关系

### 6.1 调试前端 / Overlay

建议使用：

- `GET /status`
- `WS /ws/results`
- `GET /stream/latest-frame.jpg`
- `GET /demo`

### 6.2 主系统后端对接

建议使用：

- `GET /integration/connection-status`
- `GET /integration/results/{camera_id}/latest`
- `GET /integration/fall-alerts/{camera_id}/poll`
- `GET /fall-events/snapshots/{filename}`

### 6.3 摄像头运维

建议使用：

- `POST /stream/probe`
- `POST /stream/start`
- `POST /stream/switch-host`
- `GET /stream/source`
- `GET /status`

## 7. 注意事项

1. `GET /status` 是诊断最全的接口，但它偏调试语义，不建议第三方长期只依赖它做正式业务读取。
2. 正式对接第三方系统时，优先使用 `GET /integration/results/{camera_id}/latest`。
3. `field_rule_debug`、`pose_debug`、`temporal_debug` 属于高价值调试字段，联调阶段建议保留。
4. 快照接口返回的是静态图片，不是视频流。
5. `incident_id` 只有确认跌倒时才有业务意义。
