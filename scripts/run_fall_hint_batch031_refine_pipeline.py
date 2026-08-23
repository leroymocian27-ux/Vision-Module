from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

DEFAULT_BATCH_ID = "batch_031_hardcase_audit"
DEFAULT_BASE_DATASET = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1"
DEFAULT_MERGED_DATASET = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1_plus_batch031"
DEFAULT_PROJECT = ROOT / "runs" / "fall_hint_batch031_refine"
DEFAULT_RUNTIME_MODEL = ROOT / "models" / "yolo_fall_hint_v2_plus_b012_best.pt"
DEFAULT_CANDIDATE_B = ROOT / "runs" / "fall_hint_seed_finetune_20260703_v2" / "candidate_b_seed_emptyneg_stagea" / "weights" / "best.pt"
DEFAULT_CANDIDATE_C = ROOT / "runs" / "fall_hint_seed_finetune_20260703_v2" / "candidate_c_seed_emptyneg_stageb" / "weights" / "best.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate, merge, train, and evaluate the Fall Hint hard-case refinement line for batch 031."
    )
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--base-dataset", type=Path, default=DEFAULT_BASE_DATASET)
    parser.add_argument("--merged-dataset", type=Path, default=DEFAULT_MERGED_DATASET)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--runtime-model", type=Path, default=DEFAULT_RUNTIME_MODEL)
    parser.add_argument("--seed-model", type=Path, default=DEFAULT_CANDIDATE_B)
    parser.add_argument("--candidate-b-model", type=Path, default=DEFAULT_CANDIDATE_B)
    parser.add_argument("--candidate-c-model", type=Path, default=DEFAULT_CANDIDATE_C)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--epochs", type=int, default=36)
    parser.add_argument("--patience", type=int, default=12)
    parser.add_argument("--lr0", type=float, default=0.0015)
    parser.add_argument("--name", default="candidate_d_batch031_hardcase_refine")
    parser.add_argument("--thresholds", default="0.25,0.30,0.35,0.40,0.45,0.50")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--overwrite-merged", action="store_true")
    return parser.parse_args()


def run_json_command(command: list[str], cwd: Path) -> dict[str, object]:
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"command failed ({result.returncode}): {' '.join(command)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    stdout = result.stdout.strip()
    if not stdout:
        return {}
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    payload = stdout[start : end + 1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse JSON from command output: {exc}\nOUTPUT:\n{stdout}") from exc


def run_command(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"command failed ({result.returncode}): {' '.join(command)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def train_candidate(
    *,
    model_path: Path,
    data_yaml: Path,
    project: Path,
    name: str,
    epochs: int,
    patience: int,
    batch: int,
    imgsz: int,
    device: str,
    workers: int,
    lr0: float,
) -> dict[str, str]:
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        patience=patience,
        batch=batch,
        imgsz=imgsz,
        save=True,
        save_period=-1,
        cache=False,
        device=device,
        workers=workers,
        project=str(project),
        name=name,
        exist_ok=True,
        pretrained=True,
        optimizer="AdamW",
        verbose=True,
        seed=20260704,
        deterministic=True,
        single_cls=False,
        rect=False,
        cos_lr=True,
        close_mosaic=0,
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
        lr0=lr0,
        lrf=0.01,
        momentum=0.937,
        weight_decay=0.0005,
        warmup_epochs=2.0,
        warmup_momentum=0.8,
        warmup_bias_lr=0.05,
        box=7.5,
        cls=0.5,
        dfl=1.5,
        hsv_h=0.0,
        hsv_s=0.0,
        hsv_v=0.0,
        degrees=0.0,
        translate=0.0,
        scale=0.0,
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=0.0,
        bgr=0.0,
        mosaic=0.0,
        mixup=0.0,
        copy_paste=0.0,
        erasing=0.0,
        crop_fraction=1.0,
    )
    run_dir = project / name
    summary = {
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
        "model_init": str(model_path),
        "data": str(data_yaml),
    }
    (run_dir / "train_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()
    project = args.project.resolve()
    project.mkdir(parents=True, exist_ok=True)
    config = {
        "batch_id": args.batch_id,
        "base_dataset": str(args.base_dataset.resolve()),
        "merged_dataset": str(args.merged_dataset.resolve()),
        "runtime_model": str(args.runtime_model.resolve()),
        "seed_model": str(args.seed_model.resolve()),
        "candidate_b_model": str(args.candidate_b_model.resolve()),
        "candidate_c_model": str(args.candidate_c_model.resolve()),
        "device": args.device,
        "epochs": args.epochs,
        "patience": args.patience,
        "lr0": args.lr0,
        "name": args.name,
        "thresholds": args.thresholds,
        "prepare_only": args.prepare_only,
    }
    (project / "pipeline_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    validate_payload = run_json_command(
        [
            sys.executable,
            "scripts/validate_fall_hint_review_batch.py",
            "--batch-id",
            args.batch_id,
            "--write-report",
        ],
        cwd=ROOT,
    )
    if validate_payload.get("ready_for_merge") is not True:
        summary = {
            "status": "waiting_for_manual_review",
            "validate_summary": validate_payload,
            "next_action": "finish all 120 reviews in the labeler, then rerun this pipeline",
        }
        (project / "pipeline_waiting_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    merge_command = [
        sys.executable,
        "scripts/extend_fall_hint_seed_finetune_with_review_batch.py",
        "--batch-id",
        args.batch_id,
        "--base",
        str(args.base_dataset),
        "--output",
        str(args.merged_dataset),
    ]
    if args.overwrite_merged:
        merge_command.append("--overwrite")
    merge_payload = run_json_command(merge_command, cwd=ROOT)

    if args.prepare_only:
        summary = {
            "status": "prepared_only",
            "validate_summary": validate_payload,
            "merge_summary": merge_payload,
        }
        (project / "pipeline_prepare_only_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    train_summary = train_candidate(
        model_path=args.seed_model.resolve(),
        data_yaml=args.merged_dataset.resolve() / "data.yaml",
        project=project,
        name=args.name,
        epochs=args.epochs,
        patience=args.patience,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device,
        workers=args.workers,
        lr0=args.lr0,
    )

    eval_project = project / "eval_acceptance"
    eval_command = [
        sys.executable,
        "scripts/evaluate_fall_hint_candidates.py",
        "--data",
        str(args.merged_dataset.resolve() / "data.yaml"),
        "--empty-holdout-manifest",
        str(args.merged_dataset.resolve() / "meta" / "empty_holdout_manifest.csv"),
        "--project",
        str(eval_project),
        "--device",
        args.device,
        "--baseline-name",
        "runtime_current",
        "--baseline-model",
        str(args.runtime_model.resolve()),
        "--candidate",
        f"candidate_b={args.candidate_b_model.resolve()}",
        "--candidate",
        f"candidate_c={args.candidate_c_model.resolve()}",
        "--candidate",
        f"candidate_d={Path(train_summary['best']).resolve()}",
    ]
    run_command(eval_command, cwd=ROOT)
    acceptance_path = eval_project / "acceptance_decision.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))

    sweep_project = project / "threshold_sweep"
    sweep_command = [
        sys.executable,
        "scripts/evaluate_fall_hint_threshold_sweep.py",
        "--data",
        str(args.merged_dataset.resolve() / "data.yaml"),
        "--empty-holdout-manifest",
        str(args.merged_dataset.resolve() / "meta" / "empty_holdout_manifest.csv"),
        "--project",
        str(sweep_project),
        "--device",
        args.device,
        "--thresholds",
        args.thresholds,
        "--baseline-name",
        "runtime_current",
        "--baseline-model",
        str(args.runtime_model.resolve()),
        "--candidate",
        f"candidate_b={args.candidate_b_model.resolve()}",
        "--candidate",
        f"candidate_c={args.candidate_c_model.resolve()}",
        "--candidate",
        f"candidate_d={Path(train_summary['best']).resolve()}",
    ]
    run_command(sweep_command, cwd=ROOT)
    threshold_summary_path = sweep_project / "threshold_sweep_summary.json"
    threshold_summary = {}
    if threshold_summary_path.exists():
        threshold_summary = json.loads(threshold_summary_path.read_text(encoding="utf-8"))

    pipeline_summary = {
        "status": "completed",
        "validate_summary": validate_payload,
        "merge_summary": merge_payload,
        "train_summary": train_summary,
        "acceptance_path": str(acceptance_path),
        "threshold_sweep_path": str(threshold_summary_path),
        "threshold_sweep_models": threshold_summary.get("models", {}),
        "accepted_candidates": acceptance.get("accepted_candidates", []),
        "recommended_candidate": acceptance.get("recommended_candidate", ""),
        "runtime_model_replaced": False,
    }
    (project / "pipeline_summary.json").write_text(
        json.dumps(pipeline_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(pipeline_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
