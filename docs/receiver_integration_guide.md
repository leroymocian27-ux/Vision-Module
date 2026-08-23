# Vision Service 与主系统对接文档

更新时间：2026-06-15 20:35 Asia/Shanghai

适用对象：

- 主系统后端开发
- 主系统前端开发
- 联调与部署人员

相关代码入口：

- 告警发送逻辑：[fall_event_reporter_service.py](/D:/Program/vision_service/app/services/fall_event_reporter_service.py)
- 运行时告警配置接口：[alerting_api.py](/D:/Program/vision_service/app/api/alerting_api.py)
- 快照下载接口：[fall_events_api.py](/D:/Program/vision_service/app/api/fall_events_api.py)
- 手工冒烟脚本：[post_test_fall_event.py](/D:/Program/vision_service/scripts/post_test_fall_event.py)
- 局域网配置说明：[lan_alert_setup.md](/D:/Program/vision_service/docs/lan_alert_setup.md)

## 1. 文档目标

本文档说明 `vision_service` 如何把“确认跌倒”事件推送到另一台主系统服务器，以及主系统后端、主系统前端分别需要完成哪些工作，最终让主系统前端可以弹出告警。

本文档覆盖三段链路：

1. `vision_service` 发现跌倒并生成告警
2. `vision_service` 通过 HTTP 把告警发送给主系统后端
3. 主系统后端把告警再推送给主系统前端并触发弹窗

## 2. 当前联调结论

截至 `2026-06-15 20:27 Asia/Shanghai`，本机已完成以下验证：

- 视频流实时处理正常
- Vision Service 告警推送功能已启用
- 主系统主机 `http://192.168.8.254:8000/healthz` 可访问，返回 `{"status":"ok"}`

但当前端到端链路还没有完全打通，原因是：

- Vision Service 实际向主系统发送 `POST http://192.168.8.254:8000/api/v1/video-bridge/fall-events`
- 主系统当前返回 `404 Not Found`

这意味着：

- 网络基本可达
- 主系统当前监听地址和端口是通的
- 但主系统并没有正确暴露 Vision Service 期望的接收接口，或者路径与当前约定不一致

因此，当前状态不能说“已经可以在主系统前端弹出跌倒告警”，只能说“本地实时处理正常，但主系统接收接口尚未对齐”。

## 3. 对接总览

```text
摄像头 RTSP
-> Vision Service 采集
-> 检测 / 跟踪 / 跌倒确认
-> Vision Service 生成告警 JSON
-> POST 到主系统后端 /api/v1/video-bridge/fall-events
-> 主系统后端落库 / 去重 / 转发
-> 主系统前端收到推送
-> 前端弹窗、播报、展示快照
```

推荐的主系统处理方式：

- 后端负责接收、校验、去重、落库、转发
- 前端不要直接暴露为 Vision Service 的接收端
- 前端应通过 WebSocket、SSE 或轮询从主系统后端获取告警

## 4. Vision Service 什么时候会发告警

Vision Service 不是“检测到有人倒地框”就立即发送，而是只在满足“确认跌倒”的条件后发送。

当前发送条件来自代码中的以下判断：

- `fall_decision.fall_state` 为 `fallen_confirmed` 或 `confirmed_fall`
- 或 `alarm_preview.confirmed=true` 且 `risk_level` 属于 `high` / `critical`

当前还有一个发送冷却机制：

- 同一空间位置的重复跌倒事件会进入冷却
- 冷却时间由 `.env` 中 `MAIN_SYSTEM_ALERT_COOLDOWN_SECONDS` 控制
- 当前默认值是 `90` 秒

因此主系统不应该假设“每一帧都能收到推送”，而应认为：

- Vision Service 只在确认事件时发一次
- 同一事件短时间内不会高频重复推送

## 5. Vision Service 当前关键配置

当前本机运行时相关配置如下：

```text
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN=YOUR_BRIDGE_TOKEN
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
VISION_SERVICE_PUBLIC_BASE_URL=http://10.12.14.29:8000
```

说明：

- 告警推送已启用
- 当前主系统接收目标是 `192.168.8.254:8000`
- Vision Service 发送时会带令牌头 `X-Vision-Service-Token`
- `VISION_SERVICE_PUBLIC_BASE_URL` 决定告警里的 `snapshot_url`

注意：

- 如果主系统需要访问告警快照，`VISION_SERVICE_PUBLIC_BASE_URL` 必须是主系统可访问的 Vision Service 局域网地址
- 不能填 `127.0.0.1`
- 也不能填主系统无法访问的网卡地址

## 6. 主系统必须提供的接收接口

主系统后端至少需要提供以下接口：

```http
POST /api/v1/video-bridge/fall-events
Content-Type: application/json
X-Vision-Service-Token: <token>
```

其中：

- 路径必须与 Vision Service 当前配置一致
- 方法必须是 `POST`
- 请求体必须接受 JSON
- 如启用鉴权，必须校验请求头中的令牌

当前 Vision Service 对成功的定义非常直接：

- 只要主系统返回 HTTP 状态码 `< 400`，Vision Service 就认为发送成功

因此主系统建议返回：

- `200 OK`
- `201 Created`
- `202 Accepted`

不建议返回：

- `409 Conflict`

原因是：

- Vision Service 当前会把 `409` 当作失败
- 如果主系统想做幂等，建议内部去重但外部仍返回 `200` 或 `202`

## 7. Vision Service 实际发送的 URL

最终 URL 的拼接规则为：

```text
MAIN_SYSTEM_BASE_URL + MAIN_SYSTEM_FALL_EVENT_PATH
```

当前运行时对应的是：

```text
http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

主系统如果路径不同，有两种改法：

1. 改主系统，让它暴露这个路径
2. 改 Vision Service 配置：

```text
MAIN_SYSTEM_BASE_URL=http://<主系统IP>:<端口>/<你的前缀>
MAIN_SYSTEM_FALL_EVENT_PATH=/你的实际路径
```

也可以运行时动态修改：

```http
POST /alerting/endpoint
```

请求示例：

```json
{
  "base_url": "http://192.168.8.254:8000/api/v1",
  "path": "/video-bridge/fall-events",
  "enabled": true
}
```

## 8. 请求头契约

如果配置了告警令牌，Vision Service 会附带：

```http
X-Vision-Service-Token: YOUR_BRIDGE_TOKEN
```

请求头名称可由 `MAIN_SYSTEM_ALERT_TOKEN_HEADER` 修改。

主系统后端推荐做法：

- 如果当前环境启用了校验，则严格校验该请求头
- 校验失败返回 `401` 或 `403`
- 校验通过继续处理

如果当前环境暂不启用鉴权，也建议保留该字段的日志记录能力，便于后续切换到正式部署。

## 9. 请求超时与重试语义

Vision Service 当前使用同步 HTTP 请求发送，每次请求超时时间来自：

```text
MAIN_SYSTEM_ALERT_TIMEOUT_MS
```

当前默认值是：

```text
10000 ms
```

主系统建议：

- 接口尽量快速返回，不要把耗时业务放在这个同步请求里
- 建议“先接收、先落队列/库、先返回 200”，再异步做后续前端推送或复杂业务

## 10. Vision Service 发送的 JSON 结构

下面是根据当前发送代码整理出的实际字段结构示例：

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
  "fall_prob": 0.91,
  "fall_score": 0.91,
  "track_id": "7",
  "incident_id": "vision-fall-camera_01-...",
  "bbox": [100.0, 120.0, 300.0, 420.0],
  "snapshot_url": "http://<vision-host>:8000/fall-events/snapshots/xxx.jpg",
  "snapshot_path": "http://<vision-host>:8000/fall-events/snapshots/xxx.jpg",
  "timestamp": "2026-06-15T12:27:45.191+00:00",
  "scores": {
    "temporal": 0.91,
    "shadow_onnx_lstm": 0.88
  },
  "injury": {
    "level": "I3",
    "reason": "vision_service_fallen_confirmed",
    "advice": "Please inspect the live camera view immediately and confirm the elder's condition."
  },
  "metadata": {
    "provider": "mock",
    "model_source": "",
    "feature_schema_hash": null,
    "frame_seq": 1234,
    "frame_width": 640,
    "frame_height": 360,
    "object_confidence": 0.95,
    "incident_spatial_key": "camera_01:fall:...",
    "person_id": null,
    "person_name": null,
    "fall_decision": {
      "fall_state": "fallen_confirmed",
      "risk_level": "critical"
    },
    "alarm_preview": {
      "confirmed": true,
      "risk_level": "critical"
    },
    "temporal": {}
  }
}
```

## 11. 字段说明

### 11.1 顶层核心字段

| 字段 | 类型 | 含义 | 主系统建议用途 |
| --- | --- | --- | --- |
| `camera_id` | string | 摄像头 ID | 告警来源标识 |
| `event_type` | string | 当前固定为 `fall_confirmed` | 主系统事件类型路由 |
| `status` | string | 当前常见值 `fallen_confirmed` | 前端展示状态 |
| `risk_level` | string | `low/medium/high/critical` | 决定告警等级、颜色、声音 |
| `fall_prob` | number | 跌倒概率 | 前端展示和规则筛选 |
| `track_id` | string | 轨迹或目标 ID | 调试排查 |
| `incident_id` | string | 事件唯一标识 | 幂等键、去重键 |
| `bbox` | number[] | 人体框 `[x1,y1,x2,y2]` | 复现定位 |
| `timestamp` | string | 事件时间，UTC ISO 8601 | 排序、展示、时序检索 |
| `snapshot_url` | string/null | Vision Service 暴露的快照地址 | 主系统前端弹窗配图 |

### 11.2 告警级别字段

| 字段 | 含义 |
| --- | --- |
| `severity` | 主系统可直接映射为业务告警等级，当前常见 `L3` |
| `risk` | 风险等级，通常与 `risk_level` 一致 |
| `risk_level` | 当前最适合作为主系统前端展示等级 |
| `injury.level` | 附加伤害等级建议，当前常见 `I2/I3` |

### 11.3 `metadata` 字段

`metadata` 主要用于排查和回溯，建议主系统后端完整保存，不建议前端直接强依赖全部字段。

比较重要的字段有：

- `frame_seq`
- `frame_width`
- `frame_height`
- `object_confidence`
- `incident_spatial_key`
- `person_id`
- `person_name`
- `fall_decision`
- `alarm_preview`
- `temporal`

## 12. 主系统后端需要做什么

主系统后端建议至少完成以下逻辑：

1. 接收 Vision Service 的 `POST`
2. 校验鉴权头
3. 解析 JSON
4. 使用 `incident_id` 做幂等去重
5. 落库或写入告警队列
6. 向主系统前端广播一条“新跌倒告警”事件
7. 返回 `<400` 的状态码给 Vision Service

推荐的后端处理模型：

```text
接收 HTTP 请求
-> 校验 token
-> JSON 解析
-> incident_id 去重
-> 保存 alarm_event
-> 发布 websocket/sse/internal event
-> 立即返回 200
```

不推荐：

- 在这个同步请求里做复杂的图像下载、AI 二次分析、人工审批
- 因为这会增加 Vision Service 的超时风险

## 13. 主系统前端需要做什么

主系统前端并不是直接接收 Vision Service 的 HTTP 推送，而应该接收主系统后端的内部消息。

推荐流程：

1. 主系统后端收到跌倒事件
2. 主系统后端把事件广播给前端
3. 主系统前端收到后立刻弹窗
4. 前端展示：
   - 摄像头名称或 `camera_id`
   - 风险等级
   - 时间
   - 快照图
   - “查看监控/确认告警/忽略告警”动作

前端推荐弹窗字段：

- `camera_id`
- `event_type`
- `status`
- `risk_level`
- `fall_prob`
- `timestamp`
- `snapshot_url`
- `person_name` 或 `person_id`（如果有）

前端推荐行为：

- 首次收到新 `incident_id` 时弹窗
- 同一 `incident_id` 重复到达时只更新不重复弹窗
- 快照图加载失败时，仍保留文本告警

## 14. 主系统最小接收示例

下面给一个最小 FastAPI 接收端示例，仅用于联调：

```python
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI()

TOKEN = "YOUR_BRIDGE_TOKEN"
seen_incidents = set()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/v1/video-bridge/fall-events")
async def receive_fall_event(
    request: Request,
    x_vision_service_token: str | None = Header(default=None),
):
    if x_vision_service_token != TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")

    payload = await request.json()
    incident_id = str(payload.get("incident_id") or "").strip()
    if not incident_id:
        raise HTTPException(status_code=400, detail="incident_id is required")

    is_duplicate = incident_id in seen_incidents
    seen_incidents.add(incident_id)

    # TODO: 写数据库 / 推送前端 websocket

    return {
        "ok": True,
        "accepted": True,
        "duplicate": is_duplicate,
        "pushed": True,
        "alarm_id": incident_id,
    }
```

## 15. 快照访问约定

当 Vision Service 成功生成快照时，告警中会包含：

- `snapshot_url`
- `snapshot_path`

它们当前都是同一个 URL，指向：

```text
GET /fall-events/snapshots/{filename}
```

Vision Service 自身通过这个接口对外暴露 JPG 快照。

主系统如果需要显示快照，必须确保：

- 主系统可以访问 `VISION_SERVICE_PUBLIC_BASE_URL`
- Vision Service 是以 `--host 0.0.0.0` 启动
- Vision Service 所在机器防火墙允许外部访问 `8000/tcp`

## 16. Vision Service 侧配置方法

### 16.1 通过 `.env` 固化配置

编辑 [`.env`](/D:/Program/vision_service/.env)：

```text
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_BASE_URL=http://<主系统IP>:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
MAIN_SYSTEM_ALERT_TOKEN=<你的token>
MAIN_SYSTEM_ALERT_TOKEN_HEADER=X-Vision-Service-Token
VISION_SERVICE_PUBLIC_BASE_URL=http://<Vision-Service-IP>:8000
```

修改后重启 Vision Service。

### 16.2 通过接口临时修改

查看当前状态：

```http
GET /alerting/status
```

临时改接收端：

```http
POST /alerting/endpoint
Content-Type: application/json
```

请求体示例：

```json
{
  "base_url": "http://192.168.8.254:8000/api/v1",
  "path": "/video-bridge/fall-events",
  "enabled": true
}
```

## 17. 联调命令

### 17.1 检查 Vision Service 当前告警配置

```powershell
Invoke-RestMethod http://127.0.0.1:8000/alerting/status |
  ConvertTo-Json -Depth 20
```

### 17.2 检查主系统主机是否在线

```powershell
Invoke-RestMethod http://192.168.8.254:8000/healthz
```

### 17.3 从 Vision Service 侧发送一条模拟告警

```powershell
$body = @{
  target_ip = "192.168.8.254"
  camera_id = "camera_01"
  track_id = "manual-probe"
  fall_prob = 0.91
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8000/alerting/simulation/send-once `
  -Method POST `
  -ContentType "application/json" `
  -Body $body |
  ConvertTo-Json -Depth 20
```

### 17.4 直接用脚本发测试告警

```powershell
cd D:\Program\vision_service
python scripts\post_test_fall_event.py --main-system-base-url http://192.168.8.254:8000/api/v1
```

## 18. 当前问题定位

当前联调结果显示：

- `GET http://192.168.8.254:8000/healthz` 成功
- `POST http://192.168.8.254:8000/api/v1/video-bridge/fall-events` 返回 `404`

这说明最可能的问题是下面之一：

1. 主系统并没有挂载 `/api/v1/video-bridge/fall-events`
2. 主系统接口前缀不是 `/api/v1`
3. 主系统实际路径不是 `/video-bridge/fall-events`
4. 当前 `8000` 端口上跑的是一个“健康检查可用但告警路由未加载”的服务

建议主系统团队优先确认：

- 当前服务实际路由清单
- 正确的跌倒接收路径
- 是否需要额外的网关或反向代理前缀

## 19. 验收标准

只有当下面所有条件都满足时，才能说“Vision Service 已和主系统打通”：

1. Vision Service 能实时分析视频
2. Vision Service 检测到确认跌倒时生成告警
3. 主系统后端成功返回 `<400`
4. 主系统后端保存并广播该事件
5. 主系统前端收到事件并弹窗
6. 主系统前端可选地展示 `snapshot_url`

建议最小验收记录至少包含：

- 事件时间
- 请求 URL
- HTTP 状态码
- `incident_id`
- 主系统落库记录 ID
- 主系统前端截图

## 20. 一句话总结

Vision Service 这一侧已经具备“生成跌倒告警并主动推送”的能力；主系统当前还缺少与之匹配的接收接口，只有在主系统正确提供 `POST /api/v1/video-bridge/fall-events` 并把收到的事件继续广播给前端后，另一台服务器前端的弹窗告警链路才算真正完成。
