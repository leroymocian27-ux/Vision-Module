# Vision Service 项目对接文档

更新时间：2026-06-19

适用版本：

- 仓库：`D:\Program\vision_service`
- 提交：`66b5b82`

## 1. 文档目标

本文档面向项目对接和落地实施，目标不是解释代码，而是帮助外部团队和新加入工程师快速完成：

1. 本地启动
2. 摄像头接入
3. 主系统对接
4. 现场联调
5. 验收留证

## 2. 项目定位

`vision_service` 是跌倒识别侧服务，负责：

- 接摄像头 RTSP
- 做检测/跟踪/姿态/时序分析
- 产生确认跌倒结果
- 保存快照
- 推送告警给主系统

主系统通常负责：

- 接收跌倒事件
- 落库
- 去重
- 转发给前端
- 前端弹窗与展示

## 3. 对接总架构

```text
RTSP Camera
-> vision_service
-> 最新结果 latest_result / integration result
-> confirmed fall
-> snapshot saved
-> POST to main system
-> main system backend
-> dashboard / popup / mobile consumer
```

## 4. 当前关键结论

截至 `66b5b82`，当前重点结论如下：

### 已完成

- 无人画面不再因为 fall-only box 误报 confirmed
- field rule 不再允许“无当前 fall object + 历史 strong hint”直接把坐姿确认成跌倒
- `field_rules_not_met` 已具备 `missing_conditions` 可解释性

### 仍需真人复验

- 坐姿是否完全不再误报
- 真实跌倒是否仍能顺利 confirmed
- 快照和 `incident_id` 是否在现场动作中正常生成

## 5. 环境与依赖

### 代码路径

```text
D:\Program\vision_service
```

### 常用入口

- 后端服务：FastAPI
- Demo 页面：`/demo`
- 状态页：`/status`

### 当前常见运行信息

实际运行时曾看到：

- `runtime_profile=current_camera_live`
- `pose_provider=branch4_legacy`
- `stream_state=connected`
- `capture_fps≈9`

注意：

- 这些是现场运行观测，不是写死配置

## 6. 摄像头对接流程

### 第一步：确认 RTSP 可达

推荐先调用：

- `POST /stream/probe`

如果可达，再启动：

- `POST /stream/start`

### 第二步：确认服务已出图

检查：

- `GET /status`
- `GET /stream/latest-frame.jpg`

期望：

- `stream_state=connected`
- `capture_fps>0`
- `frame_age_ms<500`

### 第三步：确认对象链路在工作

检查：

- `detection.latest_raw_person_count`
- `tracking.tracked_objects_count`
- `latest_result.pose_available`

## 7. 主系统对接方式

## 7.1 推荐职责划分

### vision_service

负责：

- 跌倒识别
- 跌倒确认
- 快照落盘
- 告警事件出站

### 主系统后端

负责：

- 接收 `vision_service` 告警
- 去重
- 落库
- 转发前端
- 供主系统前端查询或订阅

### 主系统前端

负责：

- 弹窗
- 红点
- 告警列表
- 快照展示

## 7.2 主系统推荐接入接口

### 主系统后端读最新结果

建议轮询：

- `GET /integration/results/{camera_id}/latest`

适合拿到：

- `fall_state`
- `alarm_confirmed`
- `incident_id`
- `snapshot_url`
- `snapshot_path`
- `risk_level`

### 主系统前端拿弹窗事件

建议通过主系统后端转发。

如果联调阶段需要直接试验，也可以轮询：

- `GET /integration/fall-alerts/{camera_id}/poll`

### 主系统展示快照

用：

- `GET /fall-events/snapshots/{filename}`

## 8. 告警上报链路

当前 `vision_service` 向主系统发送的是 HTTP POST。

典型目标路径：

```text
/api/v1/video-bridge/fall-events
```

配置相关能力：

- `GET /alerting/status`
- `POST /alerting/endpoint`

联调用模拟：

- `POST /alerting/simulation/send-once`
- `POST /alerting/simulation/start`

## 9. 现场联调建议流程

### 9.1 开始前

先确认：

- 摄像头在线
- 最新帧能打开
- `/status` 正常
- 主系统接收端健康可访问

### 9.2 无人基线测试

期望：

- `raw_person_count=0`
- `tracked_objects_count=0`
- `alarm_confirmed=false`
- `incident_id=null`

### 9.3 正常坐姿测试

动作建议：

- 离开画面 3 秒
- 站立 5 秒
- 坐下保持 10 秒
- 起身离开

期望：

- `alarm_confirmed=false`
- `incident_id=null`
- 不生成跌倒快照

允许：

- `normal`
- 或短暂 `fallen_candidate`

禁止：

- `fallen_confirmed`

### 9.4 真实跌倒测试

动作建议：

- 站立 5 秒
- 明显下落
- 侧躺或仰躺
- 保持 15 秒
- 不翻身
- 不遮挡
- 不贴边
- 全身留在画面内

期望：

- `normal -> falling -> fallen_candidate -> fallen_confirmed`
- `alarm_confirmed=true`
- `incident_id!=null`
- `snapshot` 正常生成

## 10. 现场留证要求

每一轮真人复验建议同时保留：

- `status_samples.jsonl`
- `latest-frame.jpg`
- 关键截图
- 运行日志

最重要的字段：

- `timestamp`
- `raw_person_count`
- `tracked_objects_count`
- `pose_available`
- `fall_state`
- `fall_probability`
- `risk_level`
- `alarm_confirmed`
- `incident_id`
- `candidate_duration_ms`
- `confirm_duration_ms`
- `rejected_reason`
- `missing_conditions`

## 11. 当前已知关键证据目录

推荐先看的目录：

- `logs/acceptance/standard_action_retest_20260618_112537`
- `logs/acceptance/real_retest_after_field_fix_20260618_140733`

意义：

- 第一个目录记录了坐姿误确认和真实跌倒漏确认的原始证据
- 第二个目录是 `66b5b82` 修复后的真人复验采样目录

## 12. 新工程师接手建议

第一优先级：

- 先读 `docs/engineer_handoff_2026-06-19.md`

第二优先级：

- 再看：
  - `docs/interface_api_spec_2026-06-19.md`
  - `docs/interface_function_spec_2026-06-19.md`
  - 本文档

第三优先级：

- 再读代码：
  - `app/services/result_publisher_service.py`
  - `app/services/tracking_worker_service.py`
  - `app/services/temporal_service.py`
  - `app/services/fall_event_reporter_service.py`

## 13. 当前不建议做的事

在没有新证据前，不建议：

- 直接调阈值
- 直接换 YOLO 模型
- 直接换 Pose 权重
- 直接改 RTSP 路径规避问题
- 为了让真实跌倒通过而简单放宽确认条件

## 14. 当前建议下一步

最合理的下一步不是继续猜，而是：

1. 用 `66b5b82` 再做真人复验
2. 根据新证据确认：
   - 坐姿是否已不误报
   - 真实跌倒是否还能确认
   - 无人误报是否仍然稳定
3. 再决定下一轮是修：
   - tracking
   - pose drop
   - field rule
   - temporal confirm
   - result publication
