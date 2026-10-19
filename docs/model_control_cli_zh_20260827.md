# 模型终端控制与日志监听

项目目录：

```text
E:\HealthProtection\camera-service
```

本功能的 CLI 是 HTTP 客户端，不会重新加载模型，也不会启动第二个 FastAPI。前端按钮和 CLI 都操作当前运行中的同一个 Post-Fall V2 Runtime。

## 1. 启动 Vision Service

推荐使用 GPU Python 环境启动，使二分类 ONNX 使用 CUDA：

```powershell
Set-Location "E:\HealthProtection\camera-service"
.\scripts\start_visual_gpu.ps1 -HostName 127.0.0.1 -Port 8000
```

等价命令：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

不要使用旧 `.venv` 命令作为 GPU 启动命令，因为当前 `.venv` 没有 `CUDAExecutionProvider`。

## 2. 二分类终端命令

新开 VS Code 终端，并保持目录为项目根目录：

```powershell
Set-Location "E:\HealthProtection\camera-service"
```

连接视频后，启动二分类并持续监听：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model binary start
```

如果只想启动、不进入日志监听：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model binary start --no-follow
```

查看状态：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model binary status
```

监听已经由前端开启的二分类：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model binary logs --follow
```

停止二分类：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model binary stop
```

二分类日志会显示 provider、采样 FPS、概率、聚合状态、推理延迟、队列和掉帧等信息。正常 GPU 状态应看到：

```text
Provider: CUDAExecutionProvider
```

## 3. 千问终端命令

千问必须在二分类已经开启后启用。启用并持续监听：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model qwen start
```

只启用、不进入监听：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model qwen start --no-follow
```

查看状态：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model qwen status
```

监听已经由前端开启的千问：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model qwen logs --follow
```

停止千问复核：

```powershell
E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe -m app.cli model qwen stop
```

这里的“启动千问”是启用当前服务的 Qwen 复核能力，不会另起一个 Ollama。真正的 Qwen 推理由本机：

```text
http://127.0.0.1:11434/api/chat
```

对应的 Ollama 服务负责。

## 4. Ctrl+C 行为

在 `logs --follow` 或 `start` 的日志监听中按 `Ctrl+C`，只会退出当前终端的监听：

```text
日志监听退出
模型继续运行
```

需要停止模型时必须执行对应的 `stop` 命令。

## 5. 前端同步

前端每秒读取：

```text
GET /runtime-control/status
```

因此 CLI 启用或停止模型后，页面按钮会自动变为对应状态。反过来，前端启用模型后，CLI 的 `status` 和 `logs --follow` 也读取同一份后端状态和日志。

## 6. 常用排查

确认 Vision Service 在线：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/healthz"
```

确认二分类 provider：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/runtime-control/status?camera_id=camera_01" | ConvertTo-Json -Depth 8
```

确认 Ollama 模型：

```powershell
Invoke-RestMethod "http://127.0.0.1:11434/api/tags" | ConvertTo-Json -Depth 6
```

监听显卡：

```powershell
nvidia-smi -l 1
```

在 Qwen 产生请求时，观察 `ollama.exe` 是否占用显存。是否使用 GPU 由 Ollama 运行时决定，不由 CLI 的 Python 环境决定。
