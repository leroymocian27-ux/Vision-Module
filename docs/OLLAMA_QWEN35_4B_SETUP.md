# Ollama 与 qwen3.5:4b 部署说明

本文给没有 Ollama 的 Windows 电脑使用。项目中的千问模块通过本机 Ollama 接口调用 `qwen3.5:4b`，模型不会随 GitHub 仓库自动下载。

## 一、安装 Ollama

在 PowerShell 中优先执行：

```powershell
winget install --id Ollama.Ollama -e
```

如果电脑没有 `winget`，请打开官方 Windows 下载页并运行安装程序：

<https://ollama.com/download/windows>

安装完成后，关闭并重新打开 PowerShell，检查安装：

```powershell
ollama --version
```

如果 Ollama 没有自动启动，在一个单独的 PowerShell 窗口执行：

```powershell
ollama serve
```

如果提示 `address already in use`，通常表示 Ollama 已经在后台运行，不需要重复启动。

## 二、下载 qwen3.5:4b

执行：

```powershell
ollama pull qwen3.5:4b
```

下载完成后确认模型存在并支持图像输入：

```powershell
ollama list
ollama show qwen3.5:4b
```

`ollama show` 的能力列表中应包含 `vision`。模型约占 3.4 GB，下载和首次加载时间取决于网络与磁盘速度。

## 三、测试 Ollama

先做文本测试：

```powershell
ollama run qwen3.5:4b "请只回复：本地千问连接正常。"
```

也可以直接测试 HTTP 接口：

```powershell
$body = @{
  model = "qwen3.5:4b"
  messages = @(
    @{ role = "user"; content = "请只回复：本地千问接口正常。" }
  )
  stream = $false
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Uri "http://127.0.0.1:11434/api/chat" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

## 四、获取并配置项目

```powershell
git clone https://github.com/leroymocian27-ux/Vision-Module.git
Set-Location .\Vision-Module
```

创建本机配置文件。`.env` 不应提交到 GitHub：

```powershell
if (-not (Test-Path -LiteralPath ".env")) {
  Copy-Item -LiteralPath ".env.example" -Destination ".env"
}
```

确认 `.env` 中至少包含以下配置：

```env
POST_FALL_V2_VLM_ENABLED=true
POST_FALL_V2_QWEN_ENABLED=true
POST_FALL_V2_QWEN_PROVIDER=qwen_keyframe
POST_FALL_V2_QWEN_MODEL=qwen3.5:4b
POST_FALL_V2_QWEN_BASE_URL=http://127.0.0.1:11434/api/chat
POST_FALL_V2_QWEN_TIMEOUT_SECONDS=90
POST_FALL_V2_QWEN_MAX_IMAGES=6
QWEN_MEDIA_INPUT_ENABLED=true
QWEN_MEDIA_PRIVACY_APPROVED=true
```

仓库中的 `configs/safe_demo.env` 和 `configs/post_fall_v2_candidate.env` 已经使用上述模型。使用配置文件启动时，显式指定的 `VISION_SERVICE_ENV_FILE` 优先级高于 `.env`。

## 五、安装 Python 依赖

项目要求 Python 3.10 或更高版本。建议每台电脑重新创建虚拟环境，不要跨电脑复制 `.venv`：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果电脑只有 Python 3.11，可将第一行改为 `py -3.11 -m venv .venv`。

## 六、验证项目配置

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\validate_config.py --profile safe_demo
```

输出中的 `status` 应为 `PASS`，并且 `post_fall_v2_qwen_model` 应为 `qwen3.5:4b`。

然后执行本地千问关键帧冒烟测试：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_qwen_keyframe_multimodal.py `
  --model qwen3.5:4b `
  --endpoint http://127.0.0.1:11434/api/chat `
  --timeout 120
```

该测试会向 Ollama 发送本地生成的测试图像，不会访问远程千问 API。

## 七、启动系统

先使用安全演示配置启动：

```powershell
$env:VISION_SERVICE_ENV_FILE = (Resolve-Path ".\configs\safe_demo.env").Path
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个 PowerShell 窗口检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8000/status
```

系统的跌倒二分类结果仍由本地 EfficientNet/ONNX 链路决定；`qwen3.5:4b` 只对已经确认的跌倒事件进行关键帧辅助分析，不替代主检测结果。

## 八、常见问题

### `ollama` 不是内部或外部命令

关闭当前终端并重新打开。若仍失败，确认 Ollama 安装目录已加入 PATH，或重新运行官方安装程序。

### `pull model manifest: ... 404`

检查模型名必须完全写成 `qwen3.5:4b`，不要写成 `qwen3.5-4b` 或 `qwen-3.5:4b`。

### `connection refused 127.0.0.1:11434`

在单独窗口运行 `ollama serve`，再执行 `ollama list`。Windows 上 Ollama 已作为后台服务运行时，不要重复启动多个服务。

### 项目提示模型不可用

按顺序执行：

```powershell
ollama list
ollama pull qwen3.5:4b
.\.venv\Scripts\python.exe scripts\validate_config.py --profile safe_demo
```

确认配置中的地址是 `http://127.0.0.1:11434/api/chat`，并重启 Vision Service。每台工程师电脑都必须单独安装 Ollama 并下载模型。

### 安全要求

不要把真实 RTSP 地址、密码、Token 或本机 `.env` 提交到 GitHub。Ollama 默认只监听本机 `127.0.0.1`，项目也会拒绝非本机的 Qwen 地址。
