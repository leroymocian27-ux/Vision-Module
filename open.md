```text
E:\国赛\camera-service
```

然后打开 PowerShell 终端，依次执行下面 3 条命令：

```powershell
Set-Location "E:\国赛\camera-service"
```

```powershell
$env:VISION_SERVICE_ENV_FILE = (Resolve-Path ".\configs\safe_demo.env").Path
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

看到：

```text
Application startup complete.
Uvicorn running on http://127.0.0.1:8000
```

就代表项目启动成功。**这个终端不要关闭。**

如果电脑重启后 Ollama 没有自动运行，再单独开一个 VS Code PowerShell 终端执行：

```powershell
ollama serve
```

然后浏览器打开：

```text
http://127.0.0.1:8000/demo/
```

你也可以直接在第二个终端执行：

```powershell
Start-Process "http://127.0.0.1:8000/demo/"
```

所以你真正需要记住的启动流程只有：

```powershell
Set-Location "E:\国赛\camera-service"

$env:VISION_SERVICE_ENV_FILE = (Resolve-Path ".\configs\safe_demo.env").Path

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

这套命令启动的就是你现在要的 **`safe_demo` + mock camera + Post-Fall V2 + 8000 端口**。

rtsp://127.0.0.1:8554/go2_front
