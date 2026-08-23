from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "datasets" / "fall_hint_v3_balanced_hardcase_202607"
DATASET_YAML = DATASET_ROOT / "dataset.yaml"
CLASS_MAPPING_PATH = DATASET_ROOT / "class_mapping.json"
OUTPUT_ROOT = ROOT / "runs" / "fall_hint_v3_candidates_202607"
ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

EXPECTED_CLASS_MAPPING = {
    "0": "standing",
    "1": "fallen",
    "2": "sitting",
    "3": "lying",
    "4": "falling",
    "5": "kneeling",
    "6": "bending",
}
OLD_ORDER_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
NEW_ORDER_NAMES = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
OLD_TO_NEW_ORDER = [6, 1, 3, 2, 0, 5, 4]
ISO_NOW = datetime.now().isoformat(timespec="seconds")


def read_yaml_lines(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ensure_output_root() -> None:
    if OUTPUT_ROOT.exists():
        resolved = OUTPUT_ROOT.resolve()
        workspace = ROOT.resolve()
        if workspace not in resolved.parents:
            raise RuntimeError(f"unsafe output root outside workspace: {resolved}")
        shutil.rmtree(resolved)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def precheck_dataset() -> dict[str, object]:
    issues: list[str] = []
    if not DATASET_YAML.exists():
        issues.append(f"missing dataset.yaml: {DATASET_YAML}")
    if not CLASS_MAPPING_PATH.exists():
        issues.append(f"missing class_mapping.json: {CLASS_MAPPING_PATH}")
    if issues:
        return {"ok": False, "issues": issues}

    yaml_values = read_yaml_lines(DATASET_YAML)
    yaml_text = DATASET_YAML.read_text(encoding="utf-8").lower()
    if "acceptance" in yaml_text:
        issues.append("dataset.yaml unexpectedly contains acceptance")

    dataset_path = Path(yaml_values.get("path", ""))
    train_dir = dataset_path / "train" / "images"
    val_dir = dataset_path / "val" / "images"
    test_dir = dataset_path / "test" / "images"
    train_label_dir = dataset_path / "train" / "labels"
    val_label_dir = dataset_path / "val" / "labels"
    test_label_dir = dataset_path / "test" / "labels"
    split_counts = {}
    for name, image_dir, label_dir in [
        ("train", train_dir, train_label_dir),
        ("val", val_dir, val_label_dir),
        ("test", test_dir, test_label_dir),
    ]:
        image_count = len([path for path in image_dir.glob("*") if path.is_file()])
        label_count = len(list(label_dir.glob("*.txt")))
        split_counts[name] = {"images": image_count, "labels": label_count}
        if image_count == 0:
            issues.append(f"{name}/images is empty")
        if label_count == 0:
            issues.append(f"{name}/labels is empty")

    class_mapping = json.loads(CLASS_MAPPING_PATH.read_text(encoding="utf-8"))
    if class_mapping != EXPECTED_CLASS_MAPPING:
        issues.append(f"class mapping mismatch: {class_mapping}")

    return {
        "ok": not issues,
        "issues": issues,
        "dataset_path": str(dataset_path),
        "split_counts": split_counts,
    }


def select_baseline_model() -> dict[str, object]:
    priority_paths = [
        ROOT / "models" / "7-3testmodel.pt",
        ROOT / "models" / "fall_hint" / "7-3testmodel.pt",
    ]
    selected_path: Path | None = None
    for candidate in priority_paths:
        if candidate.exists():
            selected_path = candidate.resolve()
            break
    fallback_used = False
    reason = ""
    if selected_path is None:
        selected_path = Path("yolo11n.pt")
        fallback_used = True
        reason = "BASELINE_MODEL_NOT_FOUND_USED_PRETRAINED"
    payload = {
        "selected_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_model": str(selected_path),
        "fallback_used": fallback_used,
        "reason": reason,
    }
    return payload


def prepare_remapped_seed(baseline_model_path: str) -> dict[str, object]:
    from ultralytics import YOLO

    baseline_path = Path(baseline_model_path)
    payload = {
        "source_model": str(baseline_path),
        "training_seed": str(baseline_path),
        "remapped_for_v3_order": False,
        "old_names": [],
        "new_names": NEW_ORDER_NAMES,
    }
    if not baseline_path.exists():
        return payload

    model = YOLO(str(baseline_path))
    old_names = [model.names[idx] for idx in sorted(model.names)]
    payload["old_names"] = old_names
    if old_names != OLD_ORDER_NAMES:
        return payload

    remapped_seed_path = OUTPUT_ROOT / "support" / "baseline_seed_remapped_to_v3_order.pt"
    remapped_seed_path.parent.mkdir(parents=True, exist_ok=True)
    detect = model.model.model[-1]
    for head in detect.cv3:
        conv = head[-1]
        conv.weight.data = conv.weight.data[OLD_TO_NEW_ORDER].clone()
        conv.bias.data = conv.bias.data[OLD_TO_NEW_ORDER].clone()
    new_name_map = {idx: name for idx, name in enumerate(NEW_ORDER_NAMES)}
    model.model.names = new_name_map
    if hasattr(model, "ckpt") and isinstance(model.ckpt, dict):
        model.ckpt["names"] = new_name_map
    model.save(str(remapped_seed_path))
    if not remapped_seed_path.exists():
        raise RuntimeError("failed to save remapped seed model")
    payload["training_seed"] = str(remapped_seed_path)
    payload["remapped_for_v3_order"] = True
    return payload


def prepare_candidate_b_variant() -> dict[str, object]:
    variant_root = OUTPUT_ROOT / "dataset_variants" / "candidate_v3_b_fp_suppression"
    if variant_root.exists():
        shutil.rmtree(variant_root)
    (variant_root / "train" / "images").mkdir(parents=True, exist_ok=True)
    (variant_root / "train" / "labels").mkdir(parents=True, exist_ok=True)

    manifest_rows = read_csv(DATASET_ROOT / "manifest.csv")
    train_rows = [row for row in manifest_rows if row.get("split") == "train"]
    hard_negative_rows = [row for row in train_rows if row.get("is_hard_negative") == "true"]

    copied = 0
    duplicated = 0
    for row in train_rows:
        src_image = Path(row["v3_image_path"])
        src_label = Path(row["v3_label_path"])
        dst_image = variant_root / "train" / "images" / src_image.name
        dst_label = variant_root / "train" / "labels" / src_label.name
        shutil.copy2(src_image, dst_image)
        shutil.copy2(src_label, dst_label)
        copied += 1
        if row.get("is_hard_negative") == "true":
            dup_image = variant_root / "train" / "images" / f"{src_image.stem}_hnx1{src_image.suffix}"
            dup_label = variant_root / "train" / "labels" / f"{src_label.stem}_hnx1.txt"
            shutil.copy2(src_image, dup_image)
            shutil.copy2(src_label, dup_label)
            duplicated += 1

    dataset_yaml = "\n".join(
        [
            f"path: {variant_root.as_posix()}",
            "train: train/images",
            f"val: {(DATASET_ROOT / 'val' / 'images').as_posix()}",
            f"test: {(DATASET_ROOT / 'test' / 'images').as_posix()}",
            "",
            "names:",
            *[f"  {idx}: {name}" for idx, name in enumerate(NEW_ORDER_NAMES)],
            "",
        ]
    )
    write_text(variant_root / "dataset.yaml", dataset_yaml)
    summary = {
        "variant_root": str(variant_root),
        "source_dataset": str(DATASET_ROOT),
        "train_rows_copied": copied,
        "hard_negative_rows": len(hard_negative_rows),
        "hard_negative_duplicates_added": duplicated,
        "oversample_factor_for_hard_negative": 2,
        "acceptance_used": False,
    }
    write_json(variant_root / "variant_summary.json", summary)
    return summary


def inspect_runtime_environment() -> dict[str, object]:
    import torch
    import ultralytics

    return {
        "python": sys.version,
        "torch": torch.__version__,
        "ultralytics": ultralytics.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "device_count": int(torch.cuda.device_count()),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    }


def train_candidate(
    *,
    model_path: str,
    data_path: str,
    config: dict[str, object],
    cuda_available: bool,
) -> dict[str, object]:
    from ultralytics import YOLO

    run_name = str(config["name"])
    attempts: list[dict[str, object]] = []
    start_time = time.time()

    if cuda_available:
        candidates = [
            {"device": "0", "epochs": int(config["epochs"]), "imgsz": int(config["imgsz"]), "batch": 16},
            {"device": "0", "epochs": int(config["epochs"]), "imgsz": int(config["imgsz"]), "batch": 8},
            {"device": "0", "epochs": int(config["epochs"]), "imgsz": int(config["imgsz"]), "batch": 4},
            {"device": "0", "epochs": int(config["epochs"]), "imgsz": 512, "batch": 4},
        ]
    else:
        candidates = [
            {"device": "cpu", "epochs": 5, "imgsz": 416, "batch": 4},
        ]

    last_error = ""
    for attempt in candidates:
        attempt_payload = dict(attempt)
        attempt_payload["started_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            run_dir = OUTPUT_ROOT / run_name
            if run_dir.exists():
                shutil.rmtree(run_dir)
            model = YOLO(model_path)
            result = model.train(
                data=data_path,
                project=str(OUTPUT_ROOT),
                name=run_name,
                exist_ok=True,
                device=attempt["device"],
                workers=0,
                batch=attempt["batch"],
                imgsz=attempt["imgsz"],
                epochs=attempt["epochs"],
                patience=int(config["patience"]),
                seed=int(config["seed"]),
                lr0=float(config["lr0"]),
                lrf=float(config["lrf"]),
                mosaic=float(config["mosaic"]),
                mixup=float(config["mixup"]),
                copy_paste=float(config["copy_paste"]),
                close_mosaic=int(config["close_mosaic"]),
                fliplr=0.5,
                translate=float(config.get("translate", 0.05)),
                scale=float(config.get("scale", 0.2)),
                erasing=0.0,
                verbose=False,
                val=True,
                plots=True,
                save=True,
            )
            save_dir = Path(result.save_dir)
            best_pt = save_dir / "weights" / "best.pt"
            last_pt = save_dir / "weights" / "last.pt"
            if not best_pt.exists():
                raise RuntimeError(f"missing best.pt after train: {best_pt}")
            if not last_pt.exists():
                raise RuntimeError(f"missing last.pt after train: {last_pt}")
            attempt_payload["status"] = "success"
            attempt_payload["save_dir"] = str(save_dir)
            attempt_payload["best_pt"] = str(best_pt)
            attempt_payload["last_pt"] = str(last_pt)
            attempts.append(attempt_payload)
            return {
                "name": run_name,
                "strategy": str(config["strategy"]),
                "data": data_path,
                "model_init": model_path,
                "train_dir": str(save_dir),
                "best_pt": str(best_pt),
                "last_pt": str(last_pt),
                "attempts": attempts,
                "fallback_used": not cuda_available or attempt["batch"] != 16 or attempt["imgsz"] != int(config["imgsz"]),
                "duration_sec": round(time.time() - start_time, 2),
            }
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            attempt_payload["status"] = "failed"
            attempt_payload["error"] = message
            attempts.append(attempt_payload)
            last_error = message
            if cuda_available and any(token in message.lower() for token in ["out of memory", "cuda", "cudnn"]):
                continue
            raise

    raise RuntimeError(f"all training attempts failed for {run_name}: {last_error}")


def build_train_configs(candidate_b_variant_yaml: Path) -> list[dict[str, object]]:
    return [
        {
            "name": "candidate_v3_a_conservative",
            "strategy": "conservative",
            "data": str(DATASET_YAML),
            "epochs": 30,
            "imgsz": 640,
            "patience": 8,
            "seed": 42,
            "lr0": 0.001,
            "lrf": 0.01,
            "mosaic": 0.5,
            "mixup": 0.0,
            "copy_paste": 0.0,
            "close_mosaic": 10,
            "translate": 0.05,
            "scale": 0.20,
        },
        {
            "name": "candidate_v3_b_fp_suppression",
            "strategy": "false_positive_suppression",
            "data": str(candidate_b_variant_yaml),
            "epochs": 35,
            "imgsz": 640,
            "patience": 8,
            "seed": 43,
            "lr0": 0.001,
            "lrf": 0.01,
            "mosaic": 0.4,
            "mixup": 0.0,
            "copy_paste": 0.0,
            "close_mosaic": 10,
            "translate": 0.05,
            "scale": 0.20,
        },
        {
            "name": "candidate_v3_c_temporal_friendly",
            "strategy": "temporal_friendly",
            "data": str(DATASET_YAML),
            "epochs": 35,
            "imgsz": 640,
            "patience": 10,
            "seed": 44,
            "lr0": 0.0008,
            "lrf": 0.01,
            "mosaic": 0.0,
            "mixup": 0.0,
            "copy_paste": 0.0,
            "close_mosaic": 0,
            "translate": 0.02,
            "scale": 0.10,
        },
    ]


def write_train_outputs(
    *,
    baseline_source: dict[str, object],
    remap_info: dict[str, object],
    env_info: dict[str, object],
    precheck: dict[str, object],
    variant_summary: dict[str, object],
    train_results: list[dict[str, object]],
    configs: list[dict[str, object]],
) -> None:
    train_config_summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(DATASET_YAML),
        "dataset_summary": precheck,
        "baseline_source": baseline_source,
        "remapped_seed": remap_info,
        "environment": env_info,
        "candidate_configs": configs,
        "candidate_b_variant": variant_summary,
        "train_results": train_results,
    }
    write_json(OUTPUT_ROOT / "train_config_summary.json", train_config_summary)
    baseline_payload = dict(baseline_source)
    baseline_payload["training_seed"] = remap_info["training_seed"]
    baseline_payload["remapped_for_v3_order"] = remap_info["remapped_for_v3_order"]
    baseline_payload["old_names"] = remap_info["old_names"]
    baseline_payload["new_names"] = remap_info["new_names"]
    write_json(OUTPUT_ROOT / "baseline_model_source.json", baseline_payload)

    candidate_manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": DATASET_YAML.as_posix(),
        "baseline_model": remap_info["training_seed"],
        "candidates": {
            result["name"]: {
                "best_pt": result["best_pt"],
                "last_pt": result["last_pt"],
                "train_dir": result["train_dir"],
                "strategy": result["strategy"],
            }
            for result in train_results
        },
        "safety": {
            "replaced_production_model": False,
            "modified_env": False,
            "modified_alarm_chain": False,
        },
    }
    write_json(OUTPUT_ROOT / "candidate_manifest.json", candidate_manifest)

    readme_lines = [
        "# Fall Hint v3 Candidates 202607",
        "",
        "这个目录保存本轮 v3 候选模型训练、评估和决策产物。",
        "",
        f"- v3 dataset.yaml: `{DATASET_YAML}`",
        f"- baseline source: `{baseline_source['baseline_model']}`",
        f"- training seed used: `{remap_info['training_seed']}`",
        f"- CUDA available: `{env_info['cuda_available']}`",
        "",
        "本轮不会替换正式模型，不会修改 .env，不会接入正式告警链路。",
    ]
    write_text(OUTPUT_ROOT / "README.md", "\n".join(readme_lines) + "\n")

    log_lines = [
        "# Train Log",
        "",
        f"- started_at: {ISO_NOW}",
        f"- dataset: {DATASET_YAML}",
        f"- split counts: {json.dumps(precheck['split_counts'], ensure_ascii=False)}",
        f"- baseline source: {baseline_source['baseline_model']}",
        f"- remapped seed used: {remap_info['training_seed']}",
        f"- torch: {env_info['torch']}",
        f"- ultralytics: {env_info['ultralytics']}",
        f"- cuda_available: {env_info['cuda_available']}",
        f"- device_name: {env_info['device_name']}",
        "",
    ]
    for result in train_results:
        log_lines.extend(
            [
                f"## {result['name']}",
                f"- strategy: {result['strategy']}",
                f"- model_init: {result['model_init']}",
                f"- data: {result['data']}",
                f"- train_dir: {result['train_dir']}",
                f"- best_pt: {result['best_pt']}",
                f"- last_pt: {result['last_pt']}",
                f"- duration_sec: {result['duration_sec']}",
                f"- fallback_used: {result['fallback_used']}",
                f"- attempts: {json.dumps(result['attempts'], ensure_ascii=False)}",
                "",
            ]
        )
    write_text(OUTPUT_ROOT / "train_log.md", "\n".join(log_lines))


def write_blocked_precheck(precheck: dict[str, object]) -> None:
    lines = ["# BLOCKED PRECHECK", ""]
    for issue in precheck["issues"]:
        lines.append(f"- {issue}")
    write_text(OUTPUT_ROOT / "BLOCKED_PRECHECK.md", "\n".join(lines) + "\n")


def main() -> int:
    ensure_output_root()

    precheck = precheck_dataset()
    if not precheck["ok"]:
        write_blocked_precheck(precheck)
        return 1

    baseline_source = select_baseline_model()
    remap_info = prepare_remapped_seed(str(baseline_source["baseline_model"]))
    env_info = inspect_runtime_environment()
    variant_summary = prepare_candidate_b_variant()
    configs = build_train_configs(Path(variant_summary["variant_root"]) / "dataset.yaml")

    train_results: list[dict[str, object]] = []
    for config in configs:
        result = train_candidate(
            model_path=str(remap_info["training_seed"]),
            data_path=str(config["data"]),
            config=config,
            cuda_available=bool(env_info["cuda_available"]),
        )
        train_results.append(result)
        write_train_outputs(
            baseline_source=baseline_source,
            remap_info=remap_info,
            env_info=env_info,
            precheck=precheck,
            variant_summary=variant_summary,
            train_results=train_results,
            configs=configs,
        )

    write_train_outputs(
        baseline_source=baseline_source,
        remap_info=remap_info,
        env_info=env_info,
        precheck=precheck,
        variant_summary=variant_summary,
        train_results=train_results,
        configs=configs,
    )

    eval_script = ROOT / "scripts" / "eval_fall_hint_v3_candidates_202607.py"
    subprocess.run([sys.executable, str(eval_script)], check=True, cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
