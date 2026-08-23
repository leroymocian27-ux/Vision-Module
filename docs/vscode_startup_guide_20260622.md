# Vision Service VS Code Startup Guide - 2026-06-22

本文档说明如何在 VS Code 中进入正确目录、选择正确 Python 环境、启动后端、打开前端，并确认项目已经成功运行。

## 1. 正确环境是什么

这个项目的主服务是 Python / FastAPI 后端，前端是由后端挂载出来的静态页面。

正确工作目录：

```powershell
D:\Program\vision_service
```

正确 Python 解释器：

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe
```

正确后端入口：

```text
app.main:app
```

正确后端端口：

```text
8000
```

正确前端访问地址：

```text
http://127.0.0.1:8000/demo
```

不要进入这些目录启动主后端：

```text
D:\Program\vision_service\app
D:\Program\vision_service\frontend_demo
D:\Program\vision_service\identity_service
```

`identity_service` 是独立身份服务，默认不是启动主视觉后端所必需的。

## 2. 用 VS Code 打开正确项目

1. 打开 VS Code。
2. 点击 `File` -> `Open Folder...`。
3. 选择这个文件夹：

```powershell
D:\Program\vision_service
```

4. 打开后确认 VS Code 左侧资源管理器顶层能看到这些文件或目录：

```text
app
frontend_demo
tests
docs
.env
requirements.txt
README.md
```

如果 VS Code 顶层只看到 `app` 或只看到 `frontend_demo`，说明打开错了目录，需要重新打开 `D:\Program\vision_service`。

## 3. 选择正确 Python 环境

项目已经配置了 `.vscode/settings.json`，默认解释器是：

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe
```

在 VS Code 中确认方法：

1. 按 `Ctrl + Shift + P`。
2. 输入并选择 `Python: Select Interpreter`。
3. 选择或确认以下解释器：

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe
```

也可以在 VS Code 终端中执行：

```powershell
& "C:\Users\YANG\.conda\envs\torchgpu\python.exe" --version
```

当前已验证结果：

```text
Python 3.10.20
```

## 4. 安装或检查依赖

第一次运行，或者依赖变更后，在 VS Code 终端执行：

```powershell
cd D:\Program\vision_service
& "C:\Users\YANG\.conda\envs\torchgpu\python.exe" -m pip install -r requirements.txt
```

快速检查核心依赖是否能导入：

```powershell
cd D:\Program\vision_service
& "C:\Users\YANG\.conda\envs\torchgpu\python.exe" -c "import fastapi, uvicorn, cv2, numpy; print('imports_ok')"
```

看到下面输出说明核心依赖正常：

```text
imports_ok
```

## 5. 检查启动配置

项目启动时会自动读取：

```powershell
D:\Program\vision_service\.env
```

当前稳定演示模式建议保持：

```text
MAIN_SYSTEM_REPORT_DRY_RUN=true
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
```

这表示：

- 跌倒事件会上报到本地流程，但不会真实 POST 到主系统。
- 姿态 pose 模块关闭，前端不会显示骨架。
- 当前运行更适合稳定演示和本地验证。

注意：不要在文档、截图或聊天中暴露 `.env` 里的摄像头密码、token、完整 RTSP 密码。

## 6. 启动后端方式一：VS Code 任务启动

项目已经配置了 `.vscode/tasks.json`，可以直接用 VS Code 任务启动。

操作步骤：

1. 在 VS Code 中按 `Ctrl + Shift + P`。
2. 输入并选择 `Tasks: Run Task`。
3. 选择：

```text
Start Vision Service
```

4. VS Code 会在终端中执行：

```powershell
C:\Users\YANG\.conda\envs\torchgpu\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

5. 看到类似下面日志，表示后端启动成功：

```text
Uvicorn running on http://0.0.0.0:8000
```

## 7. 启动后端方式二：手动命令启动

在 VS Code 中打开终端：

1. 点击 `Terminal` -> `New Terminal`。
2. 确认终端是 PowerShell。
3. 执行：

```powershell
cd D:\Program\vision_service
& "C:\Users\YANG\.conda\envs\torchgpu\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

这个终端需要保持打开。要停止后端，在这个终端按：

```text
Ctrl + C
```

## 8. 如果 8000 端口已经被占用

先检查端口：

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,State,OwningProcess
```

再确认这个进程是不是当前项目：

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId=<这里填PID>" |
  Select-Object ProcessId,ExecutablePath,CommandLine
```

如果看到类似：

```text
C:\Users\YANG\.conda\envs\torchgpu\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

说明后端已经在运行，不需要重复启动。

如果确认是旧的同一个后端进程，并且需要重启，可以先在原 VS Code 终端按 `Ctrl + C`。如果找不到原终端，再执行：

```powershell
Stop-Process -Id <这里填PID>
```

然后重新启动后端。

## 9. 验证后端是否成功启动

后端启动后，重新开一个 VS Code 终端，不要关闭正在运行 uvicorn 的终端。

检查健康接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

成功时应看到：

```text
status
------
ok
```

检查完整状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/status | ConvertTo-Json -Depth 8
```

重点看这些字段：

```text
service_status = running
cameras[0].running = true
cameras[0].stream_state = connected
detection[0].loaded = true
tracking.tracker_running = true
pose.pose_enabled = false
pose.pose_provider = disabled_placeholder
fall_event_reporter.enabled = true
fall_event_reporter.last_post_status = dry_run_skipped
```

检查前端静态页是否可访问：

```powershell
$r = Invoke-WebRequest http://127.0.0.1:8000/demo -UseBasicParsing
"HTTP $($r.StatusCode) $($r.StatusDescription)"
```

成功时应看到：

```text
HTTP 200 OK
```

检查前端使用的最新结果接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/integration/results/camera_01/latest |
  ConvertTo-Json -Depth 6
```

成功时应能看到：

```text
type = vision_result
camera_id = camera_01
service_state = running
objects = [...]
detector.name = ultralytics_yolo
```

检查告警轮询接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/integration/fall-alerts/camera_01/poll |
  ConvertTo-Json -Depth 6
```

没有跌倒事件时，返回 `no_alert` 是正常的：

```text
status = no_alert
should_popup = false
```

## 10. 打开前端

后端成功启动后，在浏览器打开：

```text
http://127.0.0.1:8000/demo
```

页面打开后：

1. `Camera` 保持：

```text
camera_01
```

2. 如果 `.env` 中已经有默认 RTSP 地址，可以不改页面里的 RTSP 输入框。
3. 如果要手动指定摄像头，把 `RTSP URL` 改成真实地址。
4. 点击 `Start` 启动或切换视频源。
5. 点击 `Connect` 建立 WebRTC 视频和 WebSocket 结果连接。

成功时页面上应看到：

```text
WebRTC: connected
WebSocket: connected
Stream: connected
Frame: 宽x高 + 帧号
Persons: 人数
Detect FPS / Track FPS / AI FPS 有数值
```

当前稳定模式下，`Pose` 显示 `pose placeholder` 或类似状态是正常的，因为 `.env` 配置了：

```text
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
```

## 11. 是否通过测试可以成功启动

可以通过测试和接口验证确认项目当前可启动。

测试命令：

```powershell
cd D:\Program\vision_service
& "C:\Users\YANG\.conda\envs\torchgpu\python.exe" -m pytest -q
```

本机当前已验证结果：

```text
76 passed in 37.04s
```

接口验证结果：

```text
GET /healthz                         OK
GET /status                          OK
GET /demo                            HTTP 200 OK
GET /integration/results/.../latest  OK
GET /integration/fall-alerts/...     OK
```

因此，按本文档使用 `D:\Program\vision_service` 作为工作目录、使用 `torchgpu` Python 环境、执行 `uvicorn app.main:app --host 0.0.0.0 --port 8000`，后端可以成功启动，前端可以通过 `/demo` 打开。

## 12. 常见错误

### 12.1 ModuleNotFoundError: No module named app

原因通常是启动目录错了。

错误目录示例：

```powershell
D:\Program\vision_service\app
```

正确做法：

```powershell
cd D:\Program\vision_service
& "C:\Users\YANG\.conda\envs\torchgpu\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 12.2 端口 8000 already in use

说明已经有服务在占用 8000。先执行：

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,State,OwningProcess
```

如果占用进程本来就是：

```text
python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

那说明后端已经启动，可以直接打开：

```text
http://127.0.0.1:8000/demo
```

### 12.3 前端打不开

先检查后端：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

如果这个接口不通，说明后端没有启动成功。先回到第 6 节或第 7 节启动后端。

### 12.4 页面没有骨架

当前稳定模式关闭了 pose，这是正常现象：

```text
ENABLE_POSE=false
POSE_PROVIDER=disabled_placeholder
```

### 12.5 没有跌倒弹窗

没有跌倒事件时：

```text
/integration/fall-alerts/camera_01/poll
```

返回 `no_alert` 是正常的。只有检测到并确认跌倒事件时，才会出现对应告警数据。

## 13. 最短启动流程

已经安装好环境时，最短流程是：

```powershell
cd D:\Program\vision_service
& "C:\Users\YANG\.conda\envs\torchgpu\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

然后浏览器打开：

```text
http://127.0.0.1:8000/demo
```

再用这些命令确认：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8000/status
```
