from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED_MODEL = ROOT / "models" / "7-3testmodel.pt"
DEFAULT_CLEAN_DATA = ROOT / "datasets" / "fall_hint_v2_clean_reviewed_only_noaug_20260703" / "data.yaml"
DEFAULT_FINETUNE_DATA = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1" / "data.yaml"
DEFAULT_PROJECT = ROOT / "runs" / "fall_hint_seed_finetune_20260703"
ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

from ultralytics import YOLO

CLASS_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
HARD_CLASS_SET = {"falling", "fallen", "lying", "kneeling", "sitting"}
REPLAY_CLASS_SET = {"standing", "bending"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finetune YOLO Fall Hint from 7-3testmodel with staged reviewed-only data.")
    parser.add_argument("--seed-model", type=Path, default=DEFAULT_SEED_MODEL)
    parser.add_argument("--clean-data", type=Path, default=DEFAULT_CLEAN_DATA)
    parser.add_argument("--finetune-data", type=Path, default=DEFAULT_FINETUNE_DATA)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--seed", type=int, default=20260703)
    parser.add_argument("--run-candidates", default="A,B,C")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def ensure_ultralytics_workspace_state() -> None:
    ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def hashed_sort_key(seed: int, *parts: str) -> str:
    return hashlib.sha256("|".join([str(seed), *parts]).encode("utf-8")).hexdigest()


def detect_dataset_root(data_yaml: Path) -> Path:
    path_value = ""
    for raw in data_yaml.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("path:"):
            path_value = line.split(":", 1)[1].strip()
            break
    if not path_value:
        raise SystemExit(f"could not resolve dataset root from {data_yaml}")
    return Path(path_value)


def load_existing_summary(project: Path) -> dict[str, object]:
    path = project / "finetune_run_summary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def infer_run_summary(project: Path, run_name: str) -> dict[str, object] | None:
    run_dir = project / run_name
    best = run_dir / "weights" / "best.pt"
    last = run_dir / "weights" / "last.pt"
    results = run_dir / "results.csv"
    args_yaml = run_dir / "args.yaml"
    train_summary = run_dir / "train_summary.json"
    if train_summary.exists():
        try:
            return json.loads(train_summary.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if not (run_dir.exists() and best.exists() and last.exists() and results.exists() and args_yaml.exists()):
        return None
    return {
        "run_dir": str(run_dir),
        "best": str(best),
        "last": str(last),
        "model_init": "",
        "data": "",
    }


def build_stage_b_dataset(stage_a_root: Path, output_root: Path, seed: int) -> dict[str, object]:
    if output_root.exists():
        shutil.rmtree(output_root)
    for split in ["train", "val", "test"]:
        (output_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_root / "labels" / split).mkdir(parents=True, exist_ok=True)
    (output_root / "meta").mkdir(parents=True, exist_ok=True)

    manifest = read_csv(stage_a_root / "meta" / "manifest.csv")
    train_rows = [row for row in manifest if row.get("split") == "train"]
    val_rows = [row for row in manifest if row.get("split") == "val"]
    test_rows = [row for row in manifest if row.get("split") == "test"]

    selected_train: list[dict[str, str]] = []
    replay_pool: list[dict[str, str]] = []
    for row in train_rows:
        class_names = set(filter(None, row.get("class_names", "").split()))
        source_role = row.get("source_role", "")
        if source_role == "reviewed_empty_train":
            selected_train.append(row)
            continue
        if class_names & HARD_CLASS_SET:
            selected_train.append(row)
            continue
        if class_names and class_names <= REPLAY_CLASS_SET:
            replay_pool.append(row)

    target_replay = int(math.ceil(len(selected_train) * 0.25))
    replay_pool.sort(
        key=lambda row: hashed_sort_key(
            seed,
            row.get("source_video", ""),
            row.get("source_original_image", ""),
            row.get("image", ""),
        )
    )
    selected_train.extend(replay_pool[:target_replay])

    selected_ids = {row["image"] for row in selected_train}
    copied_manifest: list[dict[str, object]] = []

    def copy_row(row: dict[str, str]) -> None:
        split = row["split"]
        image_src = stage_a_root / row["image"]
        label_src = stage_a_root / row["label"]
        image_dst = output_root / row["image"]
        label_dst = output_root / row["label"]
        image_dst.parent.mkdir(parents=True, exist_ok=True)
        label_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_src, image_dst)
        shutil.copy2(label_src, label_dst)
        copied_manifest.append(dict(row))

    for row in selected_train:
        copy_row(row)
    for row in val_rows + test_rows:
        copy_row(row)

    (output_root / "data.yaml").write_text(
        "\n".join(
            [
                f"path: {output_root.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "",
                "names:",
                *[f"  {idx}: {name}" for idx, name in enumerate(CLASS_NAMES)],
                "",
            ]
        ),
        encoding="utf-8",
    )
    (output_root / "classes.txt").write_text("\n".join(CLASS_NAMES) + "\n", encoding="utf-8")
    write_csv(output_root / "meta" / "manifest.csv", copied_manifest)

    summary = {
        "stage_a_root": str(stage_a_root),
        "output_root": str(output_root),
        "seed": seed,
        "selected_train_rows": len(selected_train),
        "hard_rows": sum(1 for row in selected_train if set(filter(None, row.get("class_names", "").split())) & HARD_CLASS_SET),
        "empty_rows": sum(1 for row in selected_train if row.get("source_role") == "reviewed_empty_train"),
        "replay_rows": sum(
            1
            for row in selected_train
            if row.get("source_role") != "reviewed_empty_train"
            and set(filter(None, row.get("class_names", "").split())) <= REPLAY_CLASS_SET
        ),
        "replay_target_ratio": 0.20,
        "selected_train_ids": len(selected_ids),
    }
    (output_root / "meta" / "stage_b_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def train_model(model_path: Path, data_path: Path, project: Path, name: str, config: dict[str, object]) -> dict[str, object]:
    project.mkdir(parents=True, exist_ok=True)
    (project / f"{name}_train_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    model = YOLO(str(model_path))
    model.train(
        data=str(data_path),
        epochs=int(config["epochs"]),
        patience=int(config["patience"]),
        batch=int(config["batch"]),
        imgsz=int(config["imgsz"]),
        save=True,
        save_period=-1,
        cache=False,
        device=str(config["device"]),
        workers=int(config["workers"]),
        project=str(project),
        name=name,
        exist_ok=True,
        pretrained=True,
        optimizer="AdamW",
        verbose=True,
        seed=int(config["seed"]),
        deterministic=True,
        single_cls=False,
        rect=False,
        cos_lr=True,
        close_mosaic=int(config["close_mosaic"]),
        resume=False,
        amp=True,
        fraction=1.0,
        val=True,
        split="val",
        conf=None,
        iou=0.7,
        max_det=300,
        plots=True,
        augment=False,
        lr0=float(config["lr0"]),
        lrf=0.01,
        momentum=0.937,
        weight_decay=0.0005,
        warmup_epochs=3.0,
        warmup_momentum=0.8,
        warmup_bias_lr=0.1,
        box=7.5,
        cls=0.5,
        dfl=1.5,
        hsv_h=0.015,
        hsv_s=0.3,
        hsv_v=0.2,
        degrees=0.0,
        translate=float(config["translate"]),
        scale=float(config["scale"]),
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=float(config["fliplr"]),
        bgr=0.0,
        mosaic=float(config["mosaic"]),
        mixup=0.0,
        copy_paste=0.0,
        erasing=float(config["erasing"]),
        crop_fraction=1.0,
    )
    run_dir = project / name
    summary = {
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
        "model_init": str(model_path),
        "data": str(data_path),
    }
    (run_dir / "train_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    ensure_ultralytics_workspace_state()
    args = parse_args()
    seed_model = args.seed_model.resolve()
    clean_data = args.clean_data.resolve()
    finetune_data = args.finetune_data.resolve()
    project = args.project.resolve()
    run_candidates = {name.strip().upper() for name in args.run_candidates.split(",") if name.strip()}

    if not seed_model.exists():
        raise SystemExit(f"missing seed model: {seed_model}")
    if not clean_data.exists():
        raise SystemExit(f"missing clean data yaml: {clean_data}")
    if not finetune_data.exists():
        raise SystemExit(f"missing finetune data yaml: {finetune_data}")

    stage_a_clean_name = "candidate_a_seed_clean_posonly_stagea"
    stage_a_empty_name = "candidate_b_seed_emptyneg_stagea"
    stage_b_name = "candidate_c_seed_emptyneg_stageb"
    existing = load_existing_summary(project)
    runs: dict[str, dict[str, object]] = {}
    existing_runs = existing.get("runs", {})
    if isinstance(existing_runs, dict):
        runs.update(existing_runs)

    if "A" in run_candidates:
        config_a = {
            "seed": args.seed,
            "device": args.device,
            "workers": args.workers,
            "batch": args.batch,
            "imgsz": args.imgsz,
            "epochs": 25,
            "patience": 8,
            "lr0": 0.001,
            "mosaic": 0.2,
            "close_mosaic": 5,
            "translate": 0.05,
            "scale": 0.2,
            "fliplr": 0.5,
            "erasing": 0.0,
            "stage": "A_clean_posonly",
            "class_balance_strategy": "baseline_data_only",
        }
        runs["candidate_a"] = train_model(seed_model, clean_data, project, stage_a_clean_name, config_a)

    if "B" in run_candidates:
        config_b = {
            "seed": args.seed,
            "device": args.device,
            "workers": args.workers,
            "batch": args.batch,
            "imgsz": args.imgsz,
            "epochs": 25,
            "patience": 8,
            "lr0": 0.001,
            "mosaic": 0.2,
            "close_mosaic": 5,
            "translate": 0.05,
            "scale": 0.2,
            "fliplr": 0.5,
            "erasing": 0.0,
            "stage": "A_emptyneg",
            "class_balance_strategy": "empty_negatives_only",
        }
        runs["candidate_b"] = train_model(seed_model, finetune_data, project, stage_a_empty_name, config_b)

    if "C" in run_candidates:
        if "candidate_b" not in runs:
            stage_b_init = project / stage_a_empty_name / "weights" / "best.pt"
            if not stage_b_init.exists():
                raise SystemExit("candidate C requires candidate B best.pt")
        else:
            stage_b_init = Path(str(runs["candidate_b"]["best"]))
        stage_a_root = detect_dataset_root(finetune_data)
        stage_b_dataset_root = project / "_generated_stage_b_dataset"
        stage_b_summary = build_stage_b_dataset(stage_a_root, stage_b_dataset_root, args.seed)
        config_c = {
            "seed": args.seed,
            "device": args.device,
            "workers": args.workers,
            "batch": args.batch,
            "imgsz": args.imgsz,
            "epochs": 10,
            "patience": 5,
            "lr0": 0.0003,
            "mosaic": 0.0,
            "close_mosaic": 0,
            "translate": 0.02,
            "scale": 0.1,
            "fliplr": 0.5,
            "erasing": 0.0,
            "stage": "B_polish",
            "stage_b_dataset_root": str(stage_b_dataset_root),
            "class_balance_strategy": "hard_case_plus_replay_sampling",
        }
        runs["candidate_c"] = train_model(stage_b_init, stage_b_dataset_root / "data.yaml", project, stage_b_name, config_c)
        runs["candidate_c"]["stage_b_dataset_summary"] = stage_b_summary

    summary = {
        "seed_model": str(seed_model),
        "clean_data": str(clean_data),
        "finetune_data": str(finetune_data),
        "project": str(project),
        "runs": runs,
    }
    for key, run_name in {
        "candidate_a": stage_a_clean_name,
        "candidate_b": stage_a_empty_name,
        "candidate_c": stage_b_name,
    }.items():
        if key not in summary["runs"]:
            inferred = infer_run_summary(project, run_name)
            if inferred is not None:
                summary["runs"][key] = inferred
    (project / "finetune_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
