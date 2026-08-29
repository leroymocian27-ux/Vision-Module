from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/deploy_post_fall_v2_onnx.py"
SPEC = importlib.util.spec_from_file_location("deploy_post_fall_v2_onnx", SCRIPT_PATH)
assert SPEC and SPEC.loader
deploy_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = deploy_module
SPEC.loader.exec_module(deploy_module)


def test_update_env_text_replaces_paths_hash_and_optional_threshold() -> None:
    text = "\n".join(
        [
            "POST_FALL_V2_MODEL_PATH=models/old.onnx",
            "POST_FALL_V2_BINARY_MODEL_PATH=models/old.onnx",
            "POST_FALL_V2_BINARY_MODEL_SHA256=old",
            "POST_FALL_V2_BINARY_THRESHOLD=0.1",
            "OTHER=value",
            "",
        ]
    )

    updated, changed = deploy_module.update_env_text(
        text,
        model_path="models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx",
        sha256="abc123",
        threshold="0.3979",
    )

    assert changed is True
    assert "POST_FALL_V2_MODEL_PATH=models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx" in updated
    assert "POST_FALL_V2_BINARY_MODEL_PATH=models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx" in updated
    assert "POST_FALL_V2_BINARY_MODEL_SHA256=abc123" in updated
    assert "POST_FALL_V2_BINARY_THRESHOLD=0.3979" in updated
    assert "OTHER=value" in updated


def test_deploy_copies_model_backs_up_old_and_updates_env(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "new.onnx"
    source.write_bytes(b"new model bytes")
    destination = tmp_path / "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old model bytes")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POST_FALL_V2_BINARY_MODEL_PATH=models/old.onnx\nPOST_FALL_V2_BINARY_MODEL_SHA256=old\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(deploy_module, "ROOT", tmp_path)

    result = deploy_module.deploy(
        source=source,
        destination=destination,
        env_files=[env_file],
        threshold=None,
        providers=["CPUExecutionProvider"],
        backup_dir=tmp_path / "backups",
        dry_run=False,
        skip_contract=True,
        warmup_runs=0,
    )

    assert destination.read_bytes() == b"new model bytes"
    assert result.copied is True
    assert result.backup is not None
    assert Path(result.backup).read_bytes() == b"old model bytes"
    env_text = env_file.read_text(encoding="utf-8")
    assert "POST_FALL_V2_MODEL_PATH=models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx" in env_text
    assert "POST_FALL_V2_BINARY_MODEL_PATH=models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx" in env_text
    assert result.sha256 == deploy_module.sha256_file(source)


def test_deploy_same_hash_does_not_create_backup(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "new.onnx"
    source.write_bytes(b"same model bytes")
    destination = tmp_path / "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"same model bytes")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(deploy_module, "ROOT", tmp_path)

    result = deploy_module.deploy(
        source=source,
        destination=Path("models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"),
        env_files=[Path(".env")],
        threshold=None,
        providers=["CPUExecutionProvider"],
        backup_dir=Path("backups"),
        dry_run=False,
        skip_contract=True,
        warmup_runs=0,
    )

    assert result.copied is False
    assert result.backup is None
    assert "POST_FALL_V2_BINARY_MODEL_SHA256=" in env_file.read_text(encoding="utf-8")


def test_dry_run_does_not_copy_backup_or_write_env(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "new.onnx"
    source.write_bytes(b"new model bytes")
    destination = tmp_path / "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old model bytes")
    env_file = tmp_path / ".env"
    original_env = "POST_FALL_V2_BINARY_MODEL_PATH=models/old.onnx\nPOST_FALL_V2_BINARY_MODEL_SHA256=old\n"
    env_file.write_text(original_env, encoding="utf-8")
    backup_dir = tmp_path / "backups"

    monkeypatch.setattr(deploy_module, "ROOT", tmp_path)

    result = deploy_module.deploy(
        source=source,
        destination=destination,
        env_files=[env_file],
        threshold=None,
        providers=["CPUExecutionProvider"],
        backup_dir=backup_dir,
        dry_run=True,
        skip_contract=True,
        warmup_runs=0,
    )

    assert result.copied is True
    assert result.backup is not None
    assert destination.read_bytes() == b"old model bytes"
    assert env_file.read_text(encoding="utf-8") == original_env
    assert not backup_dir.exists()
