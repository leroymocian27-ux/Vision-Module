# Vision Service 接口需求文档

生成时间：2026-06-15 18:50 Asia/Shanghai

## 1. 当前启动状态

### 1.1 主服务 Vision Service

- 地址：`http://127.0.0.1:8000`
- 健康检查：`GET /healthz` 返回 `{"status":"ok"}`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 启动命令（当前已在运行）：

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- 当前运行态要点：
  - 服务状态为 `running`
  - 默认摄像头 `camera_01` 已创建，但当前流状态为 `connecting`
  - 当前检测模型已加载：`yolov8n.pt`
  - 主服务内置身份注册能力当前为关闭状态：`identity_enabled=false`

### 1.2 独立身份服务 Identity Service

- 地址：`http://127.0.0.1:8100`
- 健康检查：`GET /healthz` 返回 `status=ok`
- OpenAPI：`http://127.0.0.1:8100/docs`
- 当前已启动
- 当前运行限制：
  - `recognizer_loaded=false`
  - `last_error=No module named 'insightface'`
  - 说明：服务可访问，但真正的人脸注册与匹配能力还需要安装 `insightface` / `onnxruntime-gpu`

## 2. 接口总体要求

- 主服务入站接口默认不做鉴权，当前更适合内网或受控环境使用。
- 允许跨域：`CORS allow_origins=["*"]`。
- 数据格式分为 4 类：
  - `application/json`
  - `multipart/form-data`
  - `image/jpeg`
  - `WebSocket JSON 推送`
- 常见状态码约定：
  - `200`：成功
  - `400`：参数或业务条件不满足
  - `404`：资源不存在或结果未就绪
  - `409`：资源冲突
  - `422`：请求体校验失败
  - `503`：依赖能力不可用

## 3. 主服务接口需求

### 3.1 状态与监控

| 接口 | 说明 | 请求要求 | 响应要求 |
| --- | --- | --- | --- |
| `GET /healthz` | 服务存活检查 | 无 | 返回 `{"status":"ok"}` |
| `GET /status` | 获取完整运行状态 | 可选查询参数 `camera_id` | 返回总状态对象，至少包含 `cameras`、`detection`、`tracking`、`identity`、`pose`、`behavior`、`temporal`、`pipeline`、`latest_result`、`fall_event_reporter` |

`GET /status` 的核心用途：

- 前端启动时拉取全量状态
- 运维判断摄像头是否掉流
- 判断模型是否加载成功
- 判断告警推送器是否启用

重点字段要求：

- `cameras[].stream_state`：应返回 `disconnected / connecting / connected / stale / reconnecting`
- `cameras[].frame_age_ms`：用于判断画面是否新鲜
- `detection[].loaded`：用于判断检测模型是否可用
- `identity.identity_enabled`：用于判断主服务内置身份注册是否开放
- `diagnostics.capture_stale`：用于标记采集链路卡死风险

### 3.2 视频流控制

| 接口 | 说明 | 请求要求 | 响应要求 |
| --- | --- | --- | --- |
| `POST /stream/start` | 启动或重启摄像头流 | JSON，字段：`camera_id`、`rtsp_url`、可选 `main_rtsp_url`、`analysis_rtsp_url` | 返回 `camera_id`、`status`、`message`、`main_rtsp_url`、`analysis_rtsp_url` |
| `GET /stream/source` | 查询当前视频源运行态 | 可选 `camera_id` | 返回视频源掩码地址、连接状态、帧龄、采集 FPS |
| `GET /stream/latest-frame.jpg` | 获取最新一帧 JPG | 可选 `camera_id` | 成功返回 `image/jpeg`，并附带 `X-Camera-Id`、`X-Frame-Seq`、`X-Frame-Age-Ms` |
| `POST /stream/switch-host` | 根据摄像头主机参数切换 RTSP 地址 | JSON，字段：`camera_id`、`host`、`username`、`password`、`port`、`main_path`、`analysis_path`、`scheme` | 返回切换后的掩码地址和重启结果 |
| `POST /stream/probe` | 探测主机端口可达性 | JSON，字段：`host`、`port`、`timeout_ms` | 返回 `reachable`、`elapsed_ms`、可选 `error` |
| `POST /stream/stop` | 停止视频流 | JSON，字段：`camera_id` | 返回 `stopped` 或 `not_found` |

视频流业务规则：

- `rtsp_url` 支持 RTSP 地址、本地文件路径、`mock://colorbars`
- 当流已存在时，`/stream/start` 可能返回：
  - `status=running`
  - `status=restarted`
  - `status=started`
- `GET /stream/latest-frame.jpg` 在尚无帧时返回 `404`，错误码为 `LATEST_FRAME_NOT_AVAILABLE`
- 当 JPG 编码失败时返回 `500`，错误码为 `LATEST_FRAME_ENCODE_FAILED`

建议联调顺序：

1. `POST /stream/probe`
2. `POST /stream/start`
3. `GET /stream/source`
4. `GET /stream/latest-frame.jpg`
5. `GET /status`

### 3.3 WebRTC 与实时结果输出

| 接口 | 说明 | 请求要求 | 响应要求 |
| --- | --- | --- | --- |
| `POST /webrtc/offer` | 提交 WebRTC offer，获取 answer | JSON，字段：`camera_id`、`sdp`、`type` | 返回 `peer_id`、`sdp`、`type=answer` |
| `POST /webrtc/candidate` | 追加 ICE candidate | JSON，字段：`peer_id`、`candidate` | 返回 `{ok: true, message: "candidate added"}` |
| `WS /ws/results` | 订阅实时识别结果 | 可选查询参数 `camera_id` | 服务端持续推送 `vision_result` JSON |
| `GET /integration/results/{camera_id}/latest` | 拉取某摄像头最新分析结果 | 路径参数 `camera_id` | 返回最近一次发布结果；未就绪时返回 `404` 与 `VISION_RESULT_NOT_READY` |
| `GET /fall-events/snapshots/{filename}` | 下载跌倒事件截图 | 路径参数 `filename` | 成功返回 JPG；非法路径或类型返回 `400` |

WebRTC 约束：

- 对应摄像头必须已启动，否则接口返回 `404`
- 若 `aiortc` / `av` 依赖缺失，接口也会返回不可用信息

`WS /ws/results` 推送消息要求：

```json
{
  "type": "vision_result",
  "camera_id": "camera_01",
  "timestamp": "2026-06-15T10:00:00+00:00",
  "frame_seq": 123,
  "frame_width": 1280,
  "frame_height": 720,
  "objects": [
    {
      "label": "person",
      "confidence": 0.92,
      "bbox": [10, 20, 100, 220],
      "track_id": 3,
      "is_target": true,
      "person_id": null,
      "person_name": null,
      "identity_state": null,
      "pose": null,
      "behavior": null,
      "temporal": null,
      "fall_decision": null,
      "alarm_preview": null
    }
  ],
  "detector": {}
}
```

`GET /integration/results/{camera_id}/latest` 在上述结构基础上，还会额外补充：

- `source_fps`
- `analysis_fps`

截图接口约束：

- 仅允许访问 `logs/fall_events/snapshots` 下的文件
- 仅允许 `.jpg` / `.jpeg`
- 错误码包括：
  - `INVALID_SNAPSHOT_PATH`
  - `SNAPSHOT_NOT_FOUND`
  - `UNSUPPORTED_SNAPSHOT_TYPE`

### 3.4 告警联动

| 接口 | 说明 | 请求要求 | 响应要求 |
| --- | --- | --- | --- |
| `GET /alerting/status` | 查看当前告警推送目标与模拟器状态 | 无 | 返回 `endpoint` 和 `simulation` |
| `POST /alerting/endpoint` | 更新告警推送目标 | JSON，字段：`base_url`、`path`、`enabled` | 返回更新后的完整状态 |
| `POST /alerting/simulation/start` | 开启持续模拟跌倒告警 | JSON，需提供 `target_ip` 或 `base_url` 之一；可带 `path`、`interval_seconds`、`camera_id`、`track_id`、`fall_prob` | 返回模拟发送状态 |
| `POST /alerting/simulation/send-once` | 单次发送模拟跌倒告警 | JSON，字段：`target_ip`、`camera_id`、`track_id`、`fall_prob` | 返回目标 URL、状态码、返回体、发送时间、事件号 |
| `POST /alerting/simulation/stop` | 停止持续模拟 | 无 | 返回停止后的模拟状态 |

告警联动要求：

- 若未传 `base_url`，系统会按 `target_ip + 默认端口 + /api/v1` 自动拼接
- 单次模拟返回字段至少包括：
  - `ok`
  - `target_url`
  - `status_code`
  - `response_body`
  - `error`
  - `sent_at`
  - `incident_id`

### 3.5 主服务内置身份管理

| 接口 | 说明 | 请求要求 | 响应要求 |
| --- | --- | --- | --- |
| `POST /identity/enroll` | 在主服务内注册人脸身份 | `multipart/form-data`，字段：`person_id`、`person_name`、`replace_existing`、`files[]` | 返回 `person_id`、`person_name`、`faces_registered`、`status` |
| `GET /identity/list` | 查询已注册身份列表 | 无 | 返回身份数组 |
| `DELETE /identity/{person_id}` | 删除指定身份 | 路径参数 `person_id` | 返回 `{person_id, status:"deleted"}` |

身份注册规则：

- 上传图片数量必须在 `1..IDENTITY_MAX_IMAGES` 范围内
- 上传文件 `content_type` 必须为 `image/*`
- 主服务内置身份模块关闭时，`/identity/enroll` 返回 `503`
- 已存在同名身份且未允许覆盖时，返回 `409`
- 无人脸或图像非法时，返回 `400`
- 人脸识别依赖不可用时，返回 `503`

当前主服务运行态说明：

- `GET /status` 显示 `identity_enabled=false`
- 因此主服务上的 `/identity/enroll` 当前不建议作为正式入口
- 如果要做独立的人脸注册/匹配，建议优先使用 8100 端口的身份服务

## 4. 独立身份服务接口需求

### 4.1 服务定位

独立身份服务只负责：

- 人脸注册
- 向量提取
- 本地身份库维护
- 单图人脸匹配

它不负责：

- RTSP 拉流
- YOLO 检测
- WebRTC
- 跌倒告警

### 4.2 接口清单

| 接口 | 说明 | 请求要求 | 响应要求 |
| --- | --- | --- | --- |
| `GET /healthz` | 查看服务与识别器状态 | 无 | 返回 `status`、`recognizer_loaded`、`recognizer_name`、`model_name`、`registered_count`、`last_error` |
| `POST /identity/enroll` | 注册身份 | `multipart/form-data`，字段：`person_id`、`person_name`、`replace_existing`、`files[]` | 返回 `person_id`、`person_name`、`faces_registered`、`embedding_count`、`model_name`、`status` |
| `POST /identity/match` | 上传单图做人脸匹配 | `multipart/form-data`，字段：`file`、可选 `threshold` | 返回 `matched`、`person_id`、`person_name`、`score`、`threshold`、`model_name` |
| `GET /identity/list` | 查询身份库 | 无 | 返回身份数组 |
| `DELETE /identity/{person_id}` | 删除身份 | 路径参数 `person_id` | 返回 `{person_id, status:"deleted"}` |

独立身份服务业务规则：

- 注册图片数量必须在 `1..IDENTITY_MAX_IMAGES` 范围内
- `file/files` 必须是图片类型
- `POST /identity/match` 找不到可匹配身份时返回 `404`
- 无法加载识别器时，注册和匹配返回 `503`

当前可用性说明：

- 服务已成功监听 `127.0.0.1:8100`
- 但 `insightface` 尚未安装，因此注册和匹配暂不可用
- 当前更适合先做接口联调、健康检查和列表/删除接口联调

## 5. 联调建议

### 5.1 主服务最小联调链路

1. `GET /healthz`
2. `GET /status`
3. `POST /stream/start`，优先使用 `mock://colorbars` 验证链路
4. `GET /stream/latest-frame.jpg`
5. `WS /ws/results`
6. `GET /integration/results/{camera_id}/latest`

### 5.2 告警联动链路

1. `GET /alerting/status`
2. `POST /alerting/endpoint`
3. `POST /alerting/simulation/send-once`
4. 如需压测或连续验证，再调用 `POST /alerting/simulation/start`

### 5.3 身份链路

1. 如使用主服务内置身份注册，先开启 `ENABLE_IDENTITY=true`
2. 如使用独立身份服务，先补装 `insightface` 与 `onnxruntime-gpu`
3. 再调用注册和匹配接口

## 6. 当前结论

- Vision Service 主服务已经处于运行状态，可直接访问 `8000` 端口进行接口联调
- 独立 Identity Service 也已启动，可直接访问 `8100` 端口进行健康检查和接口联调
- 当前最大功能限制不是接口本身，而是：
  - 主服务当前摄像头流尚未连上
  - 独立身份服务当前缺少 `insightface` 依赖
