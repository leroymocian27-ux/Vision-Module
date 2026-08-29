from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = Path("models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx")
DEFAULT_ENV_FILES = (
    Path(".env"),
    Path(".env.example"),
    Path("configs/post_fall_v2_candidate.env"),
    Path("configs/safe_demo.env"),
)
DEFAULT_INPUT_NAME = "input"
DEFAULT_OUTPUT_NAME = "logits"
DEFAULT_INPUT_SHAPE = ("batch", 3, 224, 224)
DEFAULT_OUTPUT_WIDTH = 2


@dataclass(frozen=True)
class OnnxContract:
    input_name: str
    input_shape: list[object]
    input_type: str
    output_name: str
    output_shape: list[object]
    output_type: str
    providers: list[str]


@dataclass(frozen=True)
class DeployResult:
    source: str
    destination: str
    sha256: str
    bytes: int
    copied: bool
    backup: str | None
    env_files_updated: list[str]
    contract: OnnxContract | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_project_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return ROOT / path


def normalize_onnx_dim(dim: object) -> object:
    if isinstance(dim, str) and dim:
        return dim
    if isinstance(dim, int):
        return dim
    return str(dim)


def verify_onnx_contract(
    model_path: Path,
    *,
    providers: list[str],
    input_name: str = DEFAULT_INPUT_NAME,
    output_name: str = DEFAULT_OUTPUT_NAME,
    warmup_runs: int = 1,
) -> OnnxContract:
    try:
        import numpy as np
        import onnxruntime as ort
    except Exception as exc:  # pragma: no cover - depends on deployment env
        raise RuntimeError(f"onnxruntime/numpy unavailable: {exc}") from exc

    available = set(ort.get_available_providers())
    selected = [provider for provider in providers if provider in available]
    if not selected:
        selected = ["CPUExecutionProvider"]

    session = ort.InferenceSession(str(model_path), providers=selected)
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or inputs[0].name != input_name:
        raise RuntimeError(f"unexpected ONNX input contract: {[item.name for item in inputs]}")
    if len(outputs) != 1 or outputs[0].name != output_name:
        raise RuntimeError(f"unexpected ONNX output contract: {[item.name for item in outputs]}")

    input_shape = [normalize_onnx_dim(dim) for dim in inputs[0].shape]
    output_shape = [normalize_onnx_dim(dim) for dim in outputs[0].shape]
    fixed_input_shape = [1 if dim == "batch" else dim for dim in DEFAULT_INPUT_SHAPE]
    if input_shape != list(DEFAULT_INPUT_SHAPE):
        raise RuntimeError(f"unexpected ONNX input shape: {input_shape}")
    if len(output_shape) != 2 or output_shape[-1] != DEFAULT_OUTPUT_WIDTH:
        raise RuntimeError(f"unexpected ONNX output shape: {output_shape}")

    for _ in range(max(0, warmup_runs)):
        dummy = np.zeros(fixed_input_shape, dtype=np.float32)
        logits = session.run(None, {input_name: dummy})[0]
        if tuple(logits.shape) != (1, DEFAULT_OUTPUT_WIDTH):
            raise RuntimeError(f"unexpected warmup logits shape: {logits.shape}")

    return OnnxContract(
        input_name=inputs[0].name,
        input_shape=input_shape,
        input_type=inputs[0].type,
        output_name=outputs[0].name,
        output_shape=output_shape,
        output_type=outputs[0].type,
        providers=session.get_providers(),
    )


def parse_providers(value: str) -> list[str]:
    providers = [item.strip() for item in value.split(",") if item.strip()]
    return providers or ["CPUExecutionProvider"]


def update_env_text(text: str, *, model_path: str, sha256: str, threshold: str | None) -> tuple[str, bool]:
    values = {
        "POST_FALL_V2_MODEL_PATH": model_path,
        "POST_FALL_V2_BINARY_MODEL_PATH": model_path,
        "POST_FALL_V2_BINARY_MODEL_SHA256": sha256,
    }
    if threshold is not None:
        values["POST_FALL_V2_BINARY_THRESHOLD"] = threshold

    trailing_newline = text.endswith(("\n", "\r\n"))
    lines = text.splitlines()
    seen: set[str] = set()
    changed = False
    updated: list[str] = []

    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in values:
            replacement = f"{key}={values[key]}"
            updated.append(replacement)
            seen.add(key)
            changed = changed or replacement != line
        else:
            updated.append(line)

    for key, value in values.items():
        if key not in seen:
            updated.append(f"{key}={value}")
            changed = True

    newline = "\n"
    result = newline.join(updated)
    if trailing_newline:
        result += newline
    return result, changed


def update_env_files(env_files: Iterable[Path], *, model_path: str, sha256: str, threshold: str | None, dry_run: bool) -> list[Path]:
    updated: list[Path] = []
    for env_file in env_files:
        path = resolve_project_path(env_file)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new_text, changed = update_env_text(text, model_path=model_path, sha256=sha256, threshold=threshold)
        if not changed:
            continue
        updated.append(path)
        if not dry_run:
            path.write_text(new_text, encoding="utf-8", newline="\n")
    return updated


def backup_destination(destination: Path, backup_dir: Path, *, dry_run: bool) -> Path | None:
    if not destination.exists():
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"{destination.stem}.{stamp}.bak{destination.suffix}"
    if not dry_run:
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, backup)
    return backup


def deploy(
    *,
    source: Path,
    destination: Path,
    env_files: Iterable[Path],
    threshold: str | None,
    providers: list[str],
    backup_dir: Path,
    dry_run: bool,
    skip_contract: bool,
    warmup_runs: int,
) -> DeployResult:
    source = source.resolve()
    destination = resolve_project_path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source model not found: {source}")
    if source.suffix.lower() != ".onnx":
        raise ValueError(f"source is not an ONNX file: {source}")

    contract = None
    if not skip_contract:
        contract = verify_onnx_contract(source, providers=providers, warmup_runs=warmup_runs)

    digest = sha256_file(source)
    same_file = destination.exists() and sha256_file(destination) == digest
    backup = None
    copied = False
    if not same_file:
        backup = backup_destination(destination, resolve_project_path(backup_dir), dry_run=dry_run)
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp_destination = destination.with_suffix(destination.suffix + ".tmp")
            shutil.copy2(source, temp_destination)
            os.replace(temp_destination, destination)
        copied = True

    rel_model_path = destination.relative_to(ROOT).as_posix()
    updated_env_files = update_env_files(
        env_files,
        model_path=rel_model_path,
        sha256=digest,
        threshold=threshold,
        dry_run=dry_run,
    )

    return DeployResult(
        source=str(source),
        destination=str(destination),
        sha256=digest,
        bytes=source.stat().st_size,
        copied=copied,
        backup=str(backup) if backup else None,
        env_files_updated=[str(path) for path in updated_env_files],
        contract=contract,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and deploy a Post-Fall V2 ONNX binary model into camera-service.",
    )
    parser.add_argument("source", type=Path, help="New .onnx file to deploy.")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--env-file", action="append", type=Path, dest="env_files")
    parser.add_argument("--threshold", default=None, help="Optional POST_FALL_V2_BINARY_THRESHOLD value.")
    parser.add_argument(
        "--providers",
        default="CPUExecutionProvider",
        help="Comma-separated ONNX Runtime providers used for pre-deploy verification.",
    )
    parser.add_argument("--backup-dir", type=Path, default=Path("models/backups/post_fall_v2"))
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--skip-contract", action="store_true", help="Skip ONNX Runtime contract verification.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_files = tuple(args.env_files) if args.env_files else DEFAULT_ENV_FILES
    result = deploy(
        source=args.source,
        destination=args.destination,
        env_files=env_files,
        threshold=args.threshold,
        providers=parse_providers(args.providers),
        backup_dir=args.backup_dir,
        dry_run=args.dry_run,
        skip_contract=args.skip_contract,
        warmup_runs=args.warmup_runs,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
