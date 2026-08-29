from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = os.getenv("VISION_SERVICE_BASE_URL", "http://127.0.0.1:8000")


def _default_camera_id() -> str:
    explicit = os.getenv("VISION_SERVICE_CAMERA_ID")
    if explicit and explicit.strip():
        return explicit.strip()
    env_path = os.getenv("VISION_SERVICE_ENV_FILE")
    candidates = []
    if env_path:
        candidates.append(env_path)
    candidates.append(str(os.path.join(os.getcwd(), ".env")))
    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key.strip() == "DEFAULT_CAMERA_ID" and value.strip():
                        return value.strip().strip("'\"")
        except OSError:
            continue
    return "camera_01"


DEFAULT_CAMERA_ID = _default_camera_id()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "model":
        parser.print_help()
        return 0
    try:
        return _run_model_command(args)
    except KeyboardInterrupt:
        print("\n已退出日志监听，模型继续运行。")
        return 0
    except CliError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="camera-service 模型控制与日志监听工具",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Vision Service 地址")
    parser.add_argument("--camera-id", default=DEFAULT_CAMERA_ID, help="摄像头 ID")
    commands = parser.add_subparsers(dest="command")
    model = commands.add_parser("model", help="模型控制")
    model_subcommands = model.add_subparsers(dest="model_kind", required=True)
    for kind in ("binary", "qwen"):
        kind_parser = model_subcommands.add_parser(kind, help=f"{kind} 模型")
        actions = kind_parser.add_subparsers(dest="action", required=True)
        start = actions.add_parser("start", help="启用模型并监听日志")
        start.add_argument("--no-follow", action="store_true", help="启用后不进入日志监听")
        actions.add_parser("stop", help="停用模型")
        actions.add_parser("status", help="查看模型状态")
        logs = actions.add_parser("logs", help="查看模型日志")
        logs.add_argument("--follow", action="store_true", help="持续监听新日志")
        logs.add_argument("--tail", type=int, default=20, help="先显示最近多少条日志")
    return parser


def _run_model_command(args: argparse.Namespace) -> int:
    kind = args.model_kind
    action = args.action
    if action == "start":
        current = _control_status(args.base_url, args.camera_id)
        already_enabled = bool(current.get(f"{kind}_enabled"))
        if already_enabled:
            payload = current
            print(f"{kind_label(kind)}已经开启")
        else:
            payload = _request(
                args.base_url,
                "POST",
                f"/runtime-control/{kind}",
                {"camera_id": args.camera_id, "enabled": True},
            )
            print(f"{kind_label(kind)}已开启")
        _print_model_status(kind, payload)
        if not args.no_follow:
            _follow_logs(args.base_url, args.camera_id, kind, tail=20)
        return 0
    if action == "stop":
        payload = _request(
            args.base_url,
            "POST",
            f"/runtime-control/{kind}",
            {"camera_id": args.camera_id, "enabled": False},
        )
        print(f"{kind_label(kind)}已关闭")
        _print_model_status(kind, payload)
        return 0
    if action == "status":
        payload = _control_status(args.base_url, args.camera_id)
        _print_model_status(kind, payload)
        return 0
    if action == "logs":
        if args.follow:
            _follow_logs(args.base_url, args.camera_id, kind, tail=args.tail)
        else:
            payload = _request(
                args.base_url,
                "GET",
                f"/runtime-control/logs/{kind}?camera_id={args.camera_id}&tail={max(0, min(args.tail, 500))}",
            )
            _print_model_status(kind, payload.get("status") or {})
            for event in payload.get("events") or []:
                _print_log_event(event)
        return 0
    raise CliError(f"不支持的操作：{action}")


def _follow_logs(base_url: str, camera_id: str, kind: str, *, tail: int) -> None:
    path = f"/runtime-control/logs/{kind}/stream?camera_id={quote(camera_id)}&tail={max(0, min(tail, 200))}"
    request = Request(_join_url(base_url, path), headers={"Accept": "text/event-stream"})
    try:
        response = urlopen(request, timeout=None)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise CliError(_connection_message(base_url, exc)) from exc
    print(f"已连接 {kind_label(kind)}日志流，按 Ctrl+C 退出监听（不会关闭模型）。")
    current_event = "message"
    data_lines: list[str] = []
    try:
        while True:
            line = response.readline()
            if not line:
                print("日志流已断开。", file=sys.stderr)
                return
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                if data_lines:
                    payload = _parse_json_data(data_lines)
                    if current_event == "status":
                        _print_stream_status(kind, payload)
                    elif current_event == "log":
                        _print_log_event(payload)
                current_event = "message"
                data_lines = []
                continue
            if text.startswith("event:"):
                current_event = text.partition(":")[2].strip()
            elif text.startswith("data:"):
                data_lines.append(text.partition(":")[2].lstrip())
    finally:
        response.close()


def _request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(_join_url(base_url, path), data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except json.JSONDecodeError:
            pass
        raise CliError(f"camera-service 返回 HTTP {exc.code}：{detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise CliError(_connection_message(base_url, exc)) from exc
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise CliError("camera-service 返回了无法解析的 JSON") from exc


def _control_status(base_url: str, camera_id: str) -> dict[str, Any]:
    return _request(
        base_url,
        "GET",
        f"/runtime-control/status?camera_id={quote(camera_id)}",
    )


def _print_model_status(kind: str, payload: dict[str, Any]) -> None:
    if "status" in payload and isinstance(payload["status"], dict):
        status = payload["status"]
    else:
        control = payload
        runtime = control.get("runtime") or {}
        if kind == "binary":
            status = {
                "state": "running" if control.get("binary_enabled") else "stopped",
                "enabled": control.get("binary_enabled"),
                "camera_id": control.get("camera_id"),
                "provider": runtime.get("binary_provider"),
                "model_sha256": runtime.get("binary_model_sha256"),
                "active_providers": runtime.get("binary_active_providers"),
                "sample_fps": runtime.get("binary_sample_fps") or runtime.get("sample_fps"),
                "frames_processed": runtime.get("frames_processed"),
                "frames_dropped": runtime.get("frames_dropped"),
                "queue_depth": runtime.get("queue_depth"),
                "latency_ms": runtime.get("binary_inference_latency_ms"),
                "avg_latency_ms": runtime.get("binary_inference_latency_avg_ms"),
                "last_error": runtime.get("last_error"),
            }
        else:
            status = {
                "state": "enabled" if control.get("qwen_enabled") else "stopped",
                "enabled": control.get("qwen_enabled"),
                "camera_id": control.get("camera_id"),
                "provider": runtime.get("vlm_provider"),
                "model": runtime.get("vlm_model"),
                "active_count": runtime.get("vlm_active_count"),
                "queue_depth": runtime.get("vlm_queue_depth"),
                "submitted_count": runtime.get("vlm_submitted_count"),
                "finished_count": runtime.get("vlm_finished_count"),
                "last_error": runtime.get("last_error"),
            }
    print(f"{kind_label(kind)}状态")
    for key, label in _status_labels(kind).items():
        if key in status:
            print(f"  {label}: {_format_value(status[key])}")


def _print_stream_status(kind: str, status: dict[str, Any]) -> None:
    state = status.get("state", "-")
    provider = status.get("provider") or status.get("model") or "-"
    print(f"[{time.strftime('%H:%M:%S')}] {kind_label(kind)} state={state} runtime={provider}")


def _print_log_event(event: dict[str, Any]) -> None:
    timestamp = str(event.get("emitted_at") or "")
    if "T" in timestamp:
        timestamp = timestamp.split("T", 1)[1].split(".", 1)[0].replace("Z", "")
    level = str(event.get("level") or "info").upper()
    message = event.get("message") or "-"
    fields = event.get("fields") or {}
    detail = " ".join(f"{key}={_format_value(value)}" for key, value in fields.items())
    print(f"[{timestamp or time.strftime('%H:%M:%S')}] [{level}] {message}{(' ' + detail) if detail else ''}", flush=True)


def _status_labels(kind: str) -> dict[str, str]:
    if kind == "binary":
        return {
            "state": "Status",
            "enabled": "Enabled",
            "camera_id": "Camera",
            "provider": "Provider",
            "model_sha256": "Model SHA256",
            "active_providers": "Active providers",
            "sample_fps": "Sample FPS",
            "frames_processed": "Frames processed",
            "frames_dropped": "Frames dropped",
            "queue_depth": "Queue",
            "latency_ms": "Last latency ms",
            "avg_latency_ms": "Average latency ms",
            "last_error": "Last error",
        }
    return {
        "state": "Status",
        "enabled": "Enabled",
        "camera_id": "Camera",
        "provider": "Provider",
        "model": "Model",
        "active_count": "Active requests",
        "queue_depth": "Queue",
        "submitted_count": "Submitted",
        "finished_count": "Finished",
        "last_error": "Last error",
    }


def _format_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _parse_json_data(data_lines: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return {"message": "\n".join(data_lines)}
    return payload if isinstance(payload, dict) else {"message": payload}


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _connection_message(base_url: str, exc: Exception) -> str:
    return f"无法连接 camera-service：{base_url}。请先启动 FastAPI 服务。({exc})"


def kind_label(kind: str) -> str:
    return "二分类" if kind == "binary" else "千问"


class CliError(RuntimeError):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
