# Realtime Demo Final Closure - 2026-06-22

阶段：明天实时视频检测演示收口。

约束执行情况：

- 未修改 `.env`。
- 未关闭 `MAIN_SYSTEM_REPORT_DRY_RUN`。
- 未调用真实 POST。
- 未点击前端手动模拟告警按钮。
- 未启用 pose 跌倒能力。
- 未修改 `FallStateMachine`、`ResultPublisherService`、主系统 bridge。
- 未训练模型。
- 未接入新的多模态模型。
- 未执行 `git add .` 或 `git commit -am`。

## 最终判断

```text
overall_status:
PARTIAL_BUT_DEMO_READY_WITH_FALLBACK

recommended_demo_mode:
本地 replay 主演示 + RTSP 摄像头在线能力展示
```

解释：

- RTSP 摄像头在线能力已验证。
- WebRTC / WebSocket 前端连接已验证。
- dry-run 安全状态已验证。
- 本地 replay 已通过 reporter 证明产生 `fallen_confirmed / critical / dry_run_skipped`。
- 当前 RTSP 画面无人，单人全身入镜下的 bbox / track_id / risk panel 更新未由本轮自动验证，需要明天现场人工确认。

## 开场安全检查

接口：

```text
GET http://127.0.0.1:8000/status?camera_id=camera_01
GET http://127.0.0.1:8000/alerting/status
```

结果：

| 项 | 结果 |
|---|---|
| service_status | running |
| camera connected | true |
| stream_state | connected |
| capture_fps | 约 14.9 到 15.0 |
| frame_age_ms | 正常，恢复后约 0ms |
| detection.loaded | true |
| detection model | `yolov8n.pt` |
| pose_enabled | false |
| pose_provider | `disabled_placeholder` |
| temporal.enabled | false |
| dry_run | true |
| simulation.running | false |
| reporter last_post_status | `dry_run_skipped` |

保存证据：

```text
artifacts/realtime_demo_closure_20260622/status_before_replay.json
artifacts/realtime_demo_closure_20260622/alerting_status_before_replay.json
artifacts/realtime_demo_closure_20260622/status_after_restore_sanitized.json
artifacts/realtime_demo_closure_20260622/alerting_status_after_restore.json
```

说明：JSON 产物已做 RTSP 密码脱敏。

## 前端实时页面检查

页面：

```text
http://127.0.0.1:8000/demo/
```

验证结果：

| 项 | 结果 |
|---|---|
| demo 页面 HTTP | 200 |
| WebRTC | connected |
| WebSocket | connected |
| ICE connection | connected |
| video stream | `video:live` |
| video size | `640x360` |
| video ready state | `4` |
| WS FPS | 约 `9.1` |
| Video FPS | 约 `30.0` |
| Detect FPS | 约 `3.2` |
| Track FPS | 约 `10.6` |
| Pose FPS | `0.0` |
| Reporter | `dry_run_skipped` |

未完成项：

- 当前画面无人，`personCount=0`。
- 因无人，bbox、track_id、risk panel 的“单人全身入镜更新”未由本轮自动验证。
- 明天现场需要安排单人全身入镜，确认 `personCount > 0`、bbox、track id 和 risk panel 更新。

截图/帧证据：

```text
artifacts/realtime_demo_closure_20260622/rtsp_latest_frame_before_replay.jpg
artifacts/realtime_demo_closure_20260622/rtsp_latest_frame_after_restore.jpg
```

备注：

- 浏览器截图的视频层在截图中可能黑屏，因此最终以 `/stream/latest-frame.jpg` 保存的后端 FrameBuffer 图片作为画面证据。
- 页面配置区包含 RTSP 输入，未保留含明文密码截图。

## 本地 replay 验证

使用视频：

```text
D:\Program\vision_service\logs\acceptance\cropped_recording_2026-06-20T07-32-20-181Z\run2\cropped_recording_run2.mp4
```

执行方式：

```text
POST /stream/start
camera_id=camera_01
rtsp_url=<local replay mp4 path>
```

轮询观察：

| 时间 | frame_seq | track_id | fall_state | risk_level | fall_score | reporter |
|---|---:|---:|---|---|---:|---|
| 2026-06-22T23:19:27+08:00 | 7 | 1 | fallen_candidate | medium | 0.2554 | dry_run_skipped |
| 2026-06-22T23:20:24+08:00 | 122 | 5 | fallen_candidate | high | 0.5461 | dry_run_skipped |
| 2026-06-22T23:20:25+08:00 | 124 | 5 | fallen_candidate | medium | 0.2566 | dry_run_skipped |
| 2026-06-22T23:20:39+08:00 | 150 | 7 | fallen_candidate | medium | 0.4396 | dry_run_skipped |

Reporter 最终证明：

```json
{
  "source": "fall_event_reporter.last_payload",
  "status": "fallen_confirmed",
  "state": "confirmed_fall",
  "event_type": "fall_confirmed",
  "risk_level": "critical",
  "fall_score": 0.509,
  "track_id": "1",
  "reporter_last_post_status": "dry_run_skipped",
  "reporter_last_error": null,
  "pose_enabled": false,
  "pose_provider": "disabled_placeholder",
  "temporal_enabled": false
}
```

证据文件：

```text
artifacts/realtime_demo_closure_20260622/replay_observations.json
artifacts/realtime_demo_closure_20260622/replay_confirm_observations.json
artifacts/realtime_demo_closure_20260622/replay_confirmed_reporter_proof.json
artifacts/realtime_demo_closure_20260622/replay_best_result.json
```

结论：

- 本地 replay 至少稳定产生 `fallen_candidate/high`。
- reporter 记录证明本次 replay 链路最终生成过 `fallen_confirmed / confirmed_fall / critical`。
- 事件为 dry-run，`last_post_status=dry_run_skipped`，无真实 POST。

## 恢复 RTSP 状态

replay 验证结束后已切回默认 RTSP 源。

恢复后状态：

| 项 | 结果 |
|---|---|
| stream restart | success |
| connected | true |
| stream_state | connected |
| frame_width / frame_height | 640 / 360 |
| capture_fps | 约 15.02 |
| reconnect_count | 0 |
| read_timeout_count | 0 |
| dry_run | true |
| WebRTC clients | 1 |
| WS clients | 1 |

保存证据：

```text
artifacts/realtime_demo_closure_20260622/status_after_restore_sanitized.json
artifacts/realtime_demo_closure_20260622/latest_after_restore_sanitized.json
artifacts/realtime_demo_closure_20260622/rtsp_latest_frame_after_restore.jpg
```

## 明天演示口径

建议主线：

```text
实时摄像头展示在线能力：
RTSP 接入、解码取帧、WebRTC 画面、YOLO 检测、ByteTrack 跟踪、WebSocket/Polling 结果、dry-run 安全状态。

本地 replay 展示跌倒确认能力：
fallen_confirmed / critical / dry_run_skipped。
```

必须说明：

- 当前不会向主系统真实发送告警。
- 明天使用 no-pose 安全基线，pose 不作为跌倒判断依据。
- 0-5 VisualRiskMarker 仍主要是离线/半接入能力，不作为实时主功能展示。
- runtime 当前展示的是 `low/medium/high/critical` 风险字段。
- 实时摄像头触发跌倒受动作、角度、遮挡、距离、安全因素影响，不承诺现场每次都触发 `fallen_confirmed`。

## 明天现场必做

```text
1. 开场先展示 /alerting/status 的 dry_run=true。
2. 展示 /status 的 connected=true、stream_state=connected。
3. 打开 /demo/，确认 WebRTC connected、WS connected。
4. 安排单人全身入镜，确认 personCount > 0、bbox、track_id。
5. 若实时跌倒不稳定，立即切本地 replay。
6. 展示 replay 的 fallen_confirmed / critical / dry_run_skipped。
7. 最后切回 RTSP 摄像头，证明实时源恢复。
```

## 风险说明

| 风险 | 当前处理 |
|---|---|
| 当前 RTSP 画面无人 | 明天现场需要人工全身入镜验证 |
| WebRTC 截图黑屏 | 使用 `/stream/latest-frame.jpg` 作为画面证据 |
| replay 轮询先看到 candidate | reporter 最终记录已证明 confirmed |
| 真实 POST 风险 | dry_run=true，simulation 未运行 |
| RTSP 密码泄露 | 产物和文档已脱敏扫描 |
| 0-5 VisualRiskMarker 未实时接入 | 明天只作为离线能力说明 |

## 产物位置

```text
artifacts/realtime_demo_closure_20260622/
```

该目录包含接口快照、replay 观察结果、dry-run 证明、RTSP 恢复后的帧图。

## Git 状态说明

未执行 stage / commit。当前新增的收口文档：

```text
docs/realtime_demo_final_closure_20260622.md
```

已有未跟踪项仍保持未提交状态。

