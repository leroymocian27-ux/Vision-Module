# 主系统对接方案

## 1. 当前视频地址基线

当前视觉服务推荐使用双流：

```text
main:     rtsp://admin:***@<camera-ip>:10554/tcp/av0_0
analysis: rtsp://admin:***@<camera-ip>:10554/tcp/av0_1
```

- `main`：给 WebRTC 显示画面用。
- `analysis`：给检测、跟踪、姿态、跌倒 preview 用。
- 移动 WiFi 或摄像头重启后，通常只需要更新 `<camera-ip>`。
- 当前不建议自动尝试 `554 / 8554`，验收基线仍固定为 `10554`。

## 2. 视觉服务启动

建议主系统或运维脚本把视觉服务启动在局域网可访问地址：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

主系统把 `<vision-host>` 替换成视觉服务机器 IP。

## 3. 地址与健康检查接口

### 查看当前真实拉流地址

```http
GET http://<vision-host>:8000/stream/source?camera_id=camera_01
```

返回示例：

```json
{
  "camera_id": "camera_01",
  "running": true,
  "dual_stream_enabled": true,
  "display_source_current": "main",
  "display_fallback_active": false,
  "main_rtsp_url_masked": "rtsp://admin:***@192.168.8.254:10554/tcp/av0_0",
  "analysis_rtsp_url_masked": "rtsp://admin:***@192.168.8.254:10554/tcp/av0_1",
  "main_stream_state": "connected",
  "analysis_stream_state": "connected",
  "main_connected": true,
  "analysis_connected": true,
  "main_frame_age_ms": 42,
  "analysis_frame_age_ms": 38,
  "main_capture_fps": 9.1,
  "analysis_capture_fps": 9.2
}
```

主系统判断规则：

- `running=true` 表示视觉服务已启动该摄像头。
- `main_stream_state / analysis_stream_state` 为 `connected` 表示对应流健康。
- `frame_age_ms <= 3000` 才能认为画面是新鲜帧。
- `capture_fps >= 8` 可认为视频帧率达到演示基线。

### 探测摄像头端口

```http
POST http://<vision-host>:8000/stream/probe
Content-Type: application/json
```

```json
{
  "host": "192.168.8.254",
  "port": 10554,
  "timeout_ms": 1500
}
```

该接口只检查 TCP 端口可达，不代表 RTSP 一定能出帧。用途是移动 WiFi 重启后快速筛选候选 IP。

### 按新 IP 切换双流

```http
POST http://<vision-host>:8000/stream/switch-host
Content-Type: application/json
```

```json
{
  "camera_id": "camera_01",
  "host": "192.168.8.250",
  "username": "admin",
  "password": "摄像头密码",
  "port": 10554,
  "main_path": "/tcp/av0_0",
  "analysis_path": "/tcp/av0_1"
}
```

成功后视觉服务会停止旧流、清理旧状态，并用新 IP 重启：

```json
{
  "camera_id": "camera_01",
  "status": "restarted",
  "message": "stream restarted with requested source urls",
  "main_rtsp_url": "rtsp://admin:***@192.168.8.250:10554/tcp/av0_0",
  "analysis_rtsp_url": "rtsp://admin:***@192.168.8.250:10554/tcp/av0_1"
}
```

切换后主系统应继续轮询 `/stream/source` 或 `/status`，直到：

```text
main_stream_state=connected
analysis_stream_state=connected
main_frame_age_ms <= 3000
analysis_frame_age_ms <= 3000
```

## 4. 主系统推荐流程

1. 主系统启动后调用 `/healthz`，确认视觉服务在线。
2. 调用 `/stream/source`，展示当前 masked RTSP 地址和流状态。
3. 如果移动 WiFi 或摄像头重启，主系统获取新的摄像头 IP。
4. 调用 `/stream/probe` 检查 `<new-ip>:10554` 是否可达。
5. 可达后调用 `/stream/switch-host` 切换双流。
6. 轮询 `/stream/source`，确认两路流恢复。
7. 业务数据读取继续使用 `/integration/results/camera_01/latest`。

## 5. 业务结果接口

主系统读取 AI 结果：

```http
GET http://<vision-host>:8000/integration/results/camera_01/latest
```

建议轮询频率：

```text
1~5 Hz
```

不要用该接口判断视频是否新鲜；视频健康以 `/stream/source` 或 `/status` 为准。

## 6. 错误处理建议

- `/healthz` 不通：视觉服务未启动或网络不可达。
- `/stream/probe` 不通：摄像头 IP 错、端口错、移动 WiFi 未连通或摄像头未启动。
- `/stream/source` 中 `connected=false`：RTSP 可达但拉流未成功，继续观察 `last_error` 可用 `/status`。
- `frame_age_ms > 3000`：连接可能仍在，但画面已 stale，主系统应展示“摄像头画面恢复中”。
- 切换后 10 秒仍未恢复：提示重新确认摄像头 IP、密码、移动 WiFi 网络。

## 7. 安全边界

- `/stream/source` 只返回 masked 地址，避免泄露摄像头密码。
- `/stream/switch-host` 需要主系统提交密码；生产环境建议加鉴权或只允许内网调用。
- 主系统不要保存明文密码到日志。
