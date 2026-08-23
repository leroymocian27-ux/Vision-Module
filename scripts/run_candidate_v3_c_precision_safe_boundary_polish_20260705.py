from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "runs" / "candidate_v3_c_precision_safe_boundary_polish_20260705"
TRAIN_DATASET_ROOT = ROOT / "datasets" / "precision_safe_boundary_polish_dataset_20260705"
TRAIN_DATA_YAML = TRAIN_DATASET_ROOT / "data.yaml"
TRAIN_SUMMARY_JSON = TRAIN_DATASET_ROOT / "summary.json"
TRAIN_NO_LEAK_JSON = TRAIN_DATASET_ROOT / "meta" / "no_leak_check.json"
TRAIN_SPLIT_JSON = TRAIN_DATASET_ROOT / "meta" / "split_summary.json"

BASE_HELPER_SCRIPT = ROOT / "scripts" / "run_candidate_v3_c_real_fall_recall_repair_20260705.py"
V3_CANDIDATE_MANIFEST = ROOT / "runs" / "fall_hint_v3_candidates_202607" / "candidate_manifest.json"
R2_STAGE_ROOT = ROOT / "runs" / "candidate_v3_c_real_fall_recall_repair_r2_20260705"
R2_MODEL_LOCATOR_JSON = R2_STAGE_ROOT / "model_locator.json"
R2_COMPARISON_SUMMARY_JSON = R2_STAGE_ROOT / "comparison_summary.json"

STAGE_NAME = "candidate_v3_c_precision_safe_boundary_polish_20260705"
MODEL_LABEL_BASELINE = "baseline"
MODEL_LABEL_CANDIDATE = "candidate_v3_c"
MODEL_LABEL_R2_MAINLINE = "r2_mainline_start"
MODEL_LABEL_R2_POLISH = "r2_polish_start"
MODEL_LABEL_NEW = "candidate_v3_c_precision_safe_boundary_polish"
FAILURE_SENTINEL = "__STAGE_FAILED__"

EXPECTED_TOTAL = 57
EXPECTED_TRAIN = 40
EXPECTED_VAL = 17
TARGET_FOCUS_IDS = {"acc_000023", "acc_000024"}

ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)


def load_base_helper():
    spec = importlib.util.spec_from_file_location("precision_safe_boundary_base_helper", BASE_HELPER_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load helper script: {BASE_HELPER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RUN_ROOT = RUN_ROOT
    module.MISSED_ROOT = RUN_ROOT / "missed_real_fall_analysis"
    return module


BASE = load_base_helper()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    BASE.write_json(path, payload)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    BASE.write_csv(path, rows)


def write_text(path: Path, text: str) -> None:
    BASE.write_text(path, text)


def ensure_runtime_layout() -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    for subdir in ["eval_test", "eval_acceptance", "per_sample_acceptance"]:
        (RUN_ROOT / subdir).mkdir(parents=True, exist_ok=True)


def dataset_precheck() -> dict[str, Any]:
    summary = read_json(TRAIN_SUMMARY_JSON)
    no_leak = read_json(TRAIN_NO_LEAK_JSON)
    split_summary = read_json(TRAIN_SPLIT_JSON)
    manifest_rows = BASE.read_csv(TRAIN_DATASET_ROOT / "meta" / "manifest.csv")
    train_image_count = len(list((TRAIN_DATASET_ROOT / "train" / "images").glob("*")))
    train_label_count = len(list((TRAIN_DATASET_ROOT / "train" / "labels").glob("*.txt")))
    val_image_count = len(list((TRAIN_DATASET_ROOT / "val" / "images").glob("*")))
    val_label_count = len(list((TRAIN_DATASET_ROOT / "val" / "labels").glob("*.txt")))

    payload = {
        "dataset_name": summary.get("dataset_name"),
        "dataset_yaml": str(TRAIN_DATA_YAML),
        "ready_for_training": bool(summary.get("ready_for_training")),
        "no_leak_pass": bool(summary.get("no_leak_pass")) and bool(no_leak.get("pass")),
        "total_items": int(summary.get("total_items", 0)),
        "train_items": int(summary.get("train_items", 0)),
        "val_items": int(summary.get("val_items", 0)),
        "manifest_rows": len(manifest_rows),
        "train_image_count": train_image_count,
        "train_label_count": train_label_count,
        "val_image_count": val_image_count,
        "val_label_count": val_label_count,
        "summary_path": str(TRAIN_SUMMARY_JSON),
        "no_leak_path": str(TRAIN_NO_LEAK_JSON),
        "split_summary_path": str(TRAIN_SPLIT_JSON),
        "summary": summary,
        "no_leak": no_leak,
        "split_summary": split_summary,
    }
    payload["counts_match"] = all(
        [
            payload["total_items"] == EXPECTED_TOTAL == payload["manifest_rows"],
            payload["train_items"] == EXPECTED_TRAIN == train_image_count == train_label_count,
            payload["val_items"] == EXPECTED_VAL == val_image_count == val_label_count,
        ]
    )
    payload["pass"] = all(
        [
            payload["ready_for_training"],
            payload["no_leak_pass"],
            payload["counts_match"],
        ]
    )
    write_json(RUN_ROOT / "dataset_precheck.json", payload)
    return payload


def locate_models() -> dict[str, dict[str, str]]:
    candidate_manifest = read_json(V3_CANDIDATE_MANIFEST)
    r2_locator = read_json(R2_MODEL_LOCATOR_JSON)
    r2_comparison = read_json(R2_COMPARISON_SUMMARY_JSON)

    candidate_info = candidate_manifest.get("candidates", {}).get("candidate_v3_c_temporal_friendly")
    if not candidate_info:
        raise RuntimeError("candidate_v3_c_temporal_friendly missing from candidate_manifest.json")

    candidate_path = Path(candidate_info["best_pt"])
    baseline_path = Path(r2_locator["models"]["baseline"]["path"])
    r2_mainline_path = None
    r2_polish_path = None
    for row in r2_comparison.get("test_metrics", []):
        if row.get("model_name") == "candidate_v3_c_recall_repair_r2_mainline_start":
            r2_mainline_path = Path(row["model_path"])
        if row.get("model_name") == "candidate_v3_c_recall_repair_r2_polish_start":
            r2_polish_path = Path(row["model_path"])
    if r2_mainline_path is None or r2_polish_path is None:
        raise RuntimeError("failed to locate r2 mainline/polish model paths from comparison_summary.json")

    located = {
        MODEL_LABEL_BASELINE: {
            "path": str(baseline_path),
            "source": str(R2_MODEL_LOCATOR_JSON),
            "evidence": "runs/candidate_v3_c_real_fall_recall_repair_r2_20260705/model_locator.json -> models.baseline.path",
        },
        MODEL_LABEL_CANDIDATE: {
            "path": str(candidate_path),
            "source": str(V3_CANDIDATE_MANIFEST),
            "evidence": "runs/fall_hint_v3_candidates_202607/candidate_manifest.json -> candidates.candidate_v3_c_temporal_friendly.best_pt",
        },
        MODEL_LABEL_R2_MAINLINE: {
            "path": str(r2_mainline_path),
            "source": str(R2_COMPARISON_SUMMARY_JSON),
            "evidence": "runs/candidate_v3_c_real_fall_recall_repair_r2_20260705/comparison_summary.json -> test_metrics[r2_mainline_start].model_path",
        },
        MODEL_LABEL_R2_POLISH: {
            "path": str(r2_polish_path),
            "source": str(R2_COMPARISON_SUMMARY_JSON),
            "evidence": "runs/candidate_v3_c_real_fall_recall_repair_r2_20260705/comparison_summary.json -> test_metrics[r2_polish_start].model_path",
        },
    }

    for model_name, info in located.items():
        if not Path(info["path"]).exists():
            raise RuntimeError(f"required model missing for {model_name}: {info['path']}")

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "models": located,
        "candidate_manifest_source": str(V3_CANDIDATE_MANIFEST),
        "r2_model_locator_source": str(R2_MODEL_LOCATOR_JSON),
        "r2_comparison_source": str(R2_COMPARISON_SUMMARY_JSON),
        "safety": {
            "replaced_production_model": False,
            "modified_env": False,
            "modified_alert_chain": False,
        },
    }
    write_json(RUN_ROOT / "model_locator.json", payload)
    return located


def cuda_info_or_raise() -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA_NOT_AVAILABLE")
    props = torch.cuda.get_device_properties(0)
    return {
        "cuda_available": True,
        "device_index": 0,
        "device_name": torch.cuda.get_device_name(0),
        "device_count": torch.cuda.device_count(),
        "total_memory_gb": round(props.total_memory / (1024**3), 2),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
    }


def choose_batch_size(total_memory_gb: float) -> int:
    if total_memory_gb >= 10:
        return 16
    if total_memory_gb >= 6:
        return 8
    return 4


def train_candidate(
    *,
    start_model: Path,
    run_name: str,
    lr0: float,
    epochs: int,
    patience: int,
    batch: int,
    seed: int,
) -> dict[str, Any]:
    from ultralytics import YOLO

    BASE.cuda_available_or_raise()
    run_dir = RUN_ROOT / run_name
    if run_dir.exists():
        shutil.rmtree(run_dir)

    train_start = time.time()
    model = YOLO(str(start_model))
    result = model.train(
        data=str(TRAIN_DATA_YAML),
        project=str(RUN_ROOT),
        name=run_name,
        exist_ok=True,
        device=0,
        workers=0,
        batch=batch,
        imgsz=640,
        epochs=epochs,
        patience=patience,
        seed=seed,
        optimizer="AdamW",
        lr0=lr0,
        lrf=0.1,
        warmup_epochs=0.0,
        warmup_bias_lr=0.0,
        mosaic=0.0,
        mixup=0.0,
        copy_paste=0.0,
        close_mosaic=0,
        fliplr=0.5,
        translate=0.0,
        scale=0.02,
        erasing=0.0,
        verbose=False,
        val=True,
        plots=True,
        save=True,
    )
    save_dir = Path(result.save_dir)
    best_pt = save_dir / "weights" / "best.pt"
    last_pt = save_dir / "weights" / "last.pt"
    args_yaml = save_dir / "args.yaml"
    if not best_pt.exists():
        raise RuntimeError(f"missing trained best.pt for {run_name}: {best_pt}")
    return {
        "run_name": run_name,
        "training_start_model": str(start_model),
        "optimizer": "AdamW",
        "lr0": lr0,
        "lrf": 0.1,
        "epochs": epochs,
        "patience": patience,
        "warmup_epochs": 0.0,
        "warmup_bias_lr": 0.0,
        "batch": batch,
        "imgsz": 640,
        "translate": 0.0,
        "scale": 0.02,
        "seed": seed,
        "freeze": False,
        "best_pt": str(best_pt),
        "last_pt": str(last_pt),
        "train_dir": str(save_dir),
        "args_yaml": str(args_yaml),
        "duration_sec": round(time.time() - train_start, 2),
    }


def top_prediction_confidence(preds: list[dict[str, Any]]) -> float | None:
    if not preds:
        return None
    return float(preds[0]["confidence"])


def bool_or_blank(value: bool) -> str:
    return "true" if value else "false"


def build_focus_rows(
    acceptance_rows: list[Any],
    predictions_by_model: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_id = {row.acceptance_id: row for row in acceptance_rows}
    for acceptance_id in sorted(TARGET_FOCUS_IDS):
        row = by_id.get(acceptance_id)
        if row is None:
            continue
        width, height = BASE.read_image_size(row.target_image_path)
        targets = BASE.parse_target_label(row.target_label_path, width, height)
        candidate_preds = predictions_by_model[MODEL_LABEL_CANDIDATE][str(row.target_image_path)]
        new_preds = predictions_by_model[MODEL_LABEL_NEW][str(row.target_image_path)]
        candidate_pass = BASE.acceptance_match(candidate_preds, targets, BASE.FALL_LIKE)
        new_pass = BASE.acceptance_match(new_preds, targets, BASE.FALL_LIKE)
        if new_pass and not candidate_pass:
            fixed_flag = "fixed"
            note = "candidate missed but new model matched fall-like target"
        elif candidate_pass and not new_pass:
            fixed_flag = "regressed"
            note = "candidate matched but new model missed"
        elif candidate_pass and new_pass:
            fixed_flag = "stable_pass"
            note = "both models passed"
        else:
            fixed_flag = "still_missed"
            note = f"candidate={BASE.reason_guess_for_real_fall(candidate_preds, targets)}; new={BASE.reason_guess_for_real_fall(new_preds, targets)}"
        rows.append(
            {
                "acceptance_id": acceptance_id,
                "expected_behavior": row.expected_behavior,
                "candidate_v3_c_prediction": BASE.top_prediction_text(candidate_preds),
                "new_model_prediction": BASE.top_prediction_text(new_preds),
                "candidate_v3_c_confidence": top_prediction_confidence(candidate_preds),
                "new_model_confidence": top_prediction_confidence(new_preds),
                "candidate_v3_c_pass": bool_or_blank(candidate_pass),
                "new_model_pass": bool_or_blank(new_pass),
                "fixed_or_not": fixed_flag,
                "notes": note,
            }
        )
    return rows


def build_boundary_error_delta(candidate_row: dict[str, Any], new_row: dict[str, Any]) -> list[dict[str, object]]:
    metrics = [
        "empty_fp",
        "false_adl",
        "real_fall_miss",
        "slow_fall_miss",
        "sitting_false_fallen",
        "bending_false_fallen",
        "kneeling_false_fallen",
        "lying_false_fallen",
        "repeat_alarm_count",
    ]
    rows: list[dict[str, object]] = []
    for metric in metrics:
        baseline_value = int(candidate_row[metric])
        new_value = int(new_row[metric])
        delta = new_value - baseline_value
        rows.append(
            {
                "metric": metric,
                "candidate_v3_c": baseline_value,
                MODEL_LABEL_NEW: new_value,
                "delta_new_minus_candidate": delta,
                "status": "improved" if delta < 0 else "worse" if delta > 0 else "unchanged",
            }
        )
    return rows


def gate_result(test_row: dict[str, Any], acceptance_row: dict[str, Any], candidate_test_row: dict[str, Any], candidate_acceptance_row: dict[str, Any]) -> dict[str, Any]:
    result = {
        "empty_fp_le_candidate_v3_c": int(acceptance_row["empty_fp"]) <= int(candidate_acceptance_row["empty_fp"]),
        "false_adl_le_candidate_v3_c": int(acceptance_row["false_adl"]) <= int(candidate_acceptance_row["false_adl"]),
        "real_fall_miss_le_candidate_v3_c": int(acceptance_row["real_fall_miss"]) <= int(candidate_acceptance_row["real_fall_miss"]),
        "precision_ge_candidate_v3_c_minus_0_02": float(test_row["precision"]) >= float(candidate_test_row["precision"]) - 0.02,
        "mAP50_95_ge_candidate_v3_c_minus_0_01": float(test_row["mAP50-95"]) >= float(candidate_test_row["mAP50-95"]) - 0.01,
        "no_new_kneeling_false_fallen": int(acceptance_row["kneeling_false_fallen"]) <= int(candidate_acceptance_row["kneeling_false_fallen"]),
        "no_new_bending_false_fallen": int(acceptance_row["bending_false_fallen"]) <= int(candidate_acceptance_row["bending_false_fallen"]),
        "no_new_sitting_false_fallen": int(acceptance_row["sitting_false_fallen"]) <= int(candidate_acceptance_row["sitting_false_fallen"]),
    }
    result["ideal_empty_fp_zero"] = int(acceptance_row["empty_fp"]) == 0
    result["ideal_false_adl_zero"] = int(acceptance_row["false_adl"]) == 0
    result["ideal_real_fall_miss_zero"] = int(acceptance_row["real_fall_miss"]) == 0
    result["ideal_precision_ge_candidate_v3_c"] = float(test_row["precision"]) >= float(candidate_test_row["precision"])
    result["ideal_mAP50_95_ge_candidate_v3_c"] = float(test_row["mAP50-95"]) >= float(candidate_test_row["mAP50-95"])
    result["pass"] = all(
        result[key]
        for key in [
            "empty_fp_le_candidate_v3_c",
            "false_adl_le_candidate_v3_c",
            "real_fall_miss_le_candidate_v3_c",
            "precision_ge_candidate_v3_c_minus_0_02",
            "mAP50_95_ge_candidate_v3_c_minus_0_01",
            "no_new_kneeling_false_fallen",
            "no_new_bending_false_fallen",
            "no_new_sitting_false_fallen",
        ]
    )
    return result


def build_log_text(
    *,
    start_time: str,
    end_time: str,
    dataset_precheck_payload: dict[str, Any],
    model_locator_payload: dict[str, Any],
    cuda_payload: dict[str, Any],
    train_payload: dict[str, Any],
    test_metrics: list[dict[str, Any]],
    acceptance_metrics: list[dict[str, Any]],
    focus_rows: list[dict[str, object]],
    boundary_delta_rows: list[dict[str, object]],
    gate_payload: dict[str, Any],
    final_payload: dict[str, Any],
) -> str:
    lines = [
        "# Build Log",
        "",
        f"1. start_time: {start_time}",
        f"2. end_time: {end_time}",
        f"3. dataset_precheck: {json.dumps(dataset_precheck_payload, ensure_ascii=False)}",
        f"4. model_locator: {json.dumps(model_locator_payload, ensure_ascii=False)}",
        f"5. training_params: {json.dumps(train_payload, ensure_ascii=False)}",
        f"6. cuda_environment: {json.dumps(cuda_payload, ensure_ascii=False)}",
        f"7. freeze_enabled: NO",
        f"8. training_completed: {'YES' if Path(train_payload['best_pt']).exists() else 'NO'}",
        "9. test_results:",
    ]
    for row in test_metrics:
        lines.append(
            f"   - {row['model_name']}: precision={row['precision']:.4f}, recall={row['recall']:.4f}, mAP50={row['mAP50']:.4f}, mAP50-95={row['mAP50-95']:.4f}"
        )
    lines.append("10. fixed_acceptance_results:")
    for row in acceptance_metrics:
        lines.append(
            "   - "
            f"{row['model_name']}: empty_fp={row['empty_fp']}, false_adl={row['false_adl']}, "
            f"real_fall_miss={row['real_fall_miss']}, slow_fall_miss={row['slow_fall_miss']}, "
            f"sitting_false_fallen={row['sitting_false_fallen']}, bending_false_fallen={row['bending_false_fallen']}, "
            f"kneeling_false_fallen={row['kneeling_false_fallen']}, lying_false_fallen={row['lying_false_fallen']}, "
            f"repeat_alarm_count={row['repeat_alarm_count']}"
        )
    lines.append("11. focus_acc_000023_000024:")
    for row in focus_rows:
        lines.append(
            "   - "
            f"{row['acceptance_id']}: candidate={row['candidate_v3_c_prediction']} (pass={row['candidate_v3_c_pass']}), "
            f"new={row['new_model_prediction']} (pass={row['new_model_pass']}), fixed_or_not={row['fixed_or_not']}"
        )
    lines.append("12. boundary_error_delta:")
    for row in boundary_delta_rows:
        lines.append(
            f"   - {row['metric']}: candidate_v3_c={row['candidate_v3_c']}, {MODEL_LABEL_NEW}={row[MODEL_LABEL_NEW]}, delta={row['delta_new_minus_candidate']}, status={row['status']}"
        )
    lines.append(f"13. gate_decision: {json.dumps(gate_payload, ensure_ascii=False)}")
    lines.append(f"14. final_decision: {json.dumps(final_payload, ensure_ascii=False)}")
    lines.extend(
        [
            "15. safety_confirmation:",
            "   - trained_model: YES",
            "   - replaced_production_model: NO",
            "   - modified_env: NO",
            "   - modified_alert_chain: NO",
            "   - used_acceptance_for_training: NO",
            "   - used_test_for_training: NO",
        ]
    )
    return "\n".join(lines) + "\n"


def write_fail_outputs(reason: str, context: dict[str, Any] | None = None) -> None:
    ensure_runtime_layout()
    payload = {
        "stage_name": STAGE_NAME,
        "stage_result": "FAIL",
        "reason": reason,
        "context": context or {},
        "final_decision": "candidate_v3_c_remains_mainline",
        "new_model_status": "experimental_only",
        "safety": {
            "trained_model": False,
            "replaced_production_model": False,
            "modified_env": False,
            "modified_alert_chain": False,
            "used_acceptance_for_training": False,
            "used_test_for_training": False,
        },
    }
    write_json(RUN_ROOT / "comparison_summary.json", payload)
    write_json(RUN_ROOT / "acceptance_gate_decision.json", payload)
    write_json(RUN_ROOT / "final_decision.json", payload)
    write_text(
        RUN_ROOT / "build_log.md",
        "\n".join(
            [
                "# Build Log",
                "",
                "stage_result: FAIL",
                f"reason: {reason}",
                "candidate_v3_c continues as mainline",
            ]
        )
        + "\n",
    )


def run_stage() -> dict[str, Any]:
    start_time = datetime.now().isoformat(timespec="seconds")
    ensure_runtime_layout()

    dataset_precheck_payload = dataset_precheck()
    if not dataset_precheck_payload["pass"]:
        raise RuntimeError("DATASET_PRECHECK_FAILED")

    model_locator = locate_models()
    model_locator_payload = read_json(RUN_ROOT / "model_locator.json")
    fixed_acceptance_repair = BASE.repair_fixed_acceptance_target_labels_if_needed()
    cuda_payload = cuda_info_or_raise()
    batch = choose_batch_size(cuda_payload["total_memory_gb"])

    train_payload = train_candidate(
        start_model=Path(model_locator[MODEL_LABEL_CANDIDATE]["path"]),
        run_name=MODEL_LABEL_NEW,
        lr0=1e-05,
        epochs=6,
        patience=3,
        batch=batch,
        seed=75,
    )

    model_paths = {
        MODEL_LABEL_BASELINE: Path(model_locator[MODEL_LABEL_BASELINE]["path"]),
        MODEL_LABEL_CANDIDATE: Path(model_locator[MODEL_LABEL_CANDIDATE]["path"]),
        MODEL_LABEL_R2_MAINLINE: Path(model_locator[MODEL_LABEL_R2_MAINLINE]["path"]),
        MODEL_LABEL_R2_POLISH: Path(model_locator[MODEL_LABEL_R2_POLISH]["path"]),
        MODEL_LABEL_NEW: Path(train_payload["best_pt"]),
    }

    baseline_eval_yaml = BASE.prepare_baseline_eval_dataset()
    acceptance_rows = BASE.load_acceptance_rows()

    eval_plan = {
        MODEL_LABEL_BASELINE: (model_paths[MODEL_LABEL_BASELINE], baseline_eval_yaml),
        MODEL_LABEL_CANDIDATE: (model_paths[MODEL_LABEL_CANDIDATE], BASE.V3_DATASET_YAML),
        MODEL_LABEL_R2_MAINLINE: (model_paths[MODEL_LABEL_R2_MAINLINE], BASE.V3_DATASET_YAML),
        MODEL_LABEL_R2_POLISH: (model_paths[MODEL_LABEL_R2_POLISH], BASE.V3_DATASET_YAML),
        MODEL_LABEL_NEW: (model_paths[MODEL_LABEL_NEW], BASE.V3_DATASET_YAML),
    }
    test_metrics = [
        BASE.eval_test_metrics(model_name, model_path, data_yaml)
        for model_name, (model_path, data_yaml) in eval_plan.items()
    ]

    acceptance_metrics, predictions_by_model, acceptance_detail_rows = BASE.evaluate_acceptance_models(
        acceptance_rows,
        model_paths,
    )
    write_csv(RUN_ROOT / "per_sample_acceptance" / "all_models_acceptance_details.csv", acceptance_detail_rows)

    focus_rows = build_focus_rows(acceptance_rows, predictions_by_model)
    write_csv(RUN_ROOT / "per_sample_acceptance" / "focus_acc_000023_000024.csv", focus_rows)

    metric_map = {row["model_name"]: row for row in test_metrics}
    acceptance_map = {row["model_name"]: row for row in acceptance_metrics}
    boundary_delta_rows = build_boundary_error_delta(acceptance_map[MODEL_LABEL_CANDIDATE], acceptance_map[MODEL_LABEL_NEW])
    write_csv(RUN_ROOT / "per_sample_acceptance" / "boundary_error_delta.csv", boundary_delta_rows)

    gate_payload = {
        "stage_name": STAGE_NAME,
        "candidate_v3_c_test": metric_map[MODEL_LABEL_CANDIDATE],
        "candidate_v3_c_acceptance": acceptance_map[MODEL_LABEL_CANDIDATE],
        "new_model_test": metric_map[MODEL_LABEL_NEW],
        "new_model_acceptance": acceptance_map[MODEL_LABEL_NEW],
        "focus_samples": focus_rows,
        "gate": gate_result(
            metric_map[MODEL_LABEL_NEW],
            acceptance_map[MODEL_LABEL_NEW],
            metric_map[MODEL_LABEL_CANDIDATE],
            acceptance_map[MODEL_LABEL_CANDIDATE],
        ),
        "fixed_acceptance_label_repair": fixed_acceptance_repair,
        "safety": {
            "trained_model": True,
            "replaced_production_model": False,
            "modified_env": False,
            "modified_alert_chain": False,
            "used_acceptance_for_training": False,
            "used_test_for_training": False,
        },
    }
    write_json(RUN_ROOT / "acceptance_gate_decision.json", gate_payload)

    passed = bool(gate_payload["gate"]["pass"])
    final_payload = {
        "stage_name": STAGE_NAME,
        "stage_result": "PASS" if passed else "FAIL",
        "final_decision": "allowed_for_shadow_mode_candidate" if passed else "candidate_v3_c_remains_mainline",
        "new_model_status": "shadow_mode_candidate" if passed else "experimental_only",
        "current_mainline_model": str(model_paths[MODEL_LABEL_CANDIDATE]),
        "new_model_path": str(model_paths[MODEL_LABEL_NEW]),
        "production_weight_replaced": False,
        "modified_env": False,
        "modified_alert_chain": False,
        "used_acceptance_for_training": False,
        "used_test_for_training": False,
        "gate": gate_payload["gate"],
    }
    write_json(RUN_ROOT / "final_decision.json", final_payload)

    comparison_summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "stage_name": STAGE_NAME,
        "dataset_precheck": dataset_precheck_payload,
        "model_locator": model_locator_payload,
        "cuda_environment": cuda_payload,
        "train_payload": train_payload,
        "test_metrics": test_metrics,
        "acceptance_metrics": acceptance_metrics,
        "focus_samples": focus_rows,
        "boundary_error_delta": boundary_delta_rows,
        "fixed_acceptance_label_repair": fixed_acceptance_repair,
        "per_sample_acceptance_dir": str(RUN_ROOT / "per_sample_acceptance"),
        "final_decision": final_payload,
    }
    write_json(RUN_ROOT / "comparison_summary.json", comparison_summary)

    end_time = datetime.now().isoformat(timespec="seconds")
    build_log = build_log_text(
        start_time=start_time,
        end_time=end_time,
        dataset_precheck_payload=dataset_precheck_payload,
        model_locator_payload=model_locator_payload,
        cuda_payload=cuda_payload,
        train_payload=train_payload,
        test_metrics=test_metrics,
        acceptance_metrics=acceptance_metrics,
        focus_rows=focus_rows,
        boundary_delta_rows=boundary_delta_rows,
        gate_payload=gate_payload,
        final_payload=final_payload,
    )
    write_text(RUN_ROOT / "build_log.md", build_log)
    return final_payload


def main() -> int:
    try:
        final_payload = run_stage()
        return 0 if final_payload["stage_result"] in {"PASS", "FAIL"} else 1
    except Exception as exc:  # noqa: BLE001
        write_fail_outputs(str(exc), {"traceback": traceback.format_exc()})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
