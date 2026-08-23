# Vision Service 与主系统跌倒告警对接接口文档

更新时间：2026-06-30

本文档说明 `vision_service` 与主系统之间的跌倒告警对接方式。当前系统采用“视频主通道 + AI 旁路分析”：前端实时视频由 WebRTC 播放，AI 结果通过 WebSocket/REST 输出；只有最终确认跌倒时，`vision_service` 才向主系统发送告警事件。

## 1. 当前对接结论

当前视觉服务已经具备向主系统推送告警的能力，运行时配置为：

```env
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
```

实际推送地址为：

```text
POST http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

当前联调失败的直接原因是网络连接失败：

```text
192.168.8.254:8000 connection refused / connection_error
```

因此主系统需要确认：

- 主系统后端是否正在 `192.168.8.254:8000` 监听。
- 主系统是否开放 `/api/v1/video-bridge/fall-events`。
- 防火墙是否允许视觉服务机器访问 `8000/tcp`。
- 如果主系统实际端口或路径不同，需要同步修改视觉服务 `.env` 或调用 `/alerting/endpoint` 更新运行时目标。

## 2. 系统职责边界

`vision_service` 负责：

- 接入摄像头视频流。
- 执行人体检测、跟踪、姿态、跌倒提示、时序模型和融合状态机。
- 在确认跌倒后生成 `fall_confirmed` 事件。
- 保存告警截图。
- 通过 HTTP POST 将最终告警事件推送给主系统。
- 提供前端展示所需的实时视频和 overlay 数据。

主系统负责：

- 提供接收跌倒告警的 HTTP 接口。
- 校验可选鉴权 token。
- 保存告警记录。
- 将告警广播到主系统前端。
- 触发工作人员弹窗、声音、列表刷新或其他业务流程。
- 根据 `snapshot_url` 展示告警截图。

`vision_service` 不会把连续视频流推送给主系统。主系统只接收最终告警事件和截图 URL。

## 3. 主系统必须提供的接口

### 3.1 接收跌倒告警

```http
POST /api/v1/video-bridge/fall-events
Content-Type: application/json
X-Vision-Service-Token: <可选 token>
```

完整 URL 由视觉服务配置拼接：

```text
MAIN_SYSTEM_BASE_URL + MAIN_SYSTEM_FALL_EVENT_PATH
```

当前配置示例：

```text
http://192.168.8.254:8000/api/v1 + /video-bridge/fall-events
= http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

### 3.2 推荐响应

主系统收到后建议返回 `2xx`，例如：

```json
{
  "accepted": true,
  "alarm_id": "alarm_20260630_0001",
  "pushed": true
}
```

视觉服务判断成功的条件是 HTTP 状态码小于 `400`。如果返回 `4xx/5xx`，视觉服务会记录为失败。

## 4. 告警请求字段

确认跌倒后，视觉服务发送 JSON。核心字段如下：

| 字段 | 类型 | 说明 |
|---|---:|---|
| `camera_id` | string | 摄像头 ID，例如 `camera_01` |
| `stream_name` | string | 固定为 `primary` |
| `source` | string | 固定为 `vision_service` |
| `event_type` | string | 固定为 `fall_confirmed` |
| `state` | string | 主状态，通常为 `confirmed_fall` |
| `status` | string | 视觉状态，通常为 `fallen_confirmed` |
| `service_state` | string | 视觉服务状态，通常为 `running` |
| `severity` | string | 告警级别，常见为 `L2` 或 `L3` |
| `risk` | string | 风险等级：`low`、`medium`、`high`、`critical` |
| `risk_level` | string | 同 `risk`，便于主系统兼容 |
| `fall_detected` | boolean | 是否检测到跌倒，确认事件中为 `true` |
| `fall_prob` | number | 跌倒概率，范围 `0.0-1.0` |
| `fall_score` | number | 跌倒分数，通常等于 `fall_prob` |
| `track_id` | string | 跟踪目标 ID |
| `incident_id` | string | 事件唯一 ID，用于去重 |
| `bbox` | number[] | 人体框 `[x1,y1,x2,y2]`，像素坐标 |
| `snapshot_url` | string/null | 告警截图 URL |
| `snapshot_path` | string/null | 视觉服务本地截图路径 |
| `timestamp` | string | ISO 时间戳 |
| `scores` | object | 模型分数字段 |
| `injury` | object | 风险处置建议 |
| `metadata` | object | 调试、模型、融合状态等扩展信息 |

## 5. 告警请求示例

```json
{
  "camera_id": "camera_01",
  "stream_name": "primary",
  "source": "vision_service",
  "event_type": "fall_confirmed",
  "state": "confirmed_fall",
  "status": "fallen_confirmed",
  "service_state": "running",
  "severity": "L3",
  "risk": "critical",
  "risk_level": "critical",
  "fall_detected": true,
  "fall_prob": 0.9464,
  "fall_score": 0.9464,
  "track_id": "1",
  "incident_id": "vision-fall-camera_01_track_1-20260630023353489583",
  "bbox": [216.15, 412.78, 431.14, 480.0],
  "snapshot_url": "http://<vision-service-ip>:8000/fall-events/snapshots/camera_01_1_20260630023353489583.jpg",
  "snapshot_path": "D:\\Program\\vision_service\\logs\\fall_events\\snapshots\\camera_01_1_20260630023353489583.jpg",
  "timestamp": "2026-06-30T02:33:53.489+00:00",
  "scores": {
    "temporal": 0.9464
  },
  "injury": {
    "level": "I3",
    "reason": "vision_service_fallen_confirmed",
    "advice": "Please inspect the live camera view immediately and confirm the elder's condition."
  },
  "metadata": {
    "provider": "onnx_lstm",
    "model_source": "onnx_lstm",
    "frame_seq": 560,
    "frame_width": 720,
    "frame_height": 480,
    "object_confidence": 0.4574,
    "person_id": null,
    "person_name": null,
    "fall_decision": {
      "fall_state": "fallen_confirmed",
      "risk_level": "critical",
      "fall_probability": 0.9464,
      "source": "fusion_state_machine"
    },
    "temporal": {
      "fall_probability": 0.9464,
      "source": "onnx_lstm",
      "window_size": 32,
      "window_ready": true,
      "model_provider": "onnx_lstm"
    }
  }
}
```

主系统最少只需要使用这些字段即可完成弹窗：

```json
{
  "camera_id": "camera_01",
  "event_type": "fall_confirmed",
  "status": "fallen_confirmed",
  "risk_level": "critical",
  "fall_detected": true,
  "fall_prob": 0.9464,
  "incident_id": "vision-fall-camera_01_track_1-...",
  "snapshot_url": "http://<vision-service-ip>:8000/fall-events/snapshots/xxx.jpg",
  "timestamp": "2026-06-30T02:33:53.489+00:00"
}
```

## 6. 去重规则

主系统应使用 `incident_id` 去重。

建议逻辑：

- 如果 `incident_id` 已存在，不重复创建新告警。
- 如果是新的 `incident_id` 且 `fall_detected=true`，立即创建或更新跌倒告警。
- `risk_level=critical` 或 `severity=L3` 时，主系统前端应立即弹窗。

视觉服务自身也有冷却时间：

```env
MAIN_SYSTEM_ALERT_COOLDOWN_SECONDS=90
```

该冷却用于避免同一跌倒连续刷屏，但主系统仍应保留自己的 `incident_id` 幂等保护。

## 7. 截图访问接口

视觉服务会保存告警截图，并在 payload 中给出：

```text
snapshot_url
```

主系统可以直接通过 HTTP GET 访问：

```http
GET http://<vision-service-ip>:8000/fall-events/snapshots/{filename}
```

返回：

```http
Content-Type: image/jpeg
```

注意：

- `snapshot_url` 中的 host 来自 `VISION_SERVICE_PUBLIC_BASE_URL`。
- 该地址必须是主系统前端和后端都能访问到的视觉服务地址。
- 当前 `.env` 中为 `http://10.12.14.29:8000`，但当前启动脚本可能会在运行时覆盖为本机 LAN 地址。联调时请以 `/status` 或实际 payload 为准。

## 8. 视觉服务提供给主系统的可选查询接口

这些接口由视觉服务提供，主系统可以用来做兜底轮询或状态诊断。

### 8.1 连接状态

```http
GET http://<vision-service-ip>:8000/integration/connection-status
```

返回示例：

```json
{
  "vision_service": {
    "base_url": "http://192.168.8.252:8000",
    "status": "online"
  },
  "main_system": {
    "base_url": "http://192.168.8.254:8000",
    "status": "connection_error"
  },
  "camera": {
    "camera_id": "camera_01"
  },
  "timestamp": "2026-06-30T02:21:22.676+00:00"
}
```

`main_system.status` 可能值：

- `online`：主系统 `/healthz` 可访问。
- `connection_error`：无法建立 TCP 连接。
- `timeout`：连接超时。
- `unavailable`：主系统返回非成功状态或其他请求异常。

### 8.2 最新识别结果

```http
GET http://<vision-service-ip>:8000/integration/results/{camera_id}/latest
```

当还没有结果时返回：

```json
{
  "detail": "VISION_RESULT_NOT_READY"
}
```

有结果时会返回当前最新 `VisionResult`，并补充：

- `fall_detected`
- `fall_state`
- `risk_level`
- `incident_id`
- `snapshot_url`
- `alarm_confirmed`
- `camera_lost`
- `capture_stale`

### 8.3 跌倒告警轮询

```http
GET http://<vision-service-ip>:8000/integration/fall-alerts/{camera_id}/poll
```

可选参数：

```text
last_incident_id=<主系统前端上次已展示的 incident_id>
```

返回示例：

```json
{
  "camera_id": "camera_01",
  "status": "new_alert",
  "should_popup": true,
  "last_incident_id": null,
  "incident_id": "vision-fall-camera_01_track_1-...",
  "event_timestamp": "2026-06-30T02:33:53.489+00:00",
  "fall_state": "fallen_confirmed",
  "risk_level": "critical",
  "snapshot_url": "http://<vision-service-ip>:8000/fall-events/snapshots/xxx.jpg",
  "alert": {
    "event_type": "fall_confirmed"
  }
}
```

主系统前端如果采用轮询兜底：

- `should_popup=true` 时弹窗。
- 弹窗后保存 `incident_id`。
- 下一次请求带上 `last_incident_id`，避免重复弹窗。

## 9. 视觉服务告警配置接口

### 9.1 查看告警配置

```http
GET http://<vision-service-ip>:8000/alerting/status
```

返回当前目标：

```json
{
  "endpoint": {
    "base_url": "http://192.168.8.254:8000/api/v1",
    "path": "/video-bridge/fall-events",
    "enabled": true,
    "dry_run": false,
    "token_header": "X-Vision-Service-Token"
  },
  "simulation": {
    "running": false,
    "target_url": "http://192.168.8.254:8000/api/v1/video-bridge/fall-events"
  }
}
```

### 9.2 临时更新主系统地址

```http
POST http://<vision-service-ip>:8000/alerting/endpoint
Content-Type: application/json
```

请求：

```json
{
  "base_url": "http://192.168.8.254:8000/api/v1",
  "path": "/video-bridge/fall-events",
  "enabled": true
}
```

注意：该接口只更新运行时配置，不会永久写入 `.env`。服务重启后仍以 `.env` 或启动脚本参数为准。

### 9.3 单次模拟告警

仅用于联调主系统接口，不依赖真实摄像头。

```http
POST http://<vision-service-ip>:8000/alerting/simulation/send-once
Content-Type: application/json
```

请求：

```json
{
  "target_ip": "192.168.8.254",
  "camera_id": "camera_01",
  "track_id": "manual-console-probe",
  "fall_prob": 0.91
}
```

视觉服务会发送到：

```text
http://{target_ip}:8000/api/v1/video-bridge/fall-events
```

## 10. 主系统侧推荐实现

主系统应实现：

```http
GET /healthz
POST /api/v1/video-bridge/fall-events
```

`GET /healthz` 用于视觉服务诊断主系统是否在线。

`POST /api/v1/video-bridge/fall-events` 推荐处理流程：

1. 读取 JSON。
2. 校验 `event_type == "fall_confirmed"`。
3. 校验 `incident_id` 是否已存在。
4. 保存告警记录。
5. 将 `risk_level`、`camera_id`、`snapshot_url`、`timestamp`、`fall_prob` 推给主系统前端。
6. 主系统前端收到后立即弹窗。
7. 返回 `2xx`。

主系统可选校验 token：

```http
X-Vision-Service-Token: <token>
```

如果当前没有启用 token，可以先允许空 token，待联调通过后再启用。

## 11. 当前问题排查清单

当前视觉服务到主系统失败，已观察到：

```text
Test-NetConnection 192.168.8.254 -Port 8000 = False
GET /integration/connection-status -> main_system.status = connection_error
fall_event_reporter.last_post_status = request_error
```

请按顺序排查：

1. 在主系统机器上确认后端已启动。
2. 在主系统机器上执行：

```powershell
netstat -ano | findstr :8000
```

3. 确认后端监听地址不是只绑定 `127.0.0.1`。局域网联调应监听 `0.0.0.0:8000` 或主机 LAN IP。
4. 在视觉服务机器上执行：

```powershell
Test-NetConnection 192.168.8.254 -Port 8000
```

5. 确认 Windows 防火墙允许主系统后端端口入站。
6. 确认两台机器在同一网络，IP 没有变化。
7. 访问：

```text
http://192.168.8.254:8000/healthz
```

8. 再访问视觉服务：

```text
http://127.0.0.1:8000/integration/connection-status
```

当 `main_system.status=online` 后，再测试真实跌倒告警或模拟告警。

## 12. 摄像头对接状态说明

当前摄像头重启接收后仍失败：

```text
camera_id = camera_01
source = rtsp://admin:***@192.168.8.252:10554/tcp/av0_1
stream_state = connecting
connected = false
last_error = stream closed
frame_seq = 0
```

视觉服务已经重新执行过：

```http
POST /stream/stop
POST /stream/start
```

仍无帧进入，说明问题不在前端 overlay，也不是 AI 旁路，而是 RTSP 输入源当前不可达或摄像头没有输出。

摄像头排查建议：

```powershell
Test-NetConnection 192.168.8.252 -Port 10554
```

必须为 `True` 后，视觉服务才可能拿到实时画面。

## 13. 联调验收标准

完整联调通过应同时满足：

- `GET /healthz` 返回 `{"status":"ok"}`。
- `GET /status?camera_id=camera_01` 中 `connected=true`，`frame_seq` 持续增长。
- 前端 `/demo` 中 WebRTC 为 `connected`，Video Frames 持续增长。
- WebSocket 有实时结果，`Persons` 和 overlay 随画面变化。
- 真实跌倒后出现 `fallen_confirmed`。
- `fall_event_reporter.last_post_status` 为 `http_200`、`http_201` 或其他 `http_2xx`。
- 主系统收到 `incident_id`，前端弹窗。
- `snapshot_url` 可以打开 JPEG 图片。

当前尚未通过的项目：

- 摄像头 RTSP 不可达，真实画面未进入系统。
- 主系统 `192.168.8.254:8000` 不可达，真实 POST 告警无法送达。
