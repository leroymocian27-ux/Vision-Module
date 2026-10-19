# GPU 运行环境 VS Code 启动与卡顿排查指南 - 2026-08-26

这份指南只针对当前项目：

```text
E:\HealthProtection\camera-service
```

目标是避免继续用旧 `.venv` 命令启动后，让 Post-Fall V2 二分类模型退回 CPU，造成开启二分类后实时画面明显卡顿。

## 1. 推荐启动方式

在 VS Code 里打开项目根目录：

```text
E:\HealthProtection\camera-service
```

### 右上角一键启动（推荐）

在 VS Code 中打开：

```text
scripts/start_visual_gpu_auto.py
```

点击编辑器右上角的“运行 Python 文件”按钮即可。脚本按以下顺序选择第一个未被占用的端口：

```text
8000 -> 8001 -> 8002
```

启动器最终仍调用 `scripts/start_visual_gpu.ps1`，不会绕过固定 GPU Python、CUDA provider 检查或当前视频接收配置。终端会打印实际选中的端口和 Demo 地址。三个端口都被占用时，脚本会明确报错并停止，不会结束其他已有进程。

也可以在“运行和调试”下拉列表选择：

```text
Vision Service GPU (Auto 8000-8002)
```

启动前可以先跑一次本地 GPU 预检：

```powershell
cd E:\HealthProtection\camera-service
.\scripts\check_gpu_runtime_preflight.ps1
```

这个预检会检查 GPU provider、`.venv` rollback provider、EfficientNet ONNX dummy inference、`app.main` 导入、safe_demo 配置，以及临时服务启动后是否保持“未连接视频、不自动开启模型”的状态。

也可以在 VS Code 命令面板中运行任务：

```text
Tasks: Run Task
↓
GPU Runtime Preflight
```

然后在 VS Code 终端执行：

```powershell
cd E:\HealthProtection\camera-service
.\scripts\start_visual_gpu.ps1
```

这个脚本会先检查当前 GPU Conda 环境是否能看到：

```text
CUDAExecutionProvider
```

如果配置要求 GPU 但当前环境没有 CUDA provider，脚本会直接报错并停止，避免你在不知情的情况下用 CPU 跑二分类。

也可以用 VS Code 任务启动：

```text
Tasks: Run Task
↓
Run Vision Service GPU (8000)
```

## 2. 等价直接命令

如果你不想用脚本，也可以直接执行：

```powershell
cd E:\HealthProtection\camera-service
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

这个命令使用的是最终 GPU 环境：

```text
camera-service-gpu
E:\MathModelingTools\conda-envs\camera-service-gpu
```

## 3. 不推荐作为日常启动的旧命令

旧命令仍然保留作 rollback：

```powershell
cd E:\HealthProtection\camera-service
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

但当前 `.venv` 的 ONNX Runtime provider 是：

```text
AzureExecutionProvider
CPUExecutionProvider
```

也就是说，使用旧命令启动后，二分类模型无法使用 `CUDAExecutionProvider`，开启二分类时很可能重新出现 CPU 压力高、画面卡顿、延迟变大的问题。

## 4. 启动后应该是什么状态

服务启动后，系统应该只是准备好功能，不自动开始模型检测：

```text
启动服务
↓
功能准备完成
↓
页面输入 RTSP URL
↓
点击连接画面
↓
只显示实时画面
↓
手动点击开启二分类
↓
二分类才开始运行
↓
手动点击开启千问
↓
千问才参与二分类事件复核
```

启动服务但还没连接视频时，正常状态应该接近：

```text
binary_enabled=false
qwen_enabled=false
runtime.running=false
binary_model_loaded=false
binary_sample_fps=3
webrtc_target_fps=15
```

## 5. 页面操作顺序

1. 打开前端页面。
2. 在 `RTSP URL` 输入框填入摄像头地址。
3. 点击连接画面按钮。
4. 确认页面能看到实时画面。
5. 暂时不要开启模型，先观察视频是否流畅。
6. 点击开启二分类。
7. 确认页面运行状态里 provider 是 `CUDAExecutionProvider`。
8. 只有需要千问复核时，再点击开启千问。

## 6. 二分类真实抽帧频率

当前真实链路保持：

```text
POST_FALL_V2_SAMPLE_FPS=3
```

含义是：

```text
二分类每秒大约从最新帧缓存中取 3 帧进行判断
```

这不是每帧都跑模型。当前优化目标也不是把 3 FPS 降成 1 FPS，而是通过 GPU 推理、latest-frame-only、WebRTC pacing 和 JPG fallback 治理来降低延迟。

## 7. 开启二分类后卡顿时先跑这个诊断

如果你看到：

```text
不开二分类：画面正常
开启二分类：画面明显变卡、延迟变大
```

马上在另一个 VS Code 终端执行：

```powershell
cd E:\HealthProtection\camera-service
.\scripts\diagnose_gpu_runtime.ps1 `
  -JsonOut "artifacts/environment_audit/runtime_diagnosis_latest.json" `
  -FailOnCpuBinaryProvider
```

重点看输出：

```text
binary_provider_status=CUDA_OK
```

这是理想情况。

如果看到：

```text
binary_provider_status=CPU_FALLBACK
```

说明当前二分类实际跑在 CPU 上，这是开启二分类后严重卡顿的直接原因之一。

也可以用 VS Code 任务：

```text
Tasks: Run Task
↓
Diagnose GPU Runtime (8000)
```

## 8. 关键指标怎么看

诊断脚本和页面状态里最重要的是：

| 指标 | 正常含义 |
| --- | --- |
| `binary_provider` | 应为 `CUDAExecutionProvider` |
| `binary_provider_degraded` | 应为 `false` |
| `binary_sample_fps` | 应接近 `3` |
| `queue_depth` | 应为 `0` 或 `1`，不能持续积压 |
| `frame_age_ms` | 越低越好，不能持续增长 |
| `binary_queue_delay_ms` | 越低越好，持续变大说明 AI 输入滞后 |
| `binary_inference_latency_avg_ms` | GPU 下应明显低于 CPU 压力场景 |
| `camera.capture_fps` | 应稳定出帧 |
| `streaming.webrtc_target_fps` | 当前目标是 `15` |

如果 `frame_age_ms` 从几十毫秒逐渐变成几百、上千、几千毫秒，说明实时链路仍有积压或上游处理跟不上。

## 9. 快速检查 GPU 环境

```powershell
cd E:\HealthProtection\camera-service
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -c "import onnxruntime as ort; print(ort.__version__); print(ort.get_available_providers())"
nvidia-smi
```

期望看到：

```text
CUDAExecutionProvider
```

## 10. 真实 RTSP 验收命令

有可访问的授权 RTSP 源后，运行：

```powershell
cd E:\HealthProtection\camera-service
.\scripts\benchmark_real_rtsp_comparison.ps1 `
  -SourceUrl "rtsp://<user>:<password>@<host>:<port>/<path>" `
  -CameraId "camera_01" `
  -DurationSeconds 300
```

然后检查：

```powershell
.\scripts\check_runtime_acceptance.ps1 `
  -ComparisonPath "artifacts/environment_audit/<label>.comparison.json"
```

只有真实 RTSP 300 秒对比、浏览器实看、真实场景、Qwen 事件和主系统交付都通过后，才能说完整实施目标真正闭环。
