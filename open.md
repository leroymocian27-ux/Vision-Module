```text
E:\HealthProtection\camera-service
```

打开 PowerShell 终端，只使用 CUDA 启动器：

```powershell
Set-Location "E:\HealthProtection\camera-service"
.\scripts\start_visual_gpu.ps1 -HostName 127.0.0.1 -Port 8000
```

看到下面信息才代表比赛后端启动成功：

```text
Ollama CUDA Startup READY
ONNX Runtime providers: ... CUDAExecutionProvider ...
CUDAExecutionProvider available: True
Application startup complete.
Uvicorn running on http://127.0.0.1:8000
```

这个终端不要关闭。启动后打开：

```text
http://127.0.0.1:8000/demo/
```

禁止使用 `.venv`、普通 `uvicorn` 或普通 `ollama serve` 启动比赛系统。
`.venv` 是 CPU 环境，普通 `ollama serve` 不会强制 CUDA。当前后端默认启用
`VISION_SERVICE_REQUIRE_CUDA=true`，如果 CUDA、ONNX CUDA provider、GPU Python 或 Ollama GPU
预热不满足要求，系统会直接拒绝启动，避免模型静默跑到 CPU。

模型控制命令也统一使用 GPU Python：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model binary start
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model qwen start
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model binary status
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model qwen status
```

实时视频地址：

```text
http://192.168.8.249:8093/stream.mjpg
```
