from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import socket
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import urlopen
import shutil
import json
from dataclasses import replace


ROOT = Path(__file__).resolve().parents[1]
DOTENV = ROOT / ".env"


def _load_dotenv_defaults() -> None:
    if not DOTENV.exists():
        return
    for raw_line in DOTENV.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _env_or(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _default_rtsp_parts() -> dict[str, str]:
    url = _env_or("DEFAULT_RTSP_URL", "")
    if not url:
        return {}
    parsed = urlparse(url)
    parts: dict[str, str] = {}
    if parsed.hostname:
        parts["host"] = parsed.hostname
    if parsed.username:
        parts["username"] = parsed.username
    if parsed.password:
        parts["password"] = parsed.password
    if parsed.port:
        parts["port"] = str(parsed.port)
    if parsed.path:
        parts["path"] = parsed.path
    return parts


def _default_python() -> str:
    candidates = [
        Path(r"C:\Users\YANG\.conda\envs\torchgpu\python.exe"),
        Path(sys.executable),
        Path(shutil.which("python") or ""),
        Path(r"D:\Anaconda\python.exe"),
        Path(r"D:\Python\python.exe"),
    ]
    for candidate in candidates:
        if candidate and str(candidate) and candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    _load_dotenv_defaults()
    rtsp_defaults = _default_rtsp_parts()
    argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description="Start Vision Service for the current LAN camera.")
    parser.add_argument("--host", default=_env_or("CAMERA_RTSP_HOST", rtsp_defaults.get("host", "192.168.8.254")))
    parser.add_argument("--password", default=_env_or("CAMERA_RTSP_PASSWORD", rtsp_defaults.get("password", "")))
    parser.add_argument("--username", default=_env_or("CAMERA_RTSP_USERNAME", rtsp_defaults.get("username", "admin")))
    parser.add_argument("--rtsp-port", type=int, default=int(rtsp_defaults.get("port", "10554")))
    parser.add_argument("--main-path", default="/tcp/av0_0")
    parser.add_argument("--analysis-path", default=rtsp_defaults.get("path", "/tcp/av0_0"))
    parser.add_argument("--rtsp-url", default="", help="Explicit single RTSP URL. Overrides host/path URL construction.")
    parser.add_argument("--main-rtsp-url", default="", help="Explicit display stream URL.")
    parser.add_argument("--analysis-rtsp-url", default="", help="Explicit AI analysis stream URL.")
    parser.add_argument("--capture-backend", default="subprocess_opencv", choices=["opencv", "subprocess_opencv", "subprocess_pyav"])
    parser.add_argument("--temporal-provider", default=_env_or("TEMPORAL_MODEL_PROVIDER", "onnx_lstm"), choices=["mock", "shadow", "onnx_lstm"])
    parser.add_argument("--temporal-model-path", default="models/fall_lstm_v5.onnx")
    parser.add_argument("--temporal-schema-path", default="models/fall_lstm_v5_features.json")
    parser.add_argument("--enable-pose", dest="pose_enabled", action="store_true", default=_env_or("ENABLE_POSE", "true").lower() in {"1", "true", "yes", "on"}, help="Enable pose estimation explicitly.")
    parser.add_argument("--disable-pose", dest="pose_enabled", action="store_false", help="Disable pose and use placeholders. This is the default.")
    parser.add_argument(
        "--pose-provider",
        default=_env_or("POSE_PROVIDER", "yolo11_legacy"),
        choices=["disabled_placeholder", "yolo", "yolo11_legacy", "branch4_legacy", "rtmpose_onnx", "mmpose"],
        help="Use disabled_placeholder for the formal runtime, or enable a legacy provider only when explicitly needed.",
    )
    parser.add_argument("--yolo11-pose-model-path", default=_env_or("YOLO11_POSE_MODEL_PATH", "yolo11n-pose.pt"))
    parser.add_argument("--enable-main-system-alerts", action="store_true", default=_env_or("MAIN_SYSTEM_ALERT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}, help="POST confirmed fall events to health-main.")
    parser.add_argument("--main-system-base-url", default=_env_or("MAIN_SYSTEM_BASE_URL", ""))
    parser.add_argument("--vision-public-base-url", default=_env_or("VISION_SERVICE_PUBLIC_BASE_URL", ""))
    parser.add_argument("--alert-cooldown-seconds", type=float, default=90.0)
    parser.add_argument(
        "--skip-pose-deployment-guard",
        action="store_true",
        help="Development-only bypass for the pose deployment guard. Do not use for production rollout.",
    )
    parser.add_argument(
        "--pose-evidence-package",
        default=_env_or("POSE_EVIDENCE_PACKAGE", "evaluations/pose_evidence_package_check_20260705.json"),
        help="Evidence package JSON used by the pose deployment guard.",
    )
    parser.add_argument(
        "--pose-deployment-guard-output",
        default=_env_or("POSE_DEPLOYMENT_GUARD_OUTPUT", "evaluations/pose_deployment_guard_20260705.json"),
        help="Output JSON written by the pose deployment guard before service launch.",
    )
    parser.add_argument("--api-host", default="0.0.0.0")
    parser.add_argument("--health-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--python", default=_default_python())
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--auto-discover", dest="auto_discover", action="store_true", default=True)
    parser.add_argument("--no-auto-discover", dest="auto_discover", action="store_false")
    args = parser.parse_args()

    if args.auto_discover:
        _apply_discovered_devices(args, argv)

    python_exe = Path(args.python)
    if not python_exe.exists():
        print(f"python not found: {python_exe}", file=sys.stderr)
        return 2

    yolo_config_dir = ROOT / "Ultralytics"
    yolo_config_dir.mkdir(parents=True, exist_ok=True)

    default_main_url = _rtsp_url(args.username, args.password, args.host, args.rtsp_port, args.main_path)
    default_analysis_url = _rtsp_url(args.username, args.password, args.host, args.rtsp_port, args.analysis_path)
    main_url = args.main_rtsp_url or args.rtsp_url or default_main_url
    analysis_url = args.analysis_rtsp_url or args.rtsp_url or default_analysis_url
    vision_public_base_url = args.vision_public_base_url or f"http://{_lan_ipv4() or '127.0.0.1'}:{args.api_port}"

    env = os.environ.copy()
    env.update(
        {
            "VISION_SERVICE_RUNTIME_PROFILE": "current_camera_live",
            "YOLO_CONFIG_DIR": str(yolo_config_dir),
            "ENABLE_DUAL_STREAM": "false",
            "MOCK_CAMERA_ENABLED": "false",
            "DEFAULT_RTSP_URL": analysis_url,
            "MAIN_STREAM_URL": main_url,
            "ANALYSIS_STREAM_URL": analysis_url,
            "CAPTURE_BACKEND": args.capture_backend,
            "MAIN_CAPTURE_BACKEND": args.capture_backend,
            "ANALYSIS_CAPTURE_BACKEND": args.capture_backend,
            "OPENCV_FFMPEG_CAPTURE_OPTIONS": _env_or("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;8000000"),
            "CAPTURE_PROCESS_FRAME_TIMEOUT_MS": _env_or("CAPTURE_PROCESS_FRAME_TIMEOUT_MS", "8000"),
            "CAPTURE_PROCESS_OPEN_TIMEOUT_MS": _env_or("CAPTURE_PROCESS_OPEN_TIMEOUT_MS", "8000"),
            "CAPTURE_PROCESS_READ_TIMEOUT_MS": _env_or("CAPTURE_PROCESS_READ_TIMEOUT_MS", "8000"),
            "CAPTURE_PROCESS_RESTART_MS": _env_or("CAPTURE_PROCESS_RESTART_MS", "1500"),
            "CAPTURE_JPEG_QUALITY": "60",
            "CAPTURE_PROCESS_OUTPUT_HEIGHT": _env_or("CAPTURE_PROCESS_OUTPUT_HEIGHT", "360"),
            "CAPTURE_PROCESS_WRITE_FPS": _env_or("CAPTURE_PROCESS_WRITE_FPS", "12"),
            "MAIN_CAPTURE_JPEG_QUALITY": "55",
            "MAIN_CAPTURE_PROCESS_OUTPUT_HEIGHT": "720",
            "MAIN_CAPTURE_PROCESS_WRITE_FPS": "8",
            "CAPTURE_PROCESS_MAX_RESTARTS": "0",
            "ENABLE_TRACKING": "true",
            "ENABLE_IDENTITY_BINDING": "false",
            "ENABLE_TARGET_BINDING": "false",
            "YOLO_MODEL_PATH": _env_or("YOLO_MODEL_PATH", "yolov8n.pt"),
            "YOLO_DEVICE": _env_or("YOLO_DEVICE", "cuda:0"),
            "YOLO_CONFIDENCE": _env_or("YOLO_CONFIDENCE", "0.35"),
            "YOLO_IMGSZ": _env_or("YOLO_IMGSZ", "640"),
            "YOLO_FALL_CONFIDENCE": _env_or("YOLO_FALL_CONFIDENCE", "0.25"),
            "YOLO_FALL_MODEL_PATH": _env_or("YOLO_FALL_MODEL_PATH", "models/yolo_fall_hint_v2_plus_b012_best.pt"),
            "DETECTION_INTERVAL_MS": _env_or("DETECTION_INTERVAL_MS", "200"),
            "ENABLE_POSE": "true" if args.pose_enabled else "false",
            "POSE_PROVIDER": args.pose_provider,
            "POSE_WORKER_FPS": _env_or("POSE_WORKER_FPS", "3"),
            "POSE_FPS": _env_or("POSE_FPS", "3"),
            "YOLO_POSE_MODEL_PATH": _env_or("YOLO_POSE_MODEL_PATH", "yolov8n-pose.pt"),
            "YOLO_POSE_CONFIDENCE": _env_or("YOLO_POSE_CONFIDENCE", "0.25"),
            "YOLO_POSE_IMGSZ": _env_or("YOLO_POSE_IMGSZ", "640"),
            "YOLO_POSE_DEVICE": _env_or("YOLO_POSE_DEVICE", "cuda:0"),
            "YOLO11_POSE_MODEL_PATH": args.yolo11_pose_model_path,
            "YOLO11_POSE_IMGSZ": _env_or("YOLO11_POSE_IMGSZ", "640"),
            "YOLO11_POSE_CONF": _env_or("YOLO11_POSE_CONF", "0.12"),
            "YOLO11_POSE_DEVICE": _env_or("YOLO11_POSE_DEVICE", "cuda:0"),
            "YOLO11_POSE_HALF": "true",
            "YOLO11_POSE_SMOOTHING": "true",
            "YOLO11_POSE_MAX_JUMP_RATIO": "0.18",
            "BRANCH4_POSE_CONF": "0.2" if args.pose_provider == "branch4_legacy" else _env_or("BRANCH4_POSE_CONF", "0.2"),
            "BRANCH4_POSE_IMGSZ": "640",
            "BRANCH4_POSE_HALF": "true",
            "BRANCH4_POSE_CROP_PADDING_RATIO": "0.18",
            "POSE_SKIP_WHEN_INFERENCE_BUSY": "true",
            "POSE_MAX_INFERENCE_MS": "1500",
            "POSE_FALLBACK_TO_DETECTION": "true",
            "POSE_FALLBACK_MIN_CONFIDENCE": "0.15",
            "POSE_CROP_PADDING_RATIO": "0.06",
            "POSE_FALLEN_CROP_PADDING_RATIO": "0.14",
            "POSE_MIN_SKELETON_CONFIDENCE": "0.35",
            "POSE_MIN_KEYPOINT_INSIDE_RATIO": "0.65",
            "POSE_MIN_FALLEN_KEYPOINT_INSIDE_RATIO": "0.60",
            "POSE_MIN_CANDIDATE_IOU": "0.25",
            "POSE_MIN_FALLEN_CANDIDATE_IOU": "0.15",
            "POSE_MAX_TRACKING_FRAME_DELTA": "2",
            "POSE_MAX_FRAME_AGE_MS": _env_or("POSE_MAX_FRAME_AGE_MS", "800"),
            "POSE_RESULT_TTL_MS": _env_or("POSE_RESULT_TTL_MS", "800"),
            "ENABLE_BEHAVIOR": "false",
            "ENABLE_TEMPORAL": "true",
            "TEMPORAL_TRACK_MODE": "all_tracks",
            "TEMPORAL_SEQUENCE_KEY_MODE": "spatial",
            "TEMPORAL_MODEL_PROVIDER": args.temporal_provider,
            "TEMPORAL_ONNX_MODEL_PATH": args.temporal_model_path,
            "TEMPORAL_FEATURE_SCHEMA_PATH": args.temporal_schema_path,
            "TEMPORAL_FALLBACK_TO_MOCK": _env_or("TEMPORAL_FALLBACK_TO_MOCK", "false"),
            "TEMPORAL_ONNX_PROVIDERS": "CUDAExecutionProvider,CPUExecutionProvider",
            "MAIN_SYSTEM_ALERT_ENABLED": "true" if args.enable_main_system_alerts else _env_or("MAIN_SYSTEM_ALERT_ENABLED", "false"),
            "MAIN_SYSTEM_BASE_URL": args.main_system_base_url,
            "MAIN_SYSTEM_ALERT_PATH": "/api/integrations/fall-detection/alerts",
            "MAIN_SYSTEM_HEALTH_PATH": "/api/integrations/fall-detection/health",
            "MAIN_SYSTEM_CONNECT_TIMEOUT_SEC": _env_or("MAIN_SYSTEM_CONNECT_TIMEOUT_SEC", "2"),
            "MAIN_SYSTEM_READ_TIMEOUT_SEC": _env_or("MAIN_SYSTEM_READ_TIMEOUT_SEC", "5"),
            "MAIN_SYSTEM_ALERT_COOLDOWN_SECONDS": str(args.alert_cooldown_seconds),
            "FALL_DETECTOR_CONFIRM_ENABLED": "true",
            "FALL_DETECTOR_CONFIRM_MIN_PROBABILITY": "0.15",
            "FALL_DETECTOR_CONFIRM_MIN_PERSON_CONFIDENCE": "0.2",
            "FALL_DETECTOR_CONFIRM_FRAMES": "2",
            "FALL_DETECTOR_CONFIRM_MS": "500",
            "FIELD_FALL_CANDIDATE_CONFIRM_FRAMES": "3",
            "FIELD_FALL_CANDIDATE_CONFIRM_MS": "650",
            "FALL_CONFIRM_FRAMES": "3",
            "FALL_STILL_MS": "800",
            "COOLDOWN_SECONDS": "2",
            "VISION_SERVICE_PUBLIC_BASE_URL": vision_public_base_url,
            "FALL_EVENT_SNAPSHOT_DIR": "logs/fall_events/snapshots",
            "TRACKING_WORKER_FPS": "12",
            "RESULT_PUBLISH_FPS": "10",
        }
    )

    print(f"[start] camera host={args.host} rtsp_port={args.rtsp_port}")
    print(f"[start] main={_mask(main_url)}")
    print(f"[start] analysis={_mask(analysis_url)}")
    print(f"[start] capture_backend={args.capture_backend}")
    print(f"[start] enable_pose={args.pose_enabled}")
    print(f"[start] pose_provider={args.pose_provider}")
    print(f"[start] temporal_provider={args.temporal_provider}")
    print(f"[start] main_system_alert_enabled={args.enable_main_system_alerts}")
    print(f"[start] main_system_base_url={args.main_system_base_url}")
    print(f"[start] vision_public_base_url={vision_public_base_url}")
    print(f"[start] YOLO_CONFIG_DIR={yolo_config_dir}")
    if env.get("TEMPORAL_FALLBACK_TO_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}:
        print("[warn] TEMPORAL_FALLBACK_TO_MOCK is enabled; temporal model failures may be masked by mock fallback.")

    if _should_run_pose_deployment_guard(args):
        guard_report = _write_pose_deployment_guard(
            env=env,
            evidence_package=Path(args.pose_evidence_package),
            output=Path(args.pose_deployment_guard_output),
        )
        guard_summary = guard_report.get("summary", {}) if isinstance(guard_report.get("summary"), dict) else {}
        if guard_summary.get("deployment_allowed") is not True:
            print("[blocked] pose deployment guard rejected this startup.", file=sys.stderr)
            print(json.dumps(guard_summary, ensure_ascii=False, indent=2), file=sys.stderr)
            print("[hint] use --skip-pose-deployment-guard only for local debugging, not production.", file=sys.stderr)
            return 3

    process = subprocess.Popen(
        [
            str(python_exe),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            args.api_host,
            "--port",
            str(args.api_port),
        ],
        cwd=str(ROOT),
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    if args.no_wait:
        print(f"[started] pid={process.pid}")
        return 0

    ready = _wait_http(f"http://{args.health_host}:{args.api_port}/healthz", 60)
    print(f"[ready] {ready} pid={process.pid}")
    print(f"[url] http://{args.health_host}:{args.api_port}/demo")
    lan_ip = _lan_ipv4()
    if lan_ip:
        print(f"[lan-url] http://{lan_ip}:{args.api_port}/demo")
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return 0


def _rtsp_url(username: str, password: str, host: str, port: int, path: str) -> str:
    return f"rtsp://{username}:{password}@{host}:{port}{path}"


def _mask(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url
    prefix, rest = url.split("://", 1)
    userinfo, after_password = rest.split("@", 1)
    user = userinfo.split(":", 1)[0]
    return f"{prefix}://{user}:***@{after_password}"


def _apply_discovered_devices(args: argparse.Namespace, argv: list[str]) -> None:
    explicit_camera = any(item in argv for item in ("--host", "--rtsp-url", "--main-rtsp-url", "--analysis-rtsp-url"))
    explicit_main = "--main-system-base-url" in argv
    if explicit_camera and explicit_main:
        return
    try:
        from app.core.config import Settings
        from app.services.device_connection_service import DeviceConnectionService
    except Exception as exc:
        print(f"[warn] auto discovery unavailable: {exc}")
        return
    settings = Settings()
    if args.password and args.password != settings.camera_rtsp_password:
        settings = replace(settings, camera_rtsp_password=args.password)
    if args.username and args.username != settings.camera_rtsp_username:
        settings = replace(settings, camera_rtsp_username=args.username)
    if args.rtsp_port and args.rtsp_port != settings.camera_rtsp_port:
        settings = replace(settings, camera_rtsp_port=args.rtsp_port)
    if args.analysis_path and args.analysis_path != settings.camera_rtsp_path:
        settings = replace(settings, camera_rtsp_path=args.analysis_path)
    try:
        result = DeviceConnectionService(settings=settings).startup_resolve()
    except Exception as exc:
        print(f"[warn] auto discovery failed: {exc}")
        return
    camera = result.status.get("camera") or {}
    main = result.status.get("main_system") or {}
    if not explicit_camera and camera.get("status") == "connected" and camera.get("ip"):
        args.host = camera["ip"]
        if camera.get("rtsp_port"):
            args.rtsp_port = int(camera["rtsp_port"])
        if result.settings.default_rtsp_url:
            args.rtsp_url = result.settings.default_rtsp_url
        print(f"[discover] camera={camera['ip']} rtsp_port={args.rtsp_port}")
    if not explicit_main and main.get("status") == "connected" and main.get("base_url"):
        args.main_system_base_url = main["base_url"]
        print(f"[discover] main_system_base_url={args.main_system_base_url}")


def _wait_http(url: str, timeout_sec: float) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.5) as response:
                return 200 <= response.status < 500
        except URLError:
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    return False


def _should_run_pose_deployment_guard(args: argparse.Namespace) -> bool:
    return bool(args.pose_enabled and args.enable_main_system_alerts and not args.skip_pose_deployment_guard)


def _write_pose_deployment_guard(*, env: dict[str, str], evidence_package: Path, output: Path) -> dict:
    from scripts.check_pose_deployment_guard import build_deployment_guard_report_from_env

    report = build_deployment_guard_report_from_env(
        env=env,
        env_path="start_current_camera_env",
        evidence_package_path=evidence_package,
        mode="production",
    )
    output_path = output if output.is_absolute() else ROOT / output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _lan_ipv4() -> str | None:
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
