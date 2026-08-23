# 专家交接：当前未完成项与已知问题

## 1. 真实 RTSP 仍未稳定进入项目

### 现象

- 主服务可以启动
- `/demo` 可以打开
- `/healthz` 正常
- 但真实 RTSP 情况下 `/status` 常停留在：
  - `connected=false`
  - `stream_state=connecting`
  - `last_error=stream closed`

### 已知事实

- VLC 图形界面在桌面会话中曾能成功播放该 RTSP
- 自动化后台进程所在上下文里，对摄像头的网络探测和抓流结果不稳定
- PyAV 与 OpenCV/FFmpeg 在当前自动化上下文里都曾失败

### 当前判断

这不是单纯“摄像头坏了”或“URL 错了”，而是：

- 真实 RTSP 验收严重依赖桌面会话网络上下文
- 当前自动化后台上下文与桌面 VLC 可用会话可能不同

### 专家要做的事

- 把真实 RTSP 验收固定到“桌面 VLC 成功同一会话”
- 不再用错误上下文得出摄像头失败结论
- 在那个会话里重新验证：
  - `/stream/probe`
  - `/stream/start`
  - `/status`
  - `/demo`
  - WebRTC
  - WebSocket

## 2. 本地文件 EOF 生命周期还未完全做实

### 现象

本地视频样本可以启动和产出结果，但播完文件后曾出现：

- `read frame failed`
- `reconnect_scheduled`
- 状态反复重连

### 影响

这会污染以下测试结论：

- 本地文件回归
- WebRTC 长时间连接
- WebSocket 结果流
- 高级模块在可控输入下的稳定验证

### 当前目标

本地文件播完时必须进入“正常结束”语义，而不是错误恢复语义。

### 期望行为

- 不自动重连
- `stream_state=disconnected`
- `reconnect_reason=eof`
- `last_error=null`
- 历史最新帧和最新结果可保留用于观察

## 3. 高级模块仍处于“接入成功，但未完全验收”

### 3.1 pose

现状：

- `PoseService` 已接入
- 但模型可用性不稳定

已知问题：

- `yolov8n-pose.pt` 当前目录未必存在
- `yolo26n-pose.pt` 与当前 `ultralytics` 版本可能不兼容
- 过去曾触发隐式下载 `yolov8n-pose.pt`

要求：

- 禁止隐式联网下载模型
- 只允许用本地现成模型
- 模型不可用时只降级，不拖主链路

### 3.2 behavior

现状：

- 已接入
- 如果 pose 不稳定，behavior 很容易长期停在 `unknown`

要求：

- 行为层只能在 pose 新鲜时运行
- 没有 pose 时保持中性输出，不抛异常

### 3.3 temporal

现状：

- 已有状态输出
- 可以给出默认风险、默认 fall preview

要求：

- 无 pose / 无稳定 tracking 时输出中性状态
- 不能制造虚假的 pose freshness

### 3.4 identity binding

现状：

- sidecar 可启动
- 但 `recognizer_loaded=false`
- 缺少 `insightface`

要求：

- sidecar 不可识别时允许 `identity_binding_enabled=true`
- 匹配失败要安全降级
- 不影响检测 / 跟踪 / 视频 / WebRTC

## 4. WebRTC 已做基础闭环，但还需桌面会话联调

### 已完成

- `/webrtc/offer`
- `/webrtc/candidate`
- `PeerManager.add_ice_candidate`
- 本地脚本曾验证：
  - `track_received=true`

### 仍需联调

- 浏览器真实 `/demo` 页面
- Start + Connect 操作序列
- 多标签连接
- 断开重连释放 peer

### 专家重点

- 不要只看接口 200
- 要看浏览器是否真的持续收到 video track

## 5. 当前状态接口的一致性仍需保持

当前已经收敛成单流稳定版，但专家需要继续保持这些原则：

- `/stream/start` 兼容旧字段，但运行时只允许一个真实源
- `/stream/source` 与 `/status` 不能给出互相矛盾的结论
- `main_stream` / `analysis_stream` 只是单流别名，不应伪装成已完成双流

## 6. 10 小时工期下的优先级

### 必须完成

1. 本地文件 EOF 生命周期修正并通过回归
2. 真实 RTSP 在桌面会话中重新验收
3. 高级模块默认开启时确认“可降级、不拖主链路”

### 可以降级完成

1. identity sidecar 继续 `recognizer_loaded=false`
2. pose 模型暂时不可用，但主链路稳定
3. behavior/temporal 保持中性输出

### 本轮不做

1. 真正双流运行时
2. 正式告警
3. snapshot / retry queue / 推送
4. 新接口设计

## 7. 交接结论

当前未完成项不是发散的，而是已经明确集中在：

- 真实 RTSP 验收上下文
- 本地文件 EOF 生命周期
- 高级模块稳定降级
- Demo 最终联调

这四项解决后，项目就能从“已有框架”迈到“当前版本可实际验收”。
