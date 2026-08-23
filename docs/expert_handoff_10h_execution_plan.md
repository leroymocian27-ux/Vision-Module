# 专家交接：10 小时执行计划

## 目标

在不新增用户功能、不破坏现有接口和 Demo 的前提下，在 10 小时内最大化落地当前未完成项。

最终目标不是“代码更漂亮”，而是：

- 主服务稳定启动
- mock / 本地样本稳定可测
- 真实 RTSP 有明确可执行验收路径
- 高级模块默认开启时可降级运行
- 前端 `/demo` 可作为正式验收入口

## 时间分配建议

### 第 1 小时：快速校准环境与事实

- 确认当前仓库路径和 Python 环境
- 确认 `mock`、本地样本、`identity_service` 健康状态
- 确认当前真实 RTSP 仍必须在桌面 VLC 会话中验收
- 浏览日志，避免重复已知失败路径

产出：

- 一页“当前运行事实”

### 第 2-3 小时：修本地文件 EOF 生命周期

- 修正本地文件源与 RTSP 源的语义分流
- 让本地文件播完后进入正常结束态，不再重连风暴
- 验证：
  - `person_bus_loop.mp4`
  - `identity_self_loop.mp4`
  - `7992a66e51c7700a23f5e3798321077d.mp4`

通过标准：

- 3 个样本都能启动
- EOF 后不再进入重连循环
- `/status` 状态稳定

### 第 4-5 小时：高级模块默认开启下的稳定验证

- 在本地样本上跑：
  - `ENABLE_POSE=true`
  - `ENABLE_BEHAVIOR=true`
  - `ENABLE_TEMPORAL=true`
  - `ENABLE_IDENTITY_BINDING=true`
- 重点验证：
  - 主链路不被拖垮
  - pose 不可用时只降级
  - temporal 有中性输出
  - identity sidecar 失败只降级

通过标准：

- 视频 / 检测 / 跟踪 / WebRTC / WebSocket 继续可用
- 高级模块错误只体现在对应状态字段里

### 第 6 小时：WebRTC / WebSocket / Demo 联调

- 用 mock 和本地样本重跑：
  - `/webrtc/offer`
  - `/webrtc/candidate`
  - `WS /ws/results`
  - `/demo`
- 检查：
  - video track 是否稳定
  - `frame_seq` 是否递增
  - 控制台无旧的 500 / JS 空指针问题

通过标准：

- `/demo` 在 mock / 本地样本下稳定出图
- WebSocket 稳定推流
- 多标签和重复 Connect 不明显泄漏

### 第 7-8 小时：桌面会话下真实 RTSP 验收

- 在与 VLC 成功播放同一桌面会话中：
  - `stream/probe`
  - `stream/start`
  - `status`
  - `/demo`
  - WebRTC Connect
  - WebSocket

通过标准：

- `frame_seq > 0`
- `connected=true`
- 浏览器可见实时画面
- WebRTC 进入 `connected`

注意：

- 如果当前自动化后台上下文与桌面会话不同，不要在后台上下文里给真实 RTSP 下失败结论

### 第 9 小时：异常恢复与边界验证

- 真实 RTSP 短断流恢复
- 错误地址切换再切回
- 重复 Start / Stop / Connect
- sidecar 不可用恢复

通过标准：

- 不崩溃
- 不出现错误风暴
- 状态字段语义一致

### 第 10 小时：整理验收记录与交付结论

- 记录：
  - 通过项
  - 降级通过项
  - 阻塞项
  - 明确不做项
- 输出一页最终交付说明

## 专家执行顺序

严格按下面顺序执行，不建议跳步：

1. 环境校准
2. 本地文件 EOF 修正
3. 高级模块降级验证
4. WebRTC / WebSocket / Demo
5. 桌面会话 RTSP
6. 异常恢复
7. 交付总结

## 关键文件入口

### 采集与生命周期

- `app/camera/capture_worker.py`
- `app/camera/subprocess_capture_worker.py`
- `app/camera/capture_process.py`
- `app/camera/source_manager.py`

### 状态与接口

- `app/services/stream_service.py`
- `app/services/status_service.py`
- `app/api/rest_api.py`

### 前端与 WebRTC

- `app/streaming/peer_manager.py`
- `app/api/webrtc_api.py`
- `frontend_demo/app.js`
- `frontend_demo/index.html`

### 高级模块

- `app/pose/yolo_pose_estimator.py`
- `app/services/pose_worker_service.py`
- `app/services/behavior_service.py`
- `app/services/temporal_service.py`
- `app/services/identity_binding_service.py`

## 验收结论分类模板

每项只允许归类到以下四种之一：

- **通过**
- **通过但降级**
- **失败且阻塞**
- **已知缺陷但不阻塞本轮目标**

## 最终交付标准

10 小时结束时，至少要做到：

- 主服务与 `identity_service` 可稳定启动
- mock / 本地视频路径全部可测
- 本地文件 EOF 不再污染测试结论
- `/demo` 在 mock / 本地样本下稳定出图
- 真实 RTSP 有清晰、可重复的桌面会话验收路径
- 高级模块开启后，即使降级，也不拖垮主链路
