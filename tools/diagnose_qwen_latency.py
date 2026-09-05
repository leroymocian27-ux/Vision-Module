from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import random
import statistics
import string
import subprocess
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
import requests

from app.events.qwen_keyframe import QwenKeyframeAnalyzer, _ollama_post_fall_json_schema


OLLAMA_NS_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)
GPU_QUERY_FIELDS = (
    "timestamp",
    "utilization.gpu",
    "utilization.memory",
    "memory.used",
    "power.draw",
    "temperature.gpu",
    "pstate",
    "clocks.sm",
    "clocks.mem",
)


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def median(values: Iterable[float | int | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return statistics.median(clean) if clean else None


def percentile_summary(values: Iterable[float | int | None]) -> dict[str, float | None]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"p50": None, "min": None, "max": None}
    return {"p50": statistics.median(clean), "min": min(clean), "max": max(clean)}


def number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().split()[0].replace("%", "")
    if text in {"", "N/A", "[N/A]", "Not", "Supported"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def safe_run(command: list[str], *, timeout: int = 60) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        return completed.returncode, output.strip()
    except Exception as exc:
        return -1, f"COMMAND FAILED: {exc}"


class GPUSampler:
    def __init__(self, output_path: Path, interval_seconds: float = 1.0) -> None:
        self.output_path = output_path
        self.interval_seconds = max(0.5, float(interval_seconds))
        self.samples: list[dict[str, Any]] = []
        self._active_case = "idle"
        self._active_run = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="qwen-diagnostic-gpu-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.write()

    def set_active(self, case: str, run: int) -> None:
        with self._lock:
            self._active_case = case
            self._active_run = run

    def clear_active(self) -> None:
        self.set_active("idle", 0)

    def write(self) -> None:
        fields = [
            "sampled_at",
            "gpu_timestamp",
            "case",
            "run",
            "gpu_util_percent",
            "memory_util_percent",
            "memory_used_mb",
            "power_w",
            "temperature_c",
            "pstate",
            "clock_sm_mhz",
            "clock_mem_mhz",
            "error",
        ]
        with self.output_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(self.samples)

    def _loop(self) -> None:
        query = ",".join(GPU_QUERY_FIELDS)
        while not self._stop.is_set():
            sampled_at = iso_now()
            code, output = safe_run(
                ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                timeout=10,
            )
            with self._lock:
                case = self._active_case
                run = self._active_run
            row: dict[str, Any] = {
                "sampled_at": sampled_at,
                "gpu_timestamp": "",
                "case": case,
                "run": run,
                "gpu_util_percent": None,
                "memory_util_percent": None,
                "memory_used_mb": None,
                "power_w": None,
                "temperature_c": None,
                "pstate": "",
                "clock_sm_mhz": None,
                "clock_mem_mhz": None,
                "error": "",
            }
            if code == 0 and output:
                parsed = next(csv.reader([output.splitlines()[0]]), [])
                if len(parsed) >= len(GPU_QUERY_FIELDS):
                    row.update(
                        {
                            "gpu_timestamp": parsed[0].strip(),
                            "gpu_util_percent": number(parsed[1]),
                            "memory_util_percent": number(parsed[2]),
                            "memory_used_mb": number(parsed[3]),
                            "power_w": number(parsed[4]),
                            "temperature_c": number(parsed[5]),
                            "pstate": parsed[6].strip(),
                            "clock_sm_mhz": number(parsed[7]),
                            "clock_mem_mhz": number(parsed[8]),
                        }
                    )
                else:
                    row["error"] = f"unexpected nvidia-smi fields: {output}"
            else:
                row["error"] = output or f"nvidia-smi exit {code}"
            self.samples.append(row)
            self._stop.wait(self.interval_seconds)


class QwenLatencyDiagnostics:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.repo_root = Path(__file__).resolve().parents[1]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = self.repo_root / "diagnostics" / f"qwen_latency_{timestamp}"
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.raw_path = self.output_dir / "benchmark_raw.jsonl"
        self.results: list[dict[str, Any]] = []
        self.endpoint = args.endpoint.rstrip("/")
        self.model = args.model
        self.repeats = max(3, int(args.repeats))
        self.request_timeout = max(30.0, float(args.timeout))
        self.gpu = GPUSampler(self.output_dir / "gpu_samples.csv")
        self.source_event_dir: Path | None = None
        self.source_images: list[np.ndarray] = []
        self.alternate_images: list[np.ndarray] = []
        self.production_payload: dict[str, Any] | None = None
        self.production_schema = _ollama_post_fall_json_schema()
        self.random = random.Random(20260901)
        self.initial_model_context = self.loaded_model_context(self.model)
        self._last_production_guard_at = 0.0
        self.run_manifest: dict[str, Any] = {
            "started_at": iso_now(),
            "endpoint": self.endpoint,
            "model": self.model,
            "repeats": self.repeats,
            "request_timeout_seconds": self.request_timeout,
            "flash_attention_ab": "NOT RUN",
            "initial_model_context": self.initial_model_context,
        }

    def run_all(self) -> None:
        self.capture_environment()
        if not self.args.allow_live_contention and not self.production_is_quiescent():
            self.run_manifest["finished_at"] = iso_now()
            self.run_manifest["status"] = "BLOCKED_BY_RUNNING_PRODUCTION_SESSION"
            self.run_manifest["result_count"] = 0
            self._write_json(self.output_dir / "run_manifest.json", self.run_manifest)
            (self.output_dir / "PRECHECK_BLOCKED.md").write_text(
                "# Diagnostic precheck blocked\n\n"
                "The production detection session is still RUNNING or its Qwen queue is not idle.\n"
                "No benchmark request was sent. Stop the complete detection session normally with F8, "
                "wait for Qwen active_count and queue_depth to reach zero, then rerun this tool.\n",
                encoding="utf-8",
            )
            print("Precheck blocked: production session/Qwen queue is not quiescent", flush=True)
            return
        self.load_images()
        self.prepare_production_payload()
        self.gpu.start()
        try:
            self.warm_model(self.model)
            self.run_text_microbenchmarks()
            self.run_prompt_length_benchmarks()
            self.run_api_path_benchmarks()
            self.run_schema_benchmarks()
            self.run_vision_count_benchmarks()
            self.run_resolution_benchmarks()
            self.run_jpeg_benchmarks()
            self.run_montage_benchmarks()
            self.run_cache_benchmarks()
            self.run_streaming_benchmarks()
            if not self.args.skip_2b:
                self.run_2b_control()
        finally:
            self.gpu.clear_active()
            self.gpu.stop()
            if not self.args.skip_2b:
                try:
                    self.warm_model(
                        self.model,
                        record=False,
                        num_ctx=self.initial_model_context or self.args.num_ctx,
                    )
                except RuntimeError as exc:
                    self.run_manifest["model_restore_skipped"] = str(exc)
            self.run_manifest["restored_model_context"] = self.loaded_model_context(self.model)
            self.run_manifest["finished_at"] = iso_now()
            self.run_manifest["source_event_dir"] = str(self.source_event_dir) if self.source_event_dir else None
            self.run_manifest["result_count"] = len(self.results)
            self._write_json(self.output_dir / "run_manifest.json", self.run_manifest)
            self.write_summaries()

    def production_is_quiescent(self) -> bool:
        status_url = self.args.production_status_url
        try:
            response = requests.get(status_url, timeout=5)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self.run_manifest["production_precheck"] = {"status": "UNKNOWN", "error": str(exc)}
            return False
        state = str(payload.get("state") or "UNKNOWN").upper()
        components = payload.get("components") or {}
        qwen = components.get("qwen") or {}
        active_count = int(qwen.get("active_count") or 0)
        queue_depth = int(qwen.get("queue_depth") or 0)
        snapshot = {
            "status": "QUIESCENT" if state != "RUNNING" and active_count == 0 and queue_depth == 0 else "BUSY",
            "session_state": state,
            "session_id": payload.get("session_id"),
            "qwen_active_count": active_count,
            "qwen_queue_depth": queue_depth,
        }
        self.run_manifest["production_precheck"] = snapshot
        self._write_json(self.output_dir / "production_precheck.json", snapshot)
        return snapshot["status"] == "QUIESCENT"

    def ensure_production_still_quiescent(self) -> None:
        if self.args.allow_live_contention:
            return
        now = time.monotonic()
        if now - self._last_production_guard_at < 0.5:
            return
        self._last_production_guard_at = now
        try:
            response = requests.get(self.args.production_status_url, timeout=5)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"Production safety check failed during benchmark: {exc}") from exc
        state = str(payload.get("state") or "UNKNOWN").upper()
        qwen = ((payload.get("components") or {}).get("qwen") or {})
        active_count = int(qwen.get("active_count") or 0)
        queue_depth = int(qwen.get("queue_depth") or 0)
        if state == "RUNNING" or active_count > 0 or queue_depth > 0:
            snapshot = {
                "detected_at": iso_now(),
                "session_state": state,
                "session_id": payload.get("session_id"),
                "qwen_active_count": active_count,
                "qwen_queue_depth": queue_depth,
            }
            self._write_json(self.output_dir / "PRODUCTION_BECAME_BUSY.json", snapshot)
            raise RuntimeError(
                "Production session/Qwen queue became active during diagnostics; aborting before the next request"
            )

    @staticmethod
    def loaded_model_context(model: str) -> int | None:
        code, output = safe_run(["ollama", "ps"], timeout=30)
        if code != 0:
            return None
        lines = output.splitlines()
        header = next((line for line in lines if "CONTEXT" in line and "UNTIL" in line), None)
        row = next((line for line in lines if line.strip().startswith(model)), None)
        if header is None or row is None:
            return None
        start = header.find("CONTEXT")
        end = header.find("UNTIL", start)
        try:
            return int(row[start:end].strip())
        except (TypeError, ValueError):
            return None

    def capture_environment(self) -> None:
        commands = {
            "environment.txt": [
                (["ollama", "--version"], "ollama --version"),
                (["powershell", "-NoProfile", "-Command", "$PSVersionTable; Get-ComputerInfo | Select-Object OsName,OsVersion,CsProcessors,CsTotalPhysicalMemory"], "Windows / processor"),
            ],
            "ollama_models.txt": [
                (["ollama", "list"], "ollama list"),
                (["ollama", "show", self.model], f"ollama show {self.model}"),
            ],
            "ollama_ps.txt": [(["ollama", "ps"], "ollama ps")],
            "nvidia_smi.txt": [
                (["nvidia-smi"], "nvidia-smi"),
                (["nvidia-smi", "-L"], "nvidia-smi -L"),
                (["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv"], "GPU processes"),
            ],
            "nvidia_smi_full.txt": [(["nvidia-smi", "-q"], "nvidia-smi -q")],
            "ollama_env.txt": [
                (["powershell", "-NoProfile", "-Command", "Get-ChildItem Env:OLLAMA* | Format-List"], "OLLAMA environment"),
            ],
            "power_plan.txt": [(["powercfg", "/getactivescheme"], "active power plan")],
        }
        for filename, entries in commands.items():
            blocks = []
            for command, title in entries:
                code, output = safe_run(command, timeout=120)
                blocks.append(f"===== {title} (exit={code}) =====\n{output}\n")
            (self.output_dir / filename).write_text("\n".join(blocks), encoding="utf-8")
        self.capture_ollama_log()

    def capture_ollama_log(self) -> None:
        log_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"
        patterns = (
            "cuda", "vulkan", "library", "runner", "gpu", "offload", "flash", "memory", "vram",
            "kv", "vision", "image", "error", "warning", "fallback", "qwen3.5", "llama-server",
        )
        lines: list[str] = []
        if log_path.exists():
            for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if any(pattern in line.lower() for pattern in patterns):
                    lines.append(line)
            lines = lines[-4000:]
        else:
            lines = [f"server.log not found at {log_path}"]
        (self.output_dir / "ollama_log_extract.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def load_images(self) -> None:
        root = Path(self.args.event_root)
        candidates = []
        if self.args.image_dir:
            candidates.append(Path(self.args.image_dir))
        full_root = root / "binary-classification" / "full"
        if full_root.exists():
            candidates.extend(sorted((path for path in full_root.iterdir() if path.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True))
        usable: list[tuple[Path, list[np.ndarray]]] = []
        for directory in candidates:
            frames = []
            for path in sorted(directory.glob("*.jpg"))[:3]:
                try:
                    frame = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
                except OSError:
                    frame = None
                if frame is not None:
                    frames.append(frame)
            if len(frames) >= 3:
                usable.append((directory, frames))
            if len(usable) >= 2:
                break
        if not usable:
            raise RuntimeError("No event directory with at least three JPEG keyframes was found")
        self.source_event_dir, self.source_images = usable[0]
        self.alternate_images = usable[1][1] if len(usable) > 1 else []
        manifest = {
            "source_event_dir": str(self.source_event_dir),
            "source_shapes": [list(frame.shape) for frame in self.source_images],
            "alternate_available": bool(self.alternate_images),
        }
        self._write_json(self.output_dir / "image_source_manifest.json", manifest)

    def prepare_production_payload(self) -> None:
        analyzer = QwenKeyframeAnalyzer(
            endpoint_url=f"{self.endpoint}/api/chat",
            model_name=self.model,
            timeout_seconds=self.request_timeout,
            num_ctx=self.args.num_ctx,
            max_output_tokens=96,
            temperature=0.0,
        )
        payload = analyzer.build_post_fall_payload(images=[], keyframe_status="ready")
        payload.pop("format", None)
        payload["options"] = {"num_ctx": self.args.num_ctx, "num_predict": 1, "temperature": 0}
        self.production_payload = payload
        sanitized = json.loads(json.dumps(payload))
        for message in sanitized.get("messages", []):
            message.pop("images", None)
        self._write_json(self.output_dir / "production_prompt_snapshot.json", sanitized)
        self._write_json(self.output_dir / "production_schema_snapshot.json", self.production_schema)

    def warm_model(self, model: str, *, record: bool = True, num_ctx: int | None = None) -> None:
        payload = self.chat_payload(
            prompt=f"{self.fresh_nonce('warm')}只回答A",
            model=model,
            num_predict=1,
        )
        if num_ctx is not None:
            payload["options"]["num_ctx"] = int(num_ctx)
        self.request("WARMUP_" + model.replace(":", "_"), 1, payload, fresh_input=True, include_in_summary=False, record=record)

    def run_text_microbenchmarks(self) -> None:
        for tokens in (1, 8, 32, 64):
            case = f"T{tokens}_text_decode"
            for run in range(1, self.repeats + 1):
                prompt = self.fresh_nonce(case) + "连续输出英文字母A，不要空格、标点或解释，直到系统停止。"
                payload = self.chat_payload(prompt=prompt, num_predict=tokens)
                self.request(case, run, payload, fresh_input=True)

    def run_prompt_length_benchmarks(self) -> None:
        targets = {"P50": 50, "P100": 100, "P250": 250, "P500": 500}
        phrase = "仅分析给定文字并输出字母A，不要解释。"
        for case, target in targets.items():
            for run in range(1, self.repeats + 1):
                prompt = self.fresh_nonce(case) + (phrase * max(1, target // len(phrase))) + "只输出A。"
                self.request(case, run, self.chat_payload(prompt=prompt, num_predict=1), fresh_input=True)
        if self.production_payload is not None:
            for run in range(1, self.repeats + 1):
                payload = json.loads(json.dumps(self.production_payload))
                payload["messages"][-1]["content"] = self.fresh_nonce("Pcurrent") + payload["messages"][-1]["content"]
                self.request("Pcurrent_production_text", run, payload, fresh_input=True)

    def run_api_path_benchmarks(self) -> None:
        for run in range(1, self.repeats + 1):
            prompt = self.fresh_nonce("G_generate") + "只回答A"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": -1,
                "options": self.options(1),
            }
            self.request("G1_api_generate", run, payload, api_path="/api/generate", fresh_input=True)
            prompt = self.fresh_nonce("G_chat") + "只回答A"
            self.request("G2_api_chat", run, self.chat_payload(prompt=prompt, num_predict=1), fresh_input=True)

    def run_schema_benchmarks(self) -> None:
        schemas: list[tuple[str, Any, str]] = [
            ("S0_plain", None, "只输出phone，不要解释。"),
            ("S1_json_no_format", None, '只输出JSON：{"e":"phone"}，不要解释。'),
            ("S2_format_json", "json", '输出JSON，字段e固定为phone。'),
            ("S3_schema_e", schema_object({"e": {"type": "string", "const": "phone"}}, ["e"]), "识别结果固定为phone。"),
            ("S4_schema_ec", schema_object({"e": {"type": "string", "const": "phone"}, "c": {"type": "number"}}, ["e", "c"]), "输出对象类别phone和置信度。"),
            ("S5_schema_ect", schema_object({"e": {"type": "string", "const": "phone"}, "c": {"type": "number"}, "t": {"type": "string"}}, ["e", "c", "t"]), "输出对象类别、置信度和简短文本。"),
            ("S6_compact_6", compact_six_field_schema(), "输出精简结构化复核结果，判断为非跌倒。"),
            ("S7_production_13", self.production_schema, "输出完整结构化复核结果，判断为非跌倒。"),
        ]
        for case, output_format, instruction in schemas:
            for run in range(1, self.repeats + 1):
                payload = self.chat_payload(
                    prompt=self.fresh_nonce(case) + instruction,
                    num_predict=96,
                    output_format=output_format,
                )
                self.request(case, run, payload, fresh_input=True)

    def run_vision_count_benchmarks(self) -> None:
        encoded = [self.encode_image(frame, max_edge=384, quality=86)[0] for frame in self.source_images]
        for count in range(4):
            case = f"V{count}_{count}image_384"
            for run in range(1, self.repeats + 1):
                payload = self.chat_payload(
                    prompt=self.fresh_nonce(case) + "只输出A",
                    num_predict=1,
                    images=encoded[:count],
                )
                self.request(case, run, payload, fresh_input=True, metadata={"image_count": count, "max_edge": 384})

    def run_resolution_benchmarks(self) -> None:
        for edge in (512, 384, 320, 256, 224, 192):
            image_bytes, encode_ms, shape = self.encode_image(self.source_images[0], max_edge=edge, quality=86)
            case = f"R{edge}_one_image"
            for run in range(1, self.repeats + 1):
                payload = self.chat_payload(
                    prompt=self.fresh_nonce(case) + "只输出A",
                    num_predict=1,
                    images=[image_bytes],
                )
                self.request(
                    case,
                    run,
                    payload,
                    fresh_input=True,
                    metadata={"max_edge": edge, "actual_width": shape[1], "actual_height": shape[0], "jpeg_bytes": len(image_bytes), "client_encode_ms": encode_ms},
                )

    def run_jpeg_benchmarks(self) -> None:
        for quality in (95, 86, 70, 50):
            image_bytes, encode_ms, shape = self.encode_image(self.source_images[0], max_edge=256, quality=quality)
            case = f"J{quality}_quality"
            for run in range(1, self.repeats + 1):
                payload = self.chat_payload(
                    prompt=self.fresh_nonce(case) + "只输出A",
                    num_predict=1,
                    images=[image_bytes],
                )
                self.request(
                    case,
                    run,
                    payload,
                    fresh_input=True,
                    metadata={
                        "quality": quality,
                        "actual_width": shape[1],
                        "actual_height": shape[0],
                        "jpeg_bytes": len(image_bytes),
                        "base64_bytes": len(base64.b64encode(image_bytes)),
                        "client_encode_ms": encode_ms,
                    },
                )

    def run_montage_benchmarks(self) -> None:
        resized = [resize_frame(frame, 256) for frame in self.source_images]
        variants = {
            "M1_three_independent": [self.encode_frame(frame, quality=86)[0] for frame in resized],
            "M2_three_panel": [self.encode_frame(np.hstack(resized), quality=86)[0]],
            "M3_early_trigger_panel": [self.encode_frame(np.hstack([resized[0], resized[2]]), quality=86)[0]],
            "M4_trigger_single": [self.encode_frame(resized[2], quality=86)[0]],
        }
        for case, images in variants.items():
            for run in range(1, self.repeats + 1):
                payload = self.chat_payload(
                    prompt=self.fresh_nonce(case) + "按从左到右时间顺序观察，只输出A",
                    num_predict=1,
                    images=images,
                )
                self.request(case, run, payload, fresh_input=True, metadata={"image_count": len(images), "total_jpeg_bytes": sum(map(len, images))})

    def run_cache_benchmarks(self) -> None:
        base_images = [self.encode_image(frame, max_edge=256, quality=86)[0] for frame in self.source_images]
        fixed_prompt = "缓存诊断固定输入：只输出A"
        fixed_payload = self.chat_payload(prompt=fixed_prompt, num_predict=1, images=base_images)
        for run in range(1, 6):
            self.request("C1_exact_repeat", run, fixed_payload, fresh_input=False, cache_experiment=True)
        for run in range(1, 6):
            payload = self.chat_payload(prompt=f"request_id={run};{fixed_prompt}", num_predict=1, images=base_images)
            self.request("C2_prompt_nonce", run, payload, fresh_input=True, cache_experiment=True)
        for run in range(1, 6):
            optimize = run % 2
            images = [self.encode_frame(resize_frame(frame, 256), quality=86, optimize=optimize)[0] for frame in self.source_images]
            payload = self.chat_payload(prompt=fixed_prompt, num_predict=1, images=images)
            self.request("C3_reencoded_images", run, payload, fresh_input=False, cache_experiment=True, metadata={"jpeg_optimize": optimize})
        for run in range(1, 6):
            images = []
            for index, frame in enumerate(self.source_images):
                changed = resize_frame(frame, 256).copy()
                changed[0, 0, index % 3] = (int(changed[0, 0, index % 3]) + run) % 256
                images.append(self.encode_frame(changed, quality=86)[0])
            payload = self.chat_payload(prompt=fixed_prompt, num_predict=1, images=images)
            self.request("C4_one_pixel_change", run, payload, fresh_input=True, cache_experiment=True)
        if self.alternate_images:
            images = [self.encode_image(frame, max_edge=256, quality=86)[0] for frame in self.alternate_images]
            for run in range(1, 6):
                payload = self.chat_payload(prompt=f"{self.fresh_nonce('C5')}{fixed_prompt}", num_predict=1, images=images)
                self.request("C5_new_event_frames", run, payload, fresh_input=True, cache_experiment=True)
        else:
            self.record_not_run("C5_new_event_frames", "No second event with three JPEG keyframes was available")

    def run_streaming_benchmarks(self) -> None:
        for run in range(1, self.repeats + 1):
            payload = self.chat_payload(
                prompt=self.fresh_nonce("TTFT") + "连续输出英文字母A，不要空格或解释，直到系统停止。",
                num_predict=32,
            )
            payload["stream"] = True
            self.streaming_request("TTFT_streaming", run, payload)

    def run_2b_control(self) -> None:
        code, models = safe_run(["ollama", "list"], timeout=30)
        if code != 0 or "qwen3.5:2b" not in models:
            self.record_not_run("CONTROL_2B", "qwen3.5:2b is not installed")
            return
        model = "qwen3.5:2b"
        self.warm_model(model)
        encoded = [self.encode_image(frame, max_edge=384, quality=86)[0] for frame in self.source_images]
        cases = (("C2B_T1", 1, 0), ("C2B_T32", 32, 0), ("C2B_V1", 1, 1), ("C2B_V3", 1, 3))
        for case, num_predict, image_count in cases:
            for run in range(1, self.repeats + 1):
                prompt = self.fresh_nonce(case) + ("连续输出字母A直到系统停止。" if num_predict > 1 else "只输出A")
                payload = self.chat_payload(prompt=prompt, model=model, num_predict=num_predict, images=encoded[:image_count])
                self.request(case, run, payload, fresh_input=True, metadata={"model": model, "image_count": image_count})

    def request(
        self,
        case: str,
        run: int,
        payload: dict[str, Any],
        *,
        api_path: str = "/api/chat",
        fresh_input: bool,
        cache_experiment: bool = False,
        metadata: dict[str, Any] | None = None,
        include_in_summary: bool = True,
        record: bool = True,
    ) -> dict[str, Any]:
        self.ensure_production_still_quiescent()
        self.gpu.set_active(case, run)
        started_at = iso_now()
        started_perf = time.perf_counter()
        error = None
        status_code = None
        response_payload: dict[str, Any] = {}
        try:
            response = requests.post(f"{self.endpoint}{api_path}", json=payload, timeout=self.request_timeout)
            status_code = response.status_code
            response.raise_for_status()
            response_payload = response.json()
        except Exception as exc:
            error = str(exc)
        ended_perf = time.perf_counter()
        ended_at = iso_now()
        self.gpu.clear_active()
        result = self.make_result(
            case=case,
            run=run,
            api_path=api_path,
            payload=payload,
            response=response_payload,
            started_at=started_at,
            ended_at=ended_at,
            roundtrip_ms=(ended_perf - started_perf) * 1000,
            status_code=status_code,
            error=error,
            fresh_input=fresh_input,
            cache_experiment=cache_experiment,
            metadata=metadata,
            include_in_summary=include_in_summary,
        )
        if record:
            self.append_result(result)
        print(f"[{ended_at}] {case} run={run} status={status_code} total_ms={result.get('total_ms')} error={error}", flush=True)
        return result

    def streaming_request(self, case: str, run: int, payload: dict[str, Any]) -> None:
        self.ensure_production_still_quiescent()
        self.gpu.set_active(case, run)
        started_at = iso_now()
        started_perf = time.perf_counter()
        first_token_ms = None
        final_payload: dict[str, Any] = {}
        content_parts = []
        thinking_present = False
        error = None
        status_code = None
        try:
            with requests.post(f"{self.endpoint}/api/chat", json=payload, timeout=self.request_timeout, stream=True) as response:
                status_code = response.status_code
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    chunk = json.loads(line)
                    message = chunk.get("message") or {}
                    content = message.get("content") or ""
                    if message.get("thinking"):
                        thinking_present = True
                    if content:
                        if first_token_ms is None:
                            first_token_ms = (time.perf_counter() - started_perf) * 1000
                        content_parts.append(content)
                    if chunk.get("done"):
                        final_payload = chunk
        except Exception as exc:
            error = str(exc)
        ended_perf = time.perf_counter()
        ended_at = iso_now()
        self.gpu.clear_active()
        result = self.make_result(
            case=case,
            run=run,
            api_path="/api/chat",
            payload=payload,
            response=final_payload,
            started_at=started_at,
            ended_at=ended_at,
            roundtrip_ms=(ended_perf - started_perf) * 1000,
            status_code=status_code,
            error=error,
            fresh_input=True,
            cache_experiment=False,
            metadata={
                "stream": True,
                "ttft_ms": first_token_ms,
                "decode_after_first_token_ms": ((ended_perf - started_perf) * 1000 - first_token_ms) if first_token_ms is not None else None,
                "thinking_present": thinking_present,
                "content_length": len("".join(content_parts)),
            },
            include_in_summary=True,
        )
        self.append_result(result)
        print(f"[{ended_at}] {case} run={run} ttft_ms={first_token_ms} total_ms={result.get('total_ms')}", flush=True)

    def make_result(
        self,
        *,
        case: str,
        run: int,
        api_path: str,
        payload: dict[str, Any],
        response: dict[str, Any],
        started_at: str,
        ended_at: str,
        roundtrip_ms: float,
        status_code: int | None,
        error: str | None,
        fresh_input: bool,
        cache_experiment: bool,
        metadata: dict[str, Any] | None,
        include_in_summary: bool,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for field in OLLAMA_NS_FIELDS:
            raw = response.get(field)
            metrics[field + "_ns"] = raw
            metrics[field.replace("_duration", "") + "_ms"] = (float(raw) / 1_000_000) if raw is not None else None
        prompt_count = response.get("prompt_eval_count")
        eval_count = response.get("eval_count")
        prompt_ms = metrics.get("prompt_eval_ms")
        eval_ms = metrics.get("eval_ms")
        accounted_ms = sum(float(value or 0) for value in (metrics.get("load_ms"), prompt_ms, eval_ms))
        queue_or_other_ms = max(0.0, float(metrics.get("total_ms") or 0) - accounted_ms)
        image_count = sum(len(message.get("images") or []) for message in payload.get("messages", []) if isinstance(message, dict))
        message = response.get("message") or {}
        result = {
            "case": case,
            "run": run,
            "api_path": api_path,
            "model": payload.get("model"),
            "started_at": started_at,
            "ended_at": ended_at,
            "status_code": status_code,
            "error": error,
            "roundtrip_ms": round(roundtrip_ms, 3),
            **metrics,
            "queue_or_other_ms": queue_or_other_ms,
            "resource_contention_suspected": queue_or_other_ms >= 1000,
            "prompt_eval_count": prompt_count,
            "eval_count": eval_count,
            "prompt_tokens_per_second": (float(prompt_count) / (prompt_ms / 1000)) if prompt_count and prompt_ms else None,
            "eval_tokens_per_second": (float(eval_count) / (eval_ms / 1000)) if eval_count and eval_ms else None,
            "cold_load": bool(metrics.get("load_ms") and metrics["load_ms"] >= 1000),
            "fresh_input": fresh_input,
            "cache_experiment": cache_experiment,
            "cache_hit_suspected": False,
            "include_in_summary": include_in_summary,
            "image_count": image_count,
            "format_mode": format_mode(payload.get("format")),
            "num_predict": (payload.get("options") or {}).get("num_predict"),
            "num_ctx": (payload.get("options") or {}).get("num_ctx"),
            "think": payload.get("think"),
            "thinking_present": bool(message.get("thinking")),
            "response_content_length": len(str(message.get("content") or response.get("response") or "")),
            "response_excerpt": str(message.get("content") or response.get("response") or "")[:300],
            "metadata": metadata or {},
        }
        return result

    def append_result(self, result: dict[str, Any]) -> None:
        self.results.append(result)
        with self.raw_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    def record_not_run(self, case: str, reason: str) -> None:
        result = {
            "case": case,
            "run": 0,
            "error": None,
            "status": "NOT RUN",
            "reason": reason,
            "include_in_summary": False,
        }
        self.append_result(result)

    def chat_payload(
        self,
        *,
        prompt: str,
        num_predict: int,
        model: str | None = None,
        images: list[bytes] | None = None,
        output_format: Any = None,
    ) -> dict[str, Any]:
        user: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            user["images"] = [base64.b64encode(image).decode("ascii") for image in images]
        payload: dict[str, Any] = {
            "model": model or self.model,
            "stream": False,
            "think": False,
            "keep_alive": -1,
            "options": self.options(num_predict),
            "messages": [user],
        }
        if output_format is not None:
            payload["format"] = output_format
        return payload

    def options(self, num_predict: int) -> dict[str, Any]:
        return {"num_ctx": self.args.num_ctx, "num_predict": int(num_predict), "temperature": 0}

    def fresh_nonce(self, case: str) -> str:
        value = "".join(self.random.choice(string.ascii_uppercase + string.digits) for _ in range(12))
        return f"样本{value}；"

    @staticmethod
    def encode_image(frame: np.ndarray, *, max_edge: int, quality: int) -> tuple[bytes, float, tuple[int, ...]]:
        resized = resize_frame(frame, max_edge)
        encoded, encode_ms = QwenLatencyDiagnostics.encode_frame(resized, quality=quality)
        return encoded, encode_ms, resized.shape

    @staticmethod
    def encode_frame(frame: np.ndarray, *, quality: int, optimize: int | None = None) -> tuple[bytes, float]:
        options = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
        if optimize is not None:
            options.extend([int(cv2.IMWRITE_JPEG_OPTIMIZE), int(optimize)])
        started = time.perf_counter()
        ok, encoded = cv2.imencode(".jpg", frame, options)
        encode_ms = (time.perf_counter() - started) * 1000
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return encoded.tobytes(), encode_ms

    def write_summaries(self) -> None:
        self.mark_cache_hits()
        self.rewrite_raw()
        gpu_summary = summarize_gpu(self.gpu.samples)
        self._write_json(self.output_dir / "gpu_summary.json", gpu_summary)
        summaries = summarize_results(self.results, gpu_summary)
        write_summary_csv(self.output_dir / "benchmark_summary.csv", summaries)
        self.write_cache_report(summaries)
        self.write_diagnostic_report(summaries, gpu_summary)

    def mark_cache_hits(self) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for result in self.results:
            if result.get("cache_experiment") and result.get("total_ms") is not None:
                grouped[result["case"]].append(result)
        for rows in grouped.values():
            baseline = max((row.get("prompt_eval_ms") or 0) for row in rows)
            total_baseline = max((row.get("total_ms") or 0) for row in rows)
            for row in rows:
                prompt_fast = baseline > 0 and (row.get("prompt_eval_ms") or baseline) < baseline * 0.25
                total_fast = total_baseline > 0 and (row.get("total_ms") or total_baseline) < total_baseline * 0.35
                row["cache_hit_suspected"] = bool(prompt_fast or total_fast)

    def rewrite_raw(self) -> None:
        with self.raw_path.open("w", encoding="utf-8") as handle:
            for result in self.results:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    def write_cache_report(self, summaries: list[dict[str, Any]]) -> None:
        lines = ["# Cache Behavior", "", "缓存实验与核心基准分开统计；疑似缓存命中不会进入真实事件延迟归因。", ""]
        for case in ("C1_exact_repeat", "C2_prompt_nonce", "C3_reencoded_images", "C4_one_pixel_change", "C5_new_event_frames"):
            rows = [row for row in self.results if row.get("case") == case]
            if not rows:
                lines.extend([f"## {case}", "", "NOT RUN", ""])
                continue
            lines.extend([f"## {case}", "", "| Run | Prompt eval ms | Total ms | Cache hit suspected |", "|---:|---:|---:|:---:|"])
            for row in rows:
                lines.append(f"| {row.get('run')} | {fmt(row.get('prompt_eval_ms'))} | {fmt(row.get('total_ms'))} | {row.get('cache_hit_suspected', False)} |")
            lines.append("")
        lines.extend([
            "## Interpretation rule",
            "",
            "- 完全相同输入显著加速：疑似完整前缀或图像提示缓存。",
            "- Prompt 起始位置变化后恢复正常：文本前缀缓存被破坏。",
            "- JPEG bytes 变化后恢复正常：缓存包含图像输入字节或视觉前缀。",
            "- 改一个像素后恢复正常：缓存对图像内容敏感。",
        ])
        (self.output_dir / "cache_behavior.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_diagnostic_report(self, summaries: list[dict[str, Any]], gpu_summary: dict[str, Any]) -> None:
        by_case = {row["case"]: row for row in summaries}
        lines = [
            "# Qwen 3.5 Ollama Latency Diagnostic Report",
            "",
            f"生成时间：{iso_now()}",
            f"模型：`{self.model}`",
            f"事件图片：`{self.source_event_dir}`",
            f"核心测试重复次数：{self.repeats}",
            "",
            "## A. 当前环境",
            "",
            "完整环境见 `environment.txt`、`ollama_models.txt`、`ollama_ps.txt`、`nvidia_smi*.txt`、`ollama_env.txt` 和 `power_plan.txt`。",
            "Flash Attention A/B：**NOT RUN**。本轮不重启或修改正在运行的 Ollama 服务。",
            "",
            "## B. 基础性能",
            "",
        ]
        lines.extend(summary_table(summaries, lambda case: case.startswith("T") or case.startswith("P") or case.startswith("G")))
        lines.extend(["", "## C. Structured Output", ""])
        lines.extend(summary_table(summaries, lambda case: case.startswith("S")))
        lines.extend(["", "## D. Vision", ""])
        lines.extend(summary_table(summaries, lambda case: case.startswith(("V", "R", "J", "M"))))
        lines.extend(["", "## E. Cache", "", "详见 `cache_behavior.md`。", ""])
        lines.extend(["## F. GPU 利用率", ""])
        lines.extend(gpu_table(gpu_summary))
        lines.extend(["", "## G. 4B vs 2B 控制组", ""])
        control_rows = summary_table(summaries, lambda case: case.startswith("C2B"))
        lines.extend(control_rows if control_rows else ["NOT RUN"])
        lines.extend(["", "## H. 原约 24 秒耗时归因", ""])
        t1 = metric(by_case, "T1_text_decode", "total_ms_p50")
        v0 = metric(by_case, "V0_0image_384", "prompt_eval_ms_p50")
        v1 = metric(by_case, "V1_1image_384", "prompt_eval_ms_p50")
        v2 = metric(by_case, "V2_2image_384", "prompt_eval_ms_p50")
        v3 = metric(by_case, "V3_3image_384", "prompt_eval_ms_p50")
        pcurrent = metric(by_case, "Pcurrent_production_text", "prompt_eval_ms_p50")
        vision1 = diff(v1, v0)
        vision2 = diff(v2, v1)
        vision3 = diff(v3, v2)
        lines.extend([
            "以下为隔离实验估算，各阶段可能在 Ollama 内部重叠，因此不能机械相加为一次请求的精确总时长。",
            "",
            "| 模块 | 估算耗时 |",
            "|---|---:|",
            f"| 固定/API短请求成本 | {fmt(t1)} ms |",
            f"| 当前生产文本 prefill | {fmt(pcurrent)} ms |",
            f"| Vision 第1张增量 | {fmt(vision1)} ms |",
            f"| Vision 第2张增量 | {fmt(vision2)} ms |",
            f"| Vision 第3张增量 | {fmt(vision3)} ms |",
            "| Structured decode | 见 S0-S7 的 eval ms 与 tok/s |",
            "",
            "## I. Root Causes",
            "",
        ])
        root_causes = derive_root_causes(by_case, gpu_summary)
        lines.extend(root_causes or ["现有成功样本不足，无法形成可靠归因。"])
        lines.extend(["", "## J. 下一步", ""])
        lines.extend(derive_next_steps(by_case, gpu_summary))
        lines.extend([
            "",
            "## 未运行项目",
            "",
            "- Flash Attention default/on/off：**NOT RUN**，因为需要重启或隔离 Ollama，可能干扰当前主系统。",
            "- 任何失败或缺少输入的测试均在 `benchmark_raw.jsonl` 中保留真实错误，不补造结果。",
            "",
            "## think=false 验证",
            "",
            "诊断请求显式发送 `think=false`。`benchmark_raw.jsonl` 同时记录 `thinking_present`；若所有成功记录均为 false，则没有观察到显式 thinking 字段。隐藏 token 无法仅靠 REST 响应证明，仍标记为 **UNKNOWN**。",
        ])
        (self.output_dir / "DIAGNOSTIC_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resize_frame(frame: np.ndarray, max_edge: int) -> np.ndarray:
    height, width = frame.shape[:2]
    if max(height, width) <= max_edge:
        return frame.copy()
    scale = max_edge / float(max(height, width))
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(frame, target, interpolation=cv2.INTER_AREA)


def schema_object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": properties}


def compact_six_field_schema() -> dict[str, Any]:
    return schema_object(
        {
            "e": {"type": "string", "enum": ["fall", "non_fall", "unclear"]},
            "s": {"type": "string"},
            "d": {"type": "string"},
            "f": {"type": "integer", "enum": [0, 1]},
            "c": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "t": {"type": "string"},
        },
        ["e", "s", "d", "f", "c", "t"],
    )


def format_mode(value: Any) -> str:
    if value is None:
        return "none"
    if value == "json":
        return "json"
    if isinstance(value, dict):
        return f"schema_{len(value.get('properties') or {})}_fields"
    return str(value)


def summarize_gpu(samples: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        if sample.get("case") != "idle":
            grouped[str(sample.get("case"))].append(sample)
    result: dict[str, Any] = {}
    for case, rows in grouped.items():
        pstates: dict[str, int] = defaultdict(int)
        for row in rows:
            if row.get("pstate"):
                pstates[str(row["pstate"])] += 1
        result[case] = {
            "samples": len(rows),
            "gpu_util_avg": mean(row.get("gpu_util_percent") for row in rows),
            "gpu_util_peak": max_clean(row.get("gpu_util_percent") for row in rows),
            "memory_util_avg": mean(row.get("memory_util_percent") for row in rows),
            "memory_used_peak_mb": max_clean(row.get("memory_used_mb") for row in rows),
            "power_avg_w": mean(row.get("power_w") for row in rows),
            "power_peak_w": max_clean(row.get("power_w") for row in rows),
            "clock_sm_avg_mhz": mean(row.get("clock_sm_mhz") for row in rows),
            "clock_mem_avg_mhz": mean(row.get("clock_mem_mhz") for row in rows),
            "temperature_peak_c": max_clean(row.get("temperature_c") for row in rows),
            "pstate_distribution": dict(pstates),
        }
    return result


def summarize_results(results: list[dict[str, Any]], gpu_summary: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        if result.get("include_in_summary") and result.get("error") is None and result.get("total_ms") is not None:
            if result.get("cache_hit_suspected") and not result.get("cache_experiment"):
                continue
            grouped[result["case"]].append(result)
    summaries = []
    metrics = ("roundtrip_ms", "total_ms", "load_ms", "prompt_eval_ms", "eval_ms", "queue_or_other_ms", "prompt_eval_count", "eval_count", "prompt_tokens_per_second", "eval_tokens_per_second")
    for case in sorted(grouped):
        rows = grouped[case]
        summary: dict[str, Any] = {
            "case": case,
            "runs": len(rows),
            "model": rows[0].get("model"),
            "api_path": rows[0].get("api_path"),
            "image_count": rows[0].get("image_count"),
            "format_mode": rows[0].get("format_mode"),
            "num_predict": rows[0].get("num_predict"),
        }
        for metric_name in metrics:
            values = percentile_summary(row.get(metric_name) for row in rows)
            for label, value in values.items():
                summary[f"{metric_name}_{label}"] = value
        summary.update(gpu_summary.get(case, {}))
        summaries.append(summary)
    return summaries


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def mean(values: Iterable[float | int | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return statistics.mean(clean) if clean else None


def max_clean(values: Iterable[float | int | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return max(clean) if clean else None


def summary_table(rows: list[dict[str, Any]], predicate) -> list[str]:
    selected = [row for row in rows if predicate(row["case"])]
    if not selected:
        return []
    lines = [
        "| Case | Runs | Prompt tokens | Prompt ms P50 | Eval tokens | Eval ms P50 | Eval tok/s | Total ms P50 | GPU avg/peak | Power avg/peak W |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in selected:
        lines.append(
            f"| {row['case']} | {row.get('runs')} | {fmt(row.get('prompt_eval_count_p50'))} | "
            f"{fmt(row.get('prompt_eval_ms_p50'))} | {fmt(row.get('eval_count_p50'))} | {fmt(row.get('eval_ms_p50'))} | "
            f"{fmt(row.get('eval_tokens_per_second_p50'))} | {fmt(row.get('total_ms_p50'))} | "
            f"{fmt(row.get('gpu_util_avg'))}/{fmt(row.get('gpu_util_peak'))} | "
            f"{fmt(row.get('power_avg_w'))}/{fmt(row.get('power_peak_w'))} |"
        )
    return lines


def gpu_table(gpu_summary: dict[str, Any]) -> list[str]:
    lines = ["| Case | Samples | GPU avg | GPU peak | Power avg W | Power peak W | SM MHz avg | P-State |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for case in sorted(gpu_summary):
        if case.startswith(("T32", "V1_", "V3_", "TTFT")):
            row = gpu_summary[case]
            lines.append(
                f"| {case} | {row.get('samples')} | {fmt(row.get('gpu_util_avg'))} | {fmt(row.get('gpu_util_peak'))} | "
                f"{fmt(row.get('power_avg_w'))} | {fmt(row.get('power_peak_w'))} | {fmt(row.get('clock_sm_avg_mhz'))} | "
                f"{json.dumps(row.get('pstate_distribution'), ensure_ascii=False)} |"
            )
    return lines


def derive_root_causes(by_case: dict[str, dict[str, Any]], gpu_summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    index = 1
    v0 = metric(by_case, "V0_0image_384", "prompt_eval_ms_p50")
    v1 = metric(by_case, "V1_1image_384", "prompt_eval_ms_p50")
    v3 = metric(by_case, "V3_3image_384", "prompt_eval_ms_p50")
    if v0 is not None and v1 is not None and v3 is not None:
        increment = v3 - v0
        confidence = "HIGH" if increment > 1000 else "MEDIUM"
        lines.extend([
            f"### ROOT CAUSE #{index} — Vision/multimodal prefill 增量",
            "",
            f"证据：0图 prompt eval={v0:.1f}ms，1图={v1:.1f}ms，3图={v3:.1f}ms；3图相对0图增加 {increment:.1f}ms。",
            f"置信度：**{confidence}**",
            "",
        ])
        index += 1
    t32 = by_case.get("T32_text_decode")
    if t32 and t32.get("eval_tokens_per_second_p50") is not None:
        speed = t32["eval_tokens_per_second_p50"]
        lines.extend([
            f"### ROOT CAUSE #{index} — 4B 文本 decode 吞吐",
            "",
            f"证据：32-token 纯文本测试中位速度为 {speed:.2f} tok/s，eval 中位耗时 {fmt(t32.get('eval_ms_p50'))}ms。",
            f"置信度：**{'HIGH' if t32.get('runs', 0) >= 3 else 'MEDIUM'}**",
            "",
        ])
        index += 1
    prod = by_case.get("Pcurrent_production_text")
    p500 = by_case.get("P500")
    if prod and p500:
        lines.extend([
            f"### ROOT CAUSE #{index} — 生产 Prompt prefill 体量",
            "",
            f"证据：P500 prompt eval={fmt(p500.get('prompt_eval_ms_p50'))}ms；当前生产纯文本 Prompt tokens={fmt(prod.get('prompt_eval_count_p50'))}，prompt eval={fmt(prod.get('prompt_eval_ms_p50'))}ms。",
            "置信度：**HIGH**",
            "",
        ])
        index += 1
    gpu = gpu_summary.get("T32_text_decode") or {}
    if gpu.get("gpu_util_avg") is not None:
        avg = gpu["gpu_util_avg"]
        label = "GPU 利用不足或存在调度等待" if avg < 50 else "GPU 计算繁忙"
        lines.extend([
            f"### ROOT CAUSE #{index} — {label}",
            "",
            f"证据：T32 请求期间 GPU 平均利用率 {avg:.1f}%，峰值 {fmt(gpu.get('gpu_util_peak'))}%，平均功耗 {fmt(gpu.get('power_avg_w'))}W。",
            "置信度：**MEDIUM**（1秒采样无法解析更短的内部同步停顿）",
        ])
    return lines


def derive_next_steps(by_case: dict[str, dict[str, Any]], gpu_summary: dict[str, Any]) -> list[str]:
    steps = ["以下建议只对应已测指标；本轮未修改生产配置。"]
    v0 = metric(by_case, "V0_0image_384", "prompt_eval_ms_p50")
    v3 = metric(by_case, "V3_3image_384", "prompt_eval_ms_p50")
    m1 = metric(by_case, "M1_three_independent", "prompt_eval_ms_p50")
    m2 = metric(by_case, "M2_three_panel", "prompt_eval_ms_p50")
    if v0 is not None and v3 is not None and v3 - v0 > 1000:
        steps.append("- Vision 增量显著：优先依据 M1/M2 结果评估三联图或减少独立图片数量，再做准确率回归。")
    if m1 is not None and m2 is not None and m2 < m1 * 0.8:
        steps.append(f"- 三联图 prompt eval 比三张独立图低 {m1 - m2:.1f}ms，值得进入业务准确率验证。")
    prod = by_case.get("Pcurrent_production_text")
    if prod and (prod.get("prompt_eval_ms_p50") or 0) > 3000:
        steps.append("- 当前生产 Prompt prefill 显著：精简重复规则和示例是有证据支持的优先项。")
    s0 = by_case.get("S0_plain")
    s7 = by_case.get("S7_production_13")
    if s0 and s7 and (s7.get("eval_tokens_per_second_p50") or 0) < (s0.get("eval_tokens_per_second_p50") or 0) * 0.7:
        steps.append("- 完整 Schema 的 decode tok/s 明显下降：可在不丢关键安全字段的前提下评估更小 Schema。")
    gpu = gpu_summary.get("T32_text_decode") or {}
    if (gpu.get("gpu_util_avg") or 100) < 50:
        steps.append("- 长请求期间 GPU 平均利用率偏低：继续检查 Vulkan/CUDA backend、CPU同步和 Ollama runtime，不应先归因于GPU算力不足。")
    steps.append("- Flash Attention A/B 仍需在可停止或隔离 Ollama 时人工执行，本报告不伪造该结果。")
    return steps


def metric(by_case: dict[str, dict[str, Any]], case: str, name: str) -> float | None:
    value = (by_case.get(case) or {}).get(name)
    return float(value) if value is not None else None


def diff(left: float | None, right: float | None) -> float | None:
    return left - right if left is not None and right is not None else None


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sidecar Ollama/Qwen latency diagnostics")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--event-root", default=r"E:\国赛\event")
    parser.add_argument("--image-dir")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--num-ctx", type=int, default=12288)
    parser.add_argument("--skip-2b", action="store_true")
    parser.add_argument(
        "--production-status-url",
        default="http://127.0.0.1:8000/runtime-control/session/status?camera_id=go2_front_camera",
    )
    parser.add_argument(
        "--allow-live-contention",
        action="store_true",
        help="Run even while the production detection session or Qwen queue is active.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    diagnostics = QwenLatencyDiagnostics(parse_args())
    print(f"Diagnostic output: {diagnostics.output_dir}", flush=True)
    diagnostics.run_all()
    print(f"Completed: {diagnostics.output_dir}", flush=True)
