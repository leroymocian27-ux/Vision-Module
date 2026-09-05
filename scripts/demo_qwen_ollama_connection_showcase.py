from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:4b"
LOG_DIR = ROOT / "logs" / "qwen_ollama_demo"


def main() -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser(
        description="Demo local Ollama/Qwen connection for Post-Fall V2 binary-first review."
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--check-only", action="store_true", help="Only check current connection status.")
    parser.add_argument("--ensure", action="store_true", help="Start Ollama if needed, then verify the model.")
    parser.add_argument("--pull-if-missing", action="store_true", help="Run 'ollama pull <model>' if the model is absent.")
    parser.add_argument("--chat", action="store_true", help="Open a short terminal chat after connection succeeds.")
    parser.add_argument("--wait-seconds", type=int, default=45)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    print_header(args.model, args.endpoint)

    if args.wait_seconds <= 0:
        parser.error("--wait-seconds must be positive")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    if args.check_only:
        ok = check_and_print(args.endpoint, args.model, args.timeout_seconds)
        return 0 if ok else 2

    if not args.ensure:
        print("[INFO] Use --check-only for a status check, or --ensure to start and verify Ollama/Qwen.")
        print("[INFO] Example: python scripts/demo_qwen_ollama_connection.py --ensure --model qwen3.5:4b")
        return 0

    print("[1/4] Checking local Ollama service...")
    if not ollama_ready(args.endpoint):
        print("[INFO] Ollama is not reachable; trying to start local 'ollama serve'.")
        start_ollama_serve()
    wait_for_ollama(args.endpoint, args.wait_seconds)

    print("[2/4] Checking requested Qwen model...")
    if not model_exists(args.endpoint, args.model):
        if not args.pull_if_missing:
            print("============================================")
            print("QWEN OLLAMA CONNECTION FAILED")
            print("=============================")
            print(f"Reason : model not found locally: {args.model}")
            print("Hint   : rerun with --pull-if-missing, or pull it manually with:")
            print(f"         ollama pull {args.model}")
            return 2
        pull_model(args.model)

    print("[3/4] Verifying binary-first review prompt...")
    result = chat_once(args.endpoint, args.model, args.timeout_seconds)

    print("[4/4] Writing demo connection report...")
    report_path = write_report(args.endpoint, args.model, result)
    print_success(args.endpoint, args.model, result, report_path)

    if args.chat:
        interactive_chat(args.endpoint, args.model, args.timeout_seconds)
    return 0


def print_header(model: str, endpoint: str) -> None:
    print("============================================")
    print("Post-Fall V2 Ollama/Qwen Connection Demo")
    print("Binary Model First -> Qwen Local Review")
    print("===============================")
    print(f"Model    : {model}")
    print(f"Endpoint : {endpoint}")
    print()


def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def check_and_print(endpoint: str, model: str, timeout_seconds: float) -> bool:
    print("[1/3] Checking Ollama endpoint...")
    if not ollama_ready(endpoint):
        print_failure("Ollama service is not reachable on local endpoint.", endpoint, model)
        return False
    print("[2/3] Checking Qwen model...")
    if not model_exists(endpoint, model):
        print_failure(f"Qwen model is not available locally: {model}", endpoint, model)
        return False
    print("[3/3] Sending a short local chat request...")
    try:
        result = chat_once(endpoint, model, timeout_seconds)
    except Exception as exc:
        print_failure(f"Local chat request failed: {exc}", endpoint, model)
        return False
    print_success(endpoint, model, result, None)
    return True


def print_failure(reason: str, endpoint: str, model: str) -> None:
    print()
    print("============================================")
    print("QWEN OLLAMA CONNECTION FAILED")
    print("=============================")
    print(f"Endpoint : {endpoint}")
    print(f"Model    : {model}")
    print(f"Reason   : {reason}")
    print("Status   : 二分类模型可先独立工作，千问本地复核暂不可用。")
    print("=============================")


def print_success(endpoint: str, model: str, result: dict[str, Any], report_path: Path | None) -> None:
    print()
    print("============================================")
    print("QWEN OLLAMA CONNECTION PASS")
    print("===========================")
    print(f"Endpoint : {endpoint}")
    print(f"Model    : {model}")
    print(f"Latency  : {result['latency_ms']} ms")
    print("Pipeline : EfficientNet-B0 二分类 -> 本地千问复核")
    print(f"Reply    : {result['reply']}")
    if report_path:
        print(f"Report   : {report_path}")
    print("===========================")


def ollama_ready(endpoint: str) -> bool:
    try:
        request_json(f"{endpoint.rstrip('/')}/api/version", timeout=2)
        return True
    except Exception:
        return False


def wait_for_ollama(endpoint: str, wait_seconds: int) -> None:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if ollama_ready(endpoint):
            print("[INFO] Ollama service is reachable.")
            return
        time.sleep(1)
    raise RuntimeError(f"Ollama did not become ready within {wait_seconds} seconds.")


def start_ollama_serve() -> None:
    executable = shutil.which("ollama")
    if not executable:
        raise RuntimeError("Cannot find 'ollama' in PATH. Please install Ollama or add it to PATH.")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout = (LOG_DIR / "ollama_serve.stdout.log").open("ab")
    stderr = (LOG_DIR / "ollama_serve.stderr.log").open("ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [executable, "serve"],
        cwd=str(ROOT),
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def model_exists(endpoint: str, model: str) -> bool:
    payload = request_json(f"{endpoint.rstrip('/')}/api/tags", timeout=5)
    for item in payload.get("models", []):
        name = item.get("name", "")
        if name == model or name.split(":", 1)[0] == model:
            return True
    return False


def pull_model(model: str) -> None:
    executable = shutil.which("ollama")
    if not executable:
        raise RuntimeError("Cannot find 'ollama' in PATH. Please install Ollama or add it to PATH.")
    print(f"[INFO] Pulling model with Ollama: {model}")
    completed = subprocess.run([executable, "pull", model], check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"'ollama pull {model}' failed with exit code {completed.returncode}")


def chat_once(endpoint: str, model: str, timeout_seconds: float) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是跌倒检测系统的本地复核模型。只基于二分类模型给出的结构化结果做简短中文复核，"
                "不替代 EfficientNet-B0 的第一层判定。"
            ),
        },
        {
            "role": "user",
            "content": (
                "二分类模型输出：FALL，fall_probability=0.91。"
                "请用一句中文说明你已连接，并说明当前流程是先二分类、再千问复核。"
            ),
        },
    ]
    started = time.perf_counter()
    response, reply = send_showcase_qwen_review(messages, endpoint, model, timeout_seconds)
    if not reply:
        raise RuntimeError("Ollama returned an empty message.")
    return {
        "reply": one_line(reply),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "done": bool(response.get("done", False)),
    }


def send_showcase_qwen_review(
    messages: list[dict[str, str]],
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = 30,
) -> tuple[dict[str, Any], str]:


    
    #
    endpoint = "http://127.0.0.1:11434"
    #
    model = "qwen3.5:4b"
    #
    response = post_json(f"{endpoint}/api/chat", {"model": model, "messages": messages, "stream": False}, timeout=30)
    #
    reply = response["message"]["content"]

    


    return response, str(reply).strip()


def interactive_chat(endpoint: str, model: str, timeout_seconds: float) -> None:
    print()
    print("[CHAT] 本地千问已可对话。输入 exit 结束。")
    while True:
        try:
            user_text = input("You> ").strip()
        except EOFError:
            return
        if user_text.lower() in {"exit", "quit", "q"}:
            return
        if not user_text:
            continue
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": user_text}],
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {"temperature": 0.2, "num_ctx": 2048, "num_predict": 256},
        }
        try:
            response = post_json(f"{endpoint.rstrip('/')}/api/chat", payload, timeout=timeout_seconds)
            print(f"Qwen> {one_line(str(response.get('message', {}).get('content', '')).strip())}")
        except Exception as exc:
            print(f"[ERROR] Chat failed: {exc}")


def request_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    if url.endswith("/api/chat"):
        payload = dict(payload)
        payload.setdefault("think", False)
        payload.setdefault("keep_alive", "10m")
        payload.setdefault("options", {"temperature": 0, "num_ctx": 1024, "num_predict": 120})
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def write_report(endpoint: str, model: str, result: dict[str, Any]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "PASS",
        "task": "POST_FALL_V2_QWEN_OLLAMA_CONNECTION_DEMO",
        "endpoint": endpoint,
        "model": model,
        "pipeline": "EfficientNet-B0 binary classification first, local Qwen review second",
        "latency_ms": result["latency_ms"],
        "reply": result["reply"],
        "external_endpoint": "NOT_USED",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = LOG_DIR / "qwen_ollama_connection_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def one_line(text: str) -> str:
    return " ".join(text.split())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted by user.", file=sys.stderr)
        raise SystemExit(130)
