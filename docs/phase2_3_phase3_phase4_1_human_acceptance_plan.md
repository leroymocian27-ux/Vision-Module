# Phase 2.3 + Phase 3 + Phase 4.1 真人前端验收计划

## 1. 验收范围

本轮只验收：

- Phase 2.3：Identity Binding + Tracking 联动
- Phase 3：Pose skeleton overlay
- Phase 4.1：可解释 behavior 状态机

本轮不验收：

- 真实摔倒
- GRU / LSTM
- 跌倒状态机
- 告警
- 主后端 POST

## 2. 测试身份前提

如果真人就是已注册的 `elder_001`：

- 预期应能绑定 `elder_001`
- 前端目标详情面板应显示 `person_id=elder_001`
- `identity_state` 应尽量保持 `target_locked`

如果真人不是已注册对象：

- 预期不应错误绑定为 `elder_001`
- `person_id/person_name` 应为空或保持未匹配
- 不应为了“必须有结果”而强行绑定非目标人员

## 3. 前端 /demo 应展示内容

当前 `/demo` 已补充：

- 实时视频
- 目标框
- Track ID
- `Target #id / Track #id`
- `person_id / person_name`
- `identity_state`
- skeleton 骨架
- `behavior_state`
- `stream_state`
- `detection_fps`
- `tracking_fps`
- `pose_fps`
- raw `/status` JSON

观察优先级：

- 先看视频是否流畅
- 再看绿色目标框是否跟随目标
- 再看目标详情面板
- 最后用 raw JSON 交叉确认

## 4. 启动建议

主 Vision Service：

```powershell
cd D:\vision_service
conda activate torchgpu

$env:ENABLE_TRACKING="true"
$env:ENABLE_IDENTITY_BINDING="true"
$env:IDENTITY_SERVICE_URL="http://127.0.0.1:8100"
$env:IDENTITY_REQUEST_TIMEOUT_MS="1000"
$env:ENABLE_POSE="true"
$env:POSE_PROVIDER="yolo"
$env:ENABLE_BEHAVIOR="true"

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Identity Service：

```powershell
cd D:\vision_service\identity_service
conda activate identity310
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

前端：

```text
http://127.0.0.1:8000/demo
```

## 5. 真人动作验收表

| 动作 | 预期前端表现 | 预期 status 字段 | 是否通过 |
| --- | --- | --- | --- |
| 已注册目标正脸站到摄像头前 | 视频流畅；绿色目标框出现；显示 `Target #id`；目标详情显示 `elder_001` | `stream_state=connected`，`tracking_state=target_locked`，`identity.bound_person_id=elder_001` | 人工记录 |
| 已注册目标保持正脸 5-10 秒 | `Target #id` 不频繁变化；`identity_state` 尽量保持 `target_locked` | `identity.last_match_score` 有值，`identity.last_error=null` | 人工记录 |
| 已注册目标左右缓慢走动 | 目标框跟随人体；骨架跟随身体；`Target #id` 尽量稳定 | `tracking.tracked_target_id` 稳定，`pose.last_error=null` | 人工记录 |
| 已注册目标原地停住 | 骨架不明显漂移；行为可为 `standing` 或 `unknown` | `behavior.state=standing/unknown`，`frame_age_ms<3000` | 人工记录 |
| 已注册目标短暂遮挡 1-2 秒 | 视频不断；目标可能短暂丢失；恢复后尽量回到同一目标 | `tracking_state=target_lost` 或短暂保持 `target_locked` | 人工记录 |
| 已注册目标遮挡后重新露出 | 目标框恢复；骨架恢复；身份应尽量恢复为 `elder_001` | `identity.bound_person_id=elder_001`，`tracking_state=target_locked` | 人工记录 |
| 已注册目标离开画面 3 秒以上 | 目标框消失；不应误锁定背景 | `tracking_state=target_lost/target_reacquiring` | 人工记录 |
| 已注册目标重新进入画面 | 重新出现目标框；可能出现新 `track_id`；身份应重新绑定 | `identity.bound_person_id=elder_001`，`last_match_score` 更新 | 人工记录 |
| 已注册目标坐下 | 框和骨架随身体高度下降；行为方向可为 `sitting` | `behavior.state=sitting/unknown` | 人工记录 |
| 已注册目标弯腰 | 上半身骨架前倾；行为方向可为 `bending` | `behavior.state=bending/unknown` | 人工记录 |
| 已注册目标侧身 | 骨架允许部分缺点；不应导致视频/检测崩溃 | `pose.last_error=null` 或短暂为空，`stream_state=connected` | 人工记录 |
| 已注册目标安全低姿态/躺下模拟 | 不做真实摔倒；可慢慢躺到床/沙发；行为方向可为 `lying` | `behavior.state=lying/unknown`，不产生告警 | 人工记录 |

## 6. 非目标人物测试

| 动作 | 预期前端表现 | 预期 status 字段 | 是否通过 |
| --- | --- | --- | --- |
| 未注册人员单独入画 | 可出现 Track 框和骨架；不应显示 `elder_001` | `identity.bound_person_id` 不应变成 `elder_001` | 人工记录 |
| 未注册人员正脸停留 10 秒 | 不应为了匹配而错误绑定；允许 `person_id` 为空 | `identity.last_match_score` 低于阈值或未匹配 | 人工记录 |
| 未注册人员与目标人员同时入画 | 目标人员应优先保持绿色目标框；非目标为灰色或非目标状态 | `tracked_target_id` 不应因新人出现频繁切换 | 人工记录 |
| 未注册人员遮挡目标 1-2 秒 | 允许短暂 `target_lost`；不应把遮挡者绑定成 `elder_001` | `identity.bound_person_id` 不应错误切到非目标 track | 人工记录 |

## 7. Behavior 验收口径

Phase 4.1 是可解释规则层，不是最终跌倒判断。

行为状态预期方向：

- 站立：`standing`
- 走动：`walking`
- 坐下：`sitting`
- 弯腰：`bending`
- 低姿态/躺下模拟：`lying`
- 遮挡、侧身、关键点不足：允许 `unknown`

验收时不要把 behavior 不准确直接判失败。

判失败的情况：

- behavior 频繁荒谬跳变，例如静止站立时在 `lying/walking/bending` 间快速闪烁
- behavior 异常导致 WebRTC、YOLO、Tracking、Pose 中断
- behavior 输出导致错误告警。本阶段不应有告警

## 8. 通过标准

可以认为本轮真人前端验收通过的最低标准：

- 实时视频持续播放
- `frame_age_ms` 健康，不持续超过 3000ms
- 目标框能跟随真人
- `Target #id` 在短时间内相对稳定
- 已注册真人能绑定 `elder_001`
- 未注册人员不应错误绑定为 `elder_001`
- skeleton 大体贴合人体
- behavior 输出方向基本合理，或在不确定时输出 `unknown`
- `detection_fps / tracking_fps / pose_fps` 可在右侧面板观察
- 不出现 GRU、跌倒判断、告警相关输出

## 9. 辅助 WebSocket 抓取脚本

如果前端表现与预期不一致，可用脚本抓取 WebSocket payload：

```powershell
@'
import asyncio
import json
import websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8000/ws/results?camera_id=camera_01") as ws:
        for _ in range(10):
            data = json.loads(await ws.recv())
            rows = []
            for obj in data.get("objects", []):
                rows.append({
                    "track_id": obj.get("track_id"),
                    "is_target": obj.get("is_target"),
                    "person_id": obj.get("person_id"),
                    "person_name": obj.get("person_name"),
                    "identity_state": obj.get("identity_state"),
                    "pose": bool(obj.get("pose")),
                    "behavior": obj.get("behavior", {}).get("behavior_state") if obj.get("behavior") else None,
                })
            print(json.dumps({"frame_seq": data.get("frame_seq"), "objects": rows}, ensure_ascii=False))

asyncio.run(main())
'@ | C:\Users\13010\anaconda3\envs\torchgpu\python.exe -
```

## 10. 记录风险

- Phase 2.3 真实 RTSP 真人验收仍需补齐。
- Phase 3 真实 RTSP + 真人 Pose 稳定性仍需观察。
- Phase 4.1 behavior 是规则层，只能作为解释性行为理解，不代表跌倒结论。
- 真实多人遮挡时可能出现 track_id 切换，需结合后续验收记录判断。
- 本轮不允许真人真实摔倒测试。
