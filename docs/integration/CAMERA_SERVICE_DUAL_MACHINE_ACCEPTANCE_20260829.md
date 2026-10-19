# camera-service 双机真实联调验收复测 2026-08-29

## 结论

最终结果：**A-F PASS；真实跌倒测试 NOT RUN**

本轮已完成主系统局域网告警链路复测，`camera-service -> main-system -> ACK -> 主系统 alarm` 全链路通过。真实跌倒测试未执行，原因是当前运行态没有摄像头流：`stream_connected=false` / `camera_stream_state=disabled`。

## 当前电脑和项目

| 项 | 结果 |
| --- | --- |
| 项目目录 | `E:\HealthProtection\camera-service` |
| 本机实测 IPv4 | `192.168.8.253` |
| 主系统 IPv4 | `192.168.8.254` |
| 主系统 Base URL | `http://192.168.8.254:8000` |
| camera-service URL | `http://127.0.0.1:8000` / `0.0.0.0:8000` |
| GPU Conda Python | `E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe` |

## 本轮必要修复

复测前发现 `POST /alerting/simulation/send-once` 存在竞态：手动同步发送前先写入 outbox pending，后台 worker 可能抢先发送同一事件，导致首次 ACK 被污染成重复/本地 attempts 增加。

已做最小修复：

1. `send_external_alert_once()` 不再在同步 POST 前预先写 pending。
2. `AlertOutboxService.record_result()` 支持无 pending 行时 upsert 结果，保证同步发送失败仍可进入 retry/outbox。
3. 新增测试覆盖：手动 send-once 同步 POST 前 outbox pending 数为 0，首发 attempts 为 1；无 pending 行也能记录失败并重试。

未修改 EfficientNet、ONNX、采样率、视频流、MJPEG、Qwen prompt、`follow_target`。

## 本地回归

```text
python -m py_compile app/services/fall_event_reporter_service.py app/services/alert_simulator_service.py app/services/alert_outbox_service.py tests/test_alerting_manual_send.py tests/test_async_workers_and_outbox.py
python -m pytest tests/test_alerting_manual_send.py tests/test_fall_event_reporter_service.py tests/test_async_workers_and_outbox.py -q
```

结果：

```text
30 passed in 1.48s
```

补充验证：

```text
python -m pytest tests/test_fall_event_reporter_service.py -q
18 passed in 0.62s
```

关键覆盖包含：

| 用例 | 结论 |
| --- | --- |
| `test_post_fall_v2_safety_deny_does_not_queue_main_system_alert` | 非 alert 决策不入主系统发送队列 |
| `test_upright_recovery_field_confirm_is_blocked_by_reporter_guard` | 恢复直立后阻断误报 |
| `test_dry_run_skips_http_post_and_records_status_without_token` | dry-run 不 HTTP POST，且不泄露 token |
| `test_send_once_does_not_prequeue_pending_before_sync_post` | 手动 send-once 不再预排 pending，首发不会被 worker 抢跑 |

## 服务启动状态

启动命令：

```powershell
$env:MAIN_SYSTEM_BASE_URL='http://192.168.8.254:8000'
$env:MAIN_SYSTEM_ALERT_ENABLED='true'
$env:MAIN_SYSTEM_REPORT_DRY_RUN='false'
$env:ALERT_OUTBOX_ENABLED='true'
$env:MAIN_SYSTEM_ALERT_PATH='/api/integrations/fall-detection/alerts'
$env:MAIN_SYSTEM_HEALTH_PATH='/api/integrations/fall-detection/health'
$env:MAIN_SYSTEM_INTEGRATION_TOKEN=''
$env:MAIN_SYSTEM_ALERT_TOKEN=''
$env:MAIN_SYSTEM_ALERT_TOKEN_HEADER='X-Vision-Service-Token'
$env:TEST_EVENT_ROOT='E:\HealthProtection\event'
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行证据：

| 项 | 结果 |
| --- | --- |
| Uvicorn PID | `37144` |
| Reporter endpoint | `http://192.168.8.254:8000/api/integrations/fall-detection/alerts` |
| `dry_run` | `false` |
| outbox | enabled |
| Binary provider | `CUDAExecutionProvider` |
| Service status | `running` |

## TEST A TCP

```text
ComputerName     : 192.168.8.254
RemoteAddress    : 192.168.8.254
RemotePort       : 8000
InterfaceAlias   : WLAN
SourceAddress    : 192.168.8.253
TcpTestSucceeded : True
```

结果：**PASS**

## TEST B Health

请求：

```text
GET http://192.168.8.254:8000/api/integrations/fall-detection/health
```

响应：

```json
{
  "ok": true,
  "service": "main-system",
  "fall_detection_receiver": true,
  "timestamp": "2026-08-29T12:29:39.664263Z"
}
```

结果：**PASS**

## TEST C 首次测试告警

通过 camera-service reporter 发送，不绕过 camera-service 直接打主系统：

```text
POST http://127.0.0.1:8000/alerting/simulation/send-once
event_id=lan-e2e-20260829-rerun-001
camera_id=go2_front_camera
fall_prob=0.91
```

响应：

```json
{
  "ok": true,
  "target_url": "http://192.168.8.254:8000/api/integrations/fall-detection/alerts",
  "status_code": 200,
  "incident_id": "lan-e2e-20260829-rerun-001"
}
```

主系统 ACK：

```json
{
  "accepted": true,
  "alarm_id": "46e0e7a8-7489-4335-918e-dca1ec785937",
  "alert_created": true,
  "duplicate": false,
  "event_id": "lan-e2e-20260829-rerun-001",
  "ok": true,
  "storage_path": "fall_alerts/20260829/lan-e2e-20260829-rerun-001"
}
```

本地证据：

| 文件 | 结果 |
| --- | --- |
| `E:\HealthProtection\event\go2_front_camera\lan-e2e-20260829-rerun-001\main_system_alert.json` | 已生成 |
| `E:\HealthProtection\event\go2_front_camera\lan-e2e-20260829-rerun-001\main_system_delivery.json` | `status=delivered`, `attempts=1`, `last_http_status=200`, `duplicate=false` |

主系统 `/api/v1/alarms`：

| 项 | 结果 |
| --- | --- |
| 同 event_id 记录数 | `1` |
| alarm id | `46e0e7a8-7489-4335-918e-dca1ec785937` |
| message | `视频跌倒告警 | camera=go2_front_camera | state=confirmed_fall | score=0.91` |

结果：**PASS**

## TEST D Duplicate

复用同一事件：

```text
event_id=lan-e2e-20260829-rerun-001
```

ACK：

```json
{
  "accepted": true,
  "alarm_id": "46e0e7a8-7489-4335-918e-dca1ec785937",
  "alert_created": true,
  "duplicate": true,
  "event_id": "lan-e2e-20260829-rerun-001",
  "ok": true
}
```

主系统 `/api/v1/alarms` 同 event_id 记录数仍为 `1`。

结果：**PASS**

备注：Vue 弹窗“只弹一次/重复不弹第二次”仍需要现场人工目视确认。本轮后端和 ACK 层已验证主系统没有新增第二条同 event_id alarm。

## TEST E 非告警决策

本轮不伪造真实安全决策，只用自动化测试证明 gate：

| 验证 | 结果 |
| --- | --- |
| safety deny 不 queue 主系统告警 | PASS |
| upright recovery 阻断误报 | PASS |
| reporter dry-run 不 HTTP POST | PASS |

结果：**PASS by unit/simulation evidence**

## TEST F Outbox 断线恢复

不可达目标：

```text
base_url=http://127.0.0.1:9
event_id=lan-e2e-20260829-rerun-retry-001
```

失败响应：

```json
{
  "ok": false,
  "status_code": null,
  "incident_id": "lan-e2e-20260829-rerun-retry-001",
  "error": "HTTPConnectionPool(host='127.0.0.1', port=9)... connect timeout=2.0"
}
```

失败后状态：

| 项 | 结果 |
| --- | --- |
| `service_status` | `running` |
| delivery status | `retry_wait` |
| outbox retry_wait_count | `1` |
| main_system_pending_count | `1` |

恢复 endpoint：

```text
POST /alerting/endpoint
base_url=http://192.168.8.254:8000
path=/api/integrations/fall-detection/alerts
```

触发重试：

```text
POST /alerting/main-system/retry-pending
```

响应：

```json
{
  "queued": 1,
  "event_ids": ["lan-e2e-20260829-rerun-retry-001"],
  "include_failed": true
}
```

最终 delivery：

```json
{
  "event_id": "lan-e2e-20260829-rerun-retry-001",
  "status": "delivered",
  "attempts": 5,
  "last_http_status": 200,
  "last_error": null,
  "ack": {
    "accepted": true,
    "alarm_id": "b3f8a705-22ca-4d2c-a305-88abb03b2355",
    "duplicate": false,
    "event_id": "lan-e2e-20260829-rerun-retry-001",
    "ok": true
  }
}
```

主系统 `/api/v1/alarms`：

| 项 | 结果 |
| --- | --- |
| 同 event_id 记录数 | `1` |
| alarm id | `b3f8a705-22ca-4d2c-a305-88abb03b2355` |
| message | `视频跌倒告警 | camera=go2_front_camera | state=confirmed_fall | score=0.92` |

最终 reporter 状态：

```json
{
  "service_status": "running",
  "endpoint": "http://192.168.8.254:8000/api/integrations/fall-detection/alerts",
  "last_post_status": "delivered",
  "last_incident_id": "lan-e2e-20260829-rerun-retry-001",
  "last_error": null,
  "queue_size": 0,
  "main_system_pending_count": 0,
  "outbox": {
    "pending_count": 0,
    "retry_wait_count": 0,
    "failed_count": 0,
    "delivered_count": 3,
    "last_status": "delivered",
    "last_error": null
  }
}
```

结果：**PASS**

## 真实跌倒测试

结果：**NOT RUN**

原因：当前 camera-service 运行态无实际摄像头流。

```json
{
  "runtime_profile": "safe_demo",
  "cameras": [],
  "stream_connected": false,
  "latest_result": {
    "frame_status": "no_frame",
    "camera_stream_state": "disabled",
    "reason": "camera_disabled"
  },
  "runtime_control": {
    "binary_model_loaded": true,
    "binary_provider": "CUDAExecutionProvider",
    "running": false
  }
}
```

必须先接入/启动 Go2 摄像头流，再进行真人跌倒动作验收。

## 总表

| Test | Result |
| --- | --- |
| TEST A TCP | PASS |
| TEST B Health | PASS |
| TEST C 首次测试告警 | PASS |
| TEST D Duplicate | PASS |
| TEST E deny/observe/dismiss gate | PASS by tests |
| TEST F Outbox 断线恢复 | PASS |
| 真实跌倒 | NOT RUN：无摄像头流 |

## 仍需人工确认

1. Vue 页面是否在 TEST C 首次告警时弹出一次。
2. Vue 页面是否在 TEST D duplicate 时不弹第二次。
3. 接入 Go2 实时流后，再执行真实跌倒：确认 `Binary -> Qwen -> safety_outcome=alert -> Reporter -> Main System ACK -> Vue popup` 全链路。
