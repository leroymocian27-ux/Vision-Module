# Vision Service 推送主系统跌倒告警接口文件

更新时间：2026-07-07

本文档定义 Vision Service 最终会推送给主系统的跌倒告警接口。主系统只需要按本文档提供接收接口，即可接收跌倒告警并触发前端弹窗。

## 1. 最终推送接口

```http
POST http://192.168.8.248:8000/api/v1/video-bridge/fall-events
Content-Type: application/json
X-Vision-Service-Token: <可选 token>
```

当前配置含义：

| 项 | 值 |
|---|---|
| 摄像头 IP | `192.168.8.250` |
| Vision Service | `http://192.168.8.249:8000` |
| 主系统 API | `http://192.168.8.248:8000/api/v1` |
| 主系统接收路径 | `/video-bridge/fall-events` |
| 最终完整推送地址 | `http://192.168.8.248:8000/api/v1/video-bridge/fall-events` |
| 推送实现文件 | `app/services/fall_event_reporter_service.py` |
| 构造 payload 方法 | `FallEventReporterService._build_payload()` |
| 实际 POST 方法 | `FallEventReporterService._post_payload()` |

## 2. 主系统响应要求

Vision Service 判断推送成功的规则很简单：

```text
HTTP 状态码 < 400 即认为主系统接收成功
HTTP 状态码 >= 400 认为推送失败
网络异常/超时认为推送失败
```

推荐主系统成功响应：

```json
{
  "ok": true,
  "received": true,
  "incident_id": "vision-fall-camera_01_track_20-20260707093015532100",
  "alarm_id": "main-alarm-20260707093015532100",
  "message": "fall event received"
}
```

## 3. 最终推送 JSON 示例

下面是 Vision Service 确认跌倒后最终会向主系统 POST 的 JSON 格式。

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
  "fall_prob": 0.93,
  "fall_score": 0.93,
  "track_id": "20",
  "incident_id": "vision-fall-camera_01_track_20-20260707093015532100",
  "bbox": [118.4, 176.2, 372.8, 348.5],
  "snapshot_url": "http://192.168.8.249:8000/fall-events/snapshots/camera_01_20_20260707093015532100.jpg",
  "snapshot_path": "D:/Program/vision_service/data/fall_events/camera_01_20_20260707093015532100.jpg",
  "timestamp": "2026-07-07T09:30:15.532100+08:00",
  "scores": {
    "temporal": 0.93,
    "shadow_onnx_lstm": 0.88
  },
  "injury": {
    "level": "I3",
    "reason": "vision_service_fallen_confirmed",
    "advice": "Please inspect the live camera view immediately and confirm the elder's condition."
  },
  "metadata": {
    "event": {
      "incident_id": "vision-fall-camera_01_track_20-20260707093015532100",
      "camera_id": "camera_01",
      "stream_name": "primary",
      "event_type": "fall_confirmed",
      "state": "confirmed_fall",
      "status": "fallen_confirmed",
      "severity": "L3",
      "risk": "critical",
      "risk_level": "critical",
      "fall_score": 0.93,
      "fall_prob": 0.93,
      "track_id": "20",
      "snapshot_url": "http://192.168.8.249:8000/fall-events/snapshots/camera_01_20_20260707093015532100.jpg",
      "snapshot_path": "D:/Program/vision_service/data/fall_events/camera_01_20_20260707093015532100.jpg",
      "injury": {
        "level": "I3",
        "reason": "vision_service_fallen_confirmed",
        "advice": "Please inspect the live camera view immediately and confirm the elder's condition."
      },
      "multimodal_review": {
        "provider": "onnx_lstm",
        "temporal_source": "pose_temporal_fusion",
        "scores": {
          "temporal": 0.93,
          "shadow_onnx_lstm": 0.88
        }
      },
      "incident_reuse_debug": {
        "incident_reuse_checked": true,
        "incident_reused": false,
        "incident_reuse_reason": null,
        "active_incident_id": null,
        "previous_incident_id": null,
        "previous_track_id": null,
        "current_track_id": "20",
        "track_handoff_detected": false,
        "incident_reuse_age_ms": null,
        "incident_reuse_window_ms": 15000.0,
        "incident_spatial_distance": null,
        "incident_iou": 0.0,
        "single_person_scene": true,
        "duplicate_incident_suppressed": false
      }
    },
    "provider": "onnx_lstm",
    "model_source": "pose_temporal_fusion",
    "feature_schema_hash": null,
    "frame_seq": 18342,
    "frame_width": 640,
    "frame_height": 360,
    "object_confidence": 0.95,
    "incident_identity_key": "camera_01:track:20",
    "incident_spatial_key": "camera_01:fall:3:4:1:1",
    "person_id": null,
    "person_name": null,
    "fall_decision": {
      "fall_state": "fallen_confirmed",
      "risk_level": "critical",
      "fall_probability": 0.93,
      "confirm_source": "field_low_posture_recent_fall_hint"
    },
    "alarm_preview": {
      "confirmed": true,
      "risk_level": "critical",
      "fall_probability": 0.93
    },
    "temporal": {
      "source": "onnx_lstm",
      "fall_probability": 0.93
    },
    "incident_reuse_debug": {
      "incident_reuse_checked": true,
      "incident_reused": false,
      "duplicate_incident_suppressed": false
    }
  }
}
```

## 4. 主系统必须使用的关键字段

主系统弹窗只需要关注这些字段：

| 字段 | 类型 | 是否必须 | 用途 |
|---|---:|---:|---|
| `event_type` | string | 是 | 固定为 `fall_confirmed` 时表示确认跌倒事件 |
| `status` | string | 是 | `fallen_confirmed` 表示系统已确认跌倒 |
| `fall_detected` | boolean | 是 | `true` 表示确认跌倒 |
| `risk_level` | string | 是 | `critical` / `high` 建议触发强告警 |
| `incident_id` | string | 是 | 告警唯一 ID，用于弹窗去重 |
| `camera_id` | string | 是 | 摄像头 ID |
| `track_id` | string | 建议 | 人体跟踪 ID，便于排查 |
| `fall_prob` | number | 建议 | 跌倒概率，0 到 1 |
| `bbox` | number[] | 建议 | 人体框 `[x1, y1, x2, y2]` |
| `snapshot_url` | string/null | 建议 | 跌倒截图，前端弹窗可展示 |
| `timestamp` | string | 是 | 事件时间 |

## 5. 主系统弹窗触发规则

推荐主系统按以下逻辑触发跌倒弹窗：

```text
event_type == "fall_confirmed"
AND status in ["fallen_confirmed", "confirmed_fall"]
AND fall_detected == true
AND risk_level in ["high", "critical"]
AND incident_id 未弹过
```

`incident_id` 是最重要的去重字段。同一个 `incident_id` 只弹一次窗。

## 6. 最小可用接收模型

如果主系统暂时不想接收完整 metadata，至少应兼容下面的最小字段：

```json
{
  "camera_id": "camera_01",
  "source": "vision_service",
  "event_type": "fall_confirmed",
  "status": "fallen_confirmed",
  "risk_level": "critical",
  "fall_detected": true,
  "fall_prob": 0.93,
  "track_id": "20",
  "incident_id": "vision-fall-camera_01_track_20-20260707093015532100",
  "bbox": [118.4, 176.2, 372.8, 348.5],
  "snapshot_url": "http://192.168.8.249:8000/fall-events/snapshots/camera_01_20_20260707093015532100.jpg",
  "timestamp": "2026-07-07T09:30:15.532100+08:00"
}
```

## 7. FastAPI 接收示例

主系统可以按下面方式接收：

```python
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/video-bridge", tags=["video-bridge"])


class FallEventPayload(BaseModel):
    camera_id: str
    source: str = "vision_service"
    event_type: str
    status: str
    risk_level: str
    fall_detected: bool
    fall_prob: float = Field(ge=0.0, le=1.0)
    track_id: str | None = None
    incident_id: str
    bbox: list[float] | None = None
    snapshot_url: str | None = None
    timestamp: str
    metadata: dict = Field(default_factory=dict)


@router.post("/fall-events")
async def receive_fall_event(
    payload: FallEventPayload,
    x_vision_service_token: str | None = Header(default=None, alias="X-Vision-Service-Token"),
):
    if payload.event_type != "fall_confirmed":
        raise HTTPException(status_code=400, detail="UNSUPPORTED_EVENT_TYPE")

    should_popup = (
        payload.fall_detected
        and payload.status in {"fallen_confirmed", "confirmed_fall"}
        and payload.risk_level in {"high", "critical"}
    )

    # 主系统应使用 payload.incident_id 做去重。
    # 若 should_popup 为 true，则创建/广播跌倒告警弹窗。
    return {
        "ok": True,
        "received": True,
        "should_popup": should_popup,
        "incident_id": payload.incident_id,
    }
```

## 8. 注意事项

1. `snapshot_url` 是给主系统前端展示的地址；`snapshot_path` 是 Vision Service 本机路径，不建议展示给用户。
2. 主系统不要用 `track_id` 做弹窗去重，因为跟踪 ID 可能切换；应使用 `incident_id`。
3. Vision Service 内部有冷却和事件复用逻辑，同一跌倒过程会尽量复用同一个 `incident_id`。
4. 主系统返回 2xx 即可，Vision Service 不强依赖响应体结构。
5. 如果需要鉴权，请校验 `X-Vision-Service-Token`，不要把 token 写进日志。
