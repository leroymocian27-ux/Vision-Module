# Vision Service 接口功能文档

更新时间：2026-06-19

适用版本：

- 仓库：`D:\Program\vision_service`
- 提交：`66b5b82`

## 1. 文档目标

本文档不强调“接口长什么样”，而强调“接口是干什么的”。

它帮助以下角色快速理解系统：

- 新接手工程师
- 主系统对接工程师
- 测试与实施同事

## 2. 系统功能总览

`vision_service` 当前承担的职责：

1. 摄像头 RTSP 拉流
2. 行人检测
3. 跌倒检测
4. 跟踪与目标锁定
5. 姿态估计
6. 行为/时序分析
7. 跌倒确认
8. 结果发布
9. 快照落盘
10. 告警推送到主系统

整体链路：

```text
摄像头 RTSP
-> 采集
-> person detector
-> fall detector
-> tracking
-> pose
-> temporal / field rule / result fusion
-> latest_result
-> snapshot
-> main system alert
```

## 3. 按接口分组说明功能

## 3.1 健康与状态接口

对应接口：

- `GET /healthz`
- `GET /status`

功能职责：

- 判断服务进程是否活着
- 判断摄像头是否正常连通
- 判断检测、跟踪、姿态、时序链路是否工作
- 判断当前有没有确认跌倒、有没有 `incident_id`

典型使用场景：

- 启动后自检
- 线上巡检
- 验收前确认 `stream_state / capture_fps / frame_age_ms`
- 复盘误报或漏报

## 3.2 视频流控制接口

对应接口：

- `POST /stream/start`
- `GET /stream/source`
- `GET /stream/latest-frame.jpg`
- `POST /stream/switch-host`
- `POST /stream/probe`
- `POST /stream/stop`

功能职责：

- 负责摄像头源的启动、停止、切换和快速探测
- 提供实时原始帧供人工排查

典型使用场景：

- 现场摄像头地址变更
- 热点切换导致 IP 变化
- 摄像头无法出图时先测端口是否通
- 保存 `latest-frame.jpg` 做误报/漏报证据

## 3.3 WebRTC 与 WebSocket 接口

对应接口：

- `POST /webrtc/offer`
- `POST /webrtc/candidate`
- `WS /ws/results`
- `GET /demo`

功能职责：

- 为浏览器和 Demo 页面提供实时画面/实时结果
- 让前端能够订阅对象列表、状态和调试字段

典型使用场景：

- Overlay 调试
- 现场展示
- Demo 演示
- 结果实时联调

## 3.4 身份识别接口

对应接口：

- `POST /identity/enroll`
- `GET /identity/list`
- `DELETE /identity/{person_id}`

功能职责：

- 管理人员身份库
- 为后续目标绑定、人名显示、身份联动提供基础能力

当前说明：

- 身份功能是辅功能
- 跌倒告警主链路不依赖身份识别才能工作

## 3.5 集成结果接口

对应接口：

- `GET /integration/connection-status`
- `GET /integration/results/{camera_id}/latest`
- `GET /integration/fall-alerts/{camera_id}/poll`

功能职责：

- 为主系统或第三方系统输出“可消费结果”
- 屏蔽内部复杂调试细节，把结果整理成外部更容易消费的标准结构

推荐理解方式：

### `GET /integration/connection-status`

作用：

- 看“我自己在线吗”
- 看“主系统接收端在线吗”

### `GET /integration/results/{camera_id}/latest`

作用：

- 看当前这一路摄像头最新的结果是什么
- 是否已经确认跌倒
- 是否有 `incident_id`
- 是否有快照

### `GET /integration/fall-alerts/{camera_id}/poll`

作用：

- 专门面向“弹窗/轮询通知”
- 适合前端或轻量轮询客户端

## 3.6 告警控制接口

对应接口：

- `GET /alerting/status`
- `POST /alerting/endpoint`
- `POST /alerting/simulation/start`
- `POST /alerting/simulation/send-once`
- `POST /alerting/simulation/stop`

功能职责：

- 管理 `vision_service` 向主系统推送告警的目标地址
- 支持联调时快速发模拟事件

典型使用场景：

- 主系统后端联调前，先改目标地址
- 验证主系统接口是否可接收
- 验证主系统前端是否能弹窗

## 3.7 快照接口

对应接口：

- `GET /fall-events/snapshots/{filename}`

功能职责：

- 提供已确认跌倒事件的快照访问能力

典型使用场景：

- 主系统详情页展示
- 联调核对是否真的有事件截图
- 告警消息里附带图片

## 4. 关键业务状态说明

## 4.1 `fall_state`

常见状态：

- `normal`
- `falling`
- `fallen_candidate`
- `fallen_confirmed`

业务含义：

- `normal`
  - 正常状态
- `falling`
  - 正在发生明显下落或时序倾向
- `fallen_candidate`
  - 有跌倒嫌疑，但尚未最终确认
- `fallen_confirmed`
  - 已确认跌倒，可触发正式事件

## 4.2 `alarm_confirmed`

含义：

- 是否进入正式告警态

推荐理解：

- `alarm_confirmed=true` 时，外部系统才应把它当作需要落库、弹窗、推送的正式事件

## 4.3 `incident_id`

含义：

- 一次确认跌倒事件的唯一业务编号

作用：

- 去重
- 详情查询
- 快照关联
- 主系统告警流转

## 4.4 `pose_available`

含义：

- 当前对象是否有可用姿态数据

注意：

- 没有 pose 不等于一定不能识别跌倒
- 但 pose 缺失会影响姿态特征和前端骨架显示

## 4.5 `missing_conditions`

含义：

- 字段规则、结果融合规则未通过时，明确列出缺了哪些条件

当前价值：

- 是这轮修复后非常关键的可解释性字段
- 以后排查 `field_rules_not_met` 不再需要先读源码

## 5. 当前项目中的几个关键修复背景

## 5.1 no-person false positive

曾经的问题：

- 画面无人
- 只有 fall detector box
- 却被提升成 tracked person
- 最终被确认成跌倒

修复后：

- 没有真实 person evidence 的 fall-only box 不再直接确认

## 5.2 field rule sitting false confirm

曾经的问题：

- 坐姿
- 被 `field_fall_candidate_promoted`
- 最终 `confirmed=True`

修复后：

- 当前帧没有 fall object 时，不能继续靠历史 strong hint 直接 confirmed
- field confirm 不再仅凭粗网格累计
- 缺条件时会输出 `missing_conditions`

## 6. 面向不同角色的推荐接口

### 前端 / Demo

- `GET /demo`
- `WS /ws/results`
- `GET /stream/latest-frame.jpg`
- `GET /status`

### 主系统后端

- `GET /integration/results/{camera_id}/latest`
- `GET /integration/connection-status`
- `GET /fall-events/snapshots/{filename}`

### 主系统前端

- `GET /integration/fall-alerts/{camera_id}/poll`
- 或由主系统后端再转发

### 测试与运维

- `GET /healthz`
- `GET /status`
- `POST /stream/probe`
- `POST /alerting/simulation/send-once`

## 7. 当前接口使用建议

1. 业务读取优先使用 `/integration/...`，不要长期只依赖 `/status`。
2. 排障优先使用 `/status`，因为它最完整。
3. 现场误报/漏报一定要同时保存：
   - `/status`
   - `latest-frame.jpg`
   - 运行日志
4. 若出现 `field_rules_not_met`，优先看 `missing_conditions`。
