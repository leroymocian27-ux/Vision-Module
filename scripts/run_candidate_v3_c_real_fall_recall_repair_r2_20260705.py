from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "runs" / "candidate_v3_c_real_fall_recall_repair_r2_20260705"
TRAIN_DATASET_ROOT = ROOT / "datasets" / "real_fall_recall_repair_r2_dataset_20260705"
TRAIN_DATA_YAML = TRAIN_DATASET_ROOT / "data.yaml"
TRAIN_SUMMARY_JSON = TRAIN_DATASET_ROOT / "summary.json"
TRAIN_NO_LEAK_JSON = TRAIN_DATASET_ROOT / "meta" / "no_leak_check.json"

BASE_HELPER_SCRIPT = ROOT / "scripts" / "run_candidate_v3_c_real_fall_recall_repair_20260705.py"
BASELINE_CANDIDATE_MANIFEST = ROOT / "runs" / "fall_hint_v3_candidates_202607" / "candidate_manifest.json"
POLISH_R2_SUMMARY = (
    ROOT
    / "runs"
    / "fall_hint_v3_c_precision_polish_20260705"
    / "candidate_v3_c_polish_r2_true_low_lr_summary.json"
)
R1_RUN_ROOT = ROOT / "runs" / "fall_hint_v3_c_real_fall_recall_repair_20260705"
R1_MODEL = R1_RUN_ROOT / "candidate_v3_c_recall_repair_r1" / "weights" / "best.pt"

ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

MODEL_LABEL_BASELINE = "baseline"
MODEL_LABEL_CANDIDATE = "candidate_v3_c"
MODEL_LABEL_POLISH_R2 = "candidate_v3_c_polish_r2_true_low_lr"
MODEL_LABEL_R1 = "candidate_v3_c_recall_repair_r1"
MODEL_LABEL_R2_MAINLINE = "candidate_v3_c_recall_repair_r2_mainline_start"
MODEL_LABEL_R2_POLISH = "candidate_v3_c_recall_repair_r2_polish_start"

TARGET_CLASS_NAMES = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
FAILURE_SENTINEL = "__STAGE_FAILED__"


def load_base_helper():
    spec = importlib.util.spec_from_file_location("recall_repair_r1_base", BASE_HELPER_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load helper script: {BASE_HELPER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RUN_ROOT = RUN_ROOT
    module.MISSED_ROOT = RUN_ROOT / "missed_real_fall_analysis"
    return module


BASE = load_base_helper()


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def ensure_runtime_layout() -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    for subdir in ["eval_test", "eval_acceptance", "per_sample_acceptance"]:
        (RUN_ROOT / subdir).mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    BASE.write_json(path, payload)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    BASE.write_csv(path, rows)


def write_text(path: Path, text: str) -> None:
    BASE.write_text(path, text)


def dataset_precheck() -> dict[str, Any]:
    summary = read_json(TRAIN_SUMMARY_JSON)
    no_leak = read_json(TRAIN_NO_LEAK_JSON)
    manifest_rows = BASE.read_csv(TRAIN_DATASET_ROOT / "meta" / "manifest.csv")
    train_image_count = len(list((TRAIN_DATASET_ROOT / "train" / "images").glob("*")))
    train_label_count = len(list((TRAIN_DATASET_ROOT / "train" / "labels").glob("*.txt")))
    val_image_count = len(list((TRAIN_DATASET_ROOT / "val" / "images").glob("*")))
    val_label_count = len(list((TRAIN_DATASET_ROOT / "val" / "labels").glob("*.txt")))
    precheck = {
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
        "positive_repair_count": int(summary.get("positive_repair_count", 0)),
        "adl_anchor_count": int(summary.get("adl_anchor_count", 0)),
        "summary_path": str(TRAIN_SUMMARY_JSON),
        "no_leak_path": str(TRAIN_NO_LEAK_JSON),
        "summary": summary,
        "no_leak": no_leak,
    }
    precheck["counts_match"] = all(
        [
            precheck["manifest_rows"] == precheck["total_items"],
            precheck["train_image_count"] == precheck["train_label_count"] == precheck["train_items"],
            precheck["val_image_count"] == precheck["val_label_count"] == precheck["val_items"],
        ]
    )
    precheck["pass"] = all(
        [
            precheck["ready_for_training"],
            precheck["no_leak_pass"],
            precheck["counts_match"],
        ]
    )
    write_json(RUN_ROOT / "dataset_precheck.json", precheck)
    return precheck


def locate_models() -> dict[str, dict[str, str]]:
    candidate_manifest = read_json(BASELINE_CANDIDATE_MANIFEST)
    polish_summary = read_json(POLISH_R2_SUMMARY)

    baseline_from_polish = None
    for row in polish_summary.get("metrics", []):
        if row.get("model_name") == MODEL_LABEL_BASELINE:
            baseline_from_polish = row.get("model_path")
            break
    if not baseline_from_polish:
        raise RuntimeError("baseline model path missing in polish_r2 summary")

    current_mainline = BASE.load_candidate_v3_c_path()
    polish_path = Path(polish_summary["best_pt"])
    locator = {
        MODEL_LABEL_BASELINE: {
            "path": str(Path(baseline_from_polish)),
            "source": str(POLISH_R2_SUMMARY),
        },
        MODEL_LABEL_CANDIDATE: {
            "path": str(current_mainline),
            "source": str(BASELINE_CANDIDATE_MANIFEST),
        },
        MODEL_LABEL_POLISH_R2: {
            "path": str(polish_path),
            "source": str(POLISH_R2_SUMMARY),
        },
        MODEL_LABEL_R1: {
            "path": str(R1_MODEL),
            "source": str(R1_RUN_ROOT / "build_log.md"),
        },
    }

    for model_name, info in locator.items():
        if not Path(info["path"]).exists():
            raise RuntimeError(f"required model missing for {model_name}: {info['path']}")

    locator_payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "models": locator,
        "candidate_manifest_source": str(BASELINE_CANDIDATE_MANIFEST),
        "polish_summary_source": str(POLISH_R2_SUMMARY),
        "safety": {
            "replaced_production_model": False,
            "modified_env": False,
            "modified_alert_chain": False,
        },
    }
    write_json(RUN_ROOT / "model_locator.json", locator_payload)
    return locator


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
        "batch": batch,
        "imgsz": 640,
        "translate": 0.0,
        "scale": 0.02,
        "seed": seed,
        "best_pt": str(best_pt),
        "last_pt": str(last_pt),
        "train_dir": str(save_dir),
        "args_yaml": str(args_yaml),
        "duration_sec": round(time.time() - train_start, 2),
    }


def build_key_acceptance_focus(detail_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    focus_categories = {"real_fall", "slow_fall_like", "sitting_as_fall", "bending_as_fall", "kneeling_as_fall", "lying_adl_as_fall", "empty_scene"}
    filtered = [row for row in detail_rows if str(row.get("category")) in focus_categories]
    filtered.sort(key=lambda row: (str(row["model_name"]), str(row["category"]), str(row["acceptance_id"])))
    return filtered


def build_real_fall_miss_summary(
    acceptance_rows: list[Any],
    predictions_by_model: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    real_fall_rows = [row for row in acceptance_rows if row.category == "real_fall"]
    for row in real_fall_rows:
        width, height = BASE.read_image_size(row.target_image_path)
        targets = BASE.parse_target_label(row.target_label_path, width, height)
        miss_record: dict[str, object] = {
            "acceptance_id": row.acceptance_id,
            "image_path": str(row.target_image_path),
            "expected_behavior": row.expected_behavior,
            "notes": row.notes,
        }
        for model_name, pred_map in predictions_by_model.items():
            preds = pred_map[str(row.target_image_path)]
            matched = BASE.acceptance_match(preds, targets, {"falling", "fallen"})
            miss_record[f"{model_name}_matched"] = matched
            miss_record[f"{model_name}_top_prediction"] = BASE.top_prediction_text(preds)
            miss_record[f"{model_name}_reason_guess"] = "" if matched else BASE.reason_guess_for_real_fall(preds, targets)
        rows.append(miss_record)
    return rows


def gate_result(test_row: dict[str, Any], acceptance_row: dict[str, Any], candidate_test_row: dict[str, Any]) -> dict[str, Any]:
    result = {
        "real_fall_miss_leq_1": acceptance_row["real_fall_miss"] <= 1,
        "empty_fp_leq_1": acceptance_row["empty_fp"] <= 1,
        "false_adl_leq_0": acceptance_row["false_adl"] <= 0,
        "precision_ge_0_58": test_row["precision"] >= 0.58,
        "mAP50_95_ge_candidate_v3_c": test_row["mAP50-95"] >= candidate_test_row["mAP50-95"],
        "no_new_severe_adl_fp": all(
            acceptance_row[key] <= 0
            for key in [
                "sitting_false_fallen",
                "bending_false_fallen",
                "kneeling_false_fallen",
                "lying_false_fallen",
            ]
        ),
    }
    result["pass"] = all(result.values())
    return result


def choose_best_r2_candidate(candidate_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    passed = [row for row in candidate_rows if row["gate"]["pass"]]
    if not passed:
        return None
    return sorted(
        passed,
        key=lambda row: (
            row["acceptance"]["real_fall_miss"],
            row["acceptance"]["false_adl"],
            row["acceptance"]["empty_fp"],
            -row["test"]["precision"],
            -row["test"]["mAP50-95"],
        ),
    )[0]


def build_log_text(
    *,
    start_time: str,
    end_time: str,
    dataset_precheck_payload: dict[str, Any],
    model_locator_payload: dict[str, Any],
    cuda_payload: dict[str, Any],
    train_payloads: list[dict[str, Any]],
    test_metrics: list[dict[str, Any]],
    acceptance_metrics: list[dict[str, Any]],
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
        f"5. cuda_environment: {json.dumps(cuda_payload, ensure_ascii=False)}",
        "6. training_starts:",
    ]
    for payload in train_payloads:
        lines.append(f"   - {json.dumps(payload, ensure_ascii=False)}")
    lines.append("7. test_results:")
    for row in test_metrics:
        lines.append(
            f"   - {row['model_name']}: precision={row['precision']:.4f}, recall={row['recall']:.4f}, mAP50={row['mAP50']:.4f}, mAP50-95={row['mAP50-95']:.4f}"
        )
    lines.append("8. fixed_acceptance_results:")
    for row in acceptance_metrics:
        lines.append(
            "   - "
            f"{row['model_name']}: empty_fp={row['empty_fp']}, false_adl={row['false_adl']}, "
            f"real_fall_miss={row['real_fall_miss']}, slow_fall_miss={row['slow_fall_miss']}, "
            f"sitting_false_fallen={row['sitting_false_fallen']}, bending_false_fallen={row['bending_false_fallen']}, "
            f"kneeling_false_fallen={row['kneeling_false_fallen']}, lying_false_fallen={row['lying_false_fallen']}, "
            f"repeat_alarm_count={row['repeat_alarm_count']}"
        )
    lines.extend(
        [
            f"9. acceptance_gate_decision: {json.dumps(gate_payload, ensure_ascii=False)}",
            f"10. final_decision: {json.dumps(final_payload, ensure_ascii=False)}",
            "11. safety_confirmation:",
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
        "stage_name": "candidate_v3_c_real_fall_recall_repair_r2_20260705",
        "stage_result": "FAIL",
        "reason": reason,
        "context": context or {},
        "safety": {
            "replaced_production_model": False,
            "modified_env": False,
            "modified_alert_chain": False,
            "used_acceptance_for_training": False,
            "used_test_for_training": False,
        },
        "final_decision": "candidate_v3_c_remains_mainline",
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

    baseline_eval_yaml = BASE.prepare_baseline_eval_dataset()
    acceptance_rows = BASE.load_acceptance_rows()

    train_payloads = [
        train_candidate(
            start_model=Path(model_locator[MODEL_LABEL_CANDIDATE]["path"]),
            run_name=MODEL_LABEL_R2_MAINLINE,
            lr0=1e-05,
            epochs=10,
            patience=4,
            batch=batch,
            seed=61,
        ),
        train_candidate(
            start_model=Path(model_locator[MODEL_LABEL_POLISH_R2]["path"]),
            run_name=MODEL_LABEL_R2_POLISH,
            lr0=2e-05,
            epochs=8,
            patience=4,
            batch=batch,
            seed=71,
        ),
    ]

    model_paths = {
        MODEL_LABEL_BASELINE: Path(model_locator[MODEL_LABEL_BASELINE]["path"]),
        MODEL_LABEL_CANDIDATE: Path(model_locator[MODEL_LABEL_CANDIDATE]["path"]),
        MODEL_LABEL_POLISH_R2: Path(model_locator[MODEL_LABEL_POLISH_R2]["path"]),
        MODEL_LABEL_R1: Path(model_locator[MODEL_LABEL_R1]["path"]),
        MODEL_LABEL_R2_MAINLINE: Path(train_payloads[0]["best_pt"]),
        MODEL_LABEL_R2_POLISH: Path(train_payloads[1]["best_pt"]),
    }

    eval_plan = {
        MODEL_LABEL_BASELINE: (model_paths[MODEL_LABEL_BASELINE], baseline_eval_yaml),
        MODEL_LABEL_CANDIDATE: (model_paths[MODEL_LABEL_CANDIDATE], BASE.V3_DATASET_YAML),
        MODEL_LABEL_POLISH_R2: (model_paths[MODEL_LABEL_POLISH_R2], BASE.V3_DATASET_YAML),
        MODEL_LABEL_R1: (model_paths[MODEL_LABEL_R1], BASE.V3_DATASET_YAML),
        MODEL_LABEL_R2_MAINLINE: (model_paths[MODEL_LABEL_R2_MAINLINE], BASE.V3_DATASET_YAML),
        MODEL_LABEL_R2_POLISH: (model_paths[MODEL_LABEL_R2_POLISH], BASE.V3_DATASET_YAML),
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
    write_csv(
        RUN_ROOT / "per_sample_acceptance" / "key_focus_acceptance_details.csv",
        build_key_acceptance_focus(acceptance_detail_rows),
    )
    write_csv(
        RUN_ROOT / "per_sample_acceptance" / "real_fall_miss_focus.csv",
        build_real_fall_miss_summary(acceptance_rows, predictions_by_model),
    )

    metric_map = {row["model_name"]: row for row in test_metrics}
    acceptance_map = {row["model_name"]: row for row in acceptance_metrics}
    candidate_test_row = metric_map[MODEL_LABEL_CANDIDATE]

    candidate_rows: list[dict[str, Any]] = []
    for model_name in [MODEL_LABEL_R2_MAINLINE, MODEL_LABEL_R2_POLISH]:
        candidate_rows.append(
            {
                "model_name": model_name,
                "test": metric_map[model_name],
                "acceptance": acceptance_map[model_name],
                "gate": gate_result(metric_map[model_name], acceptance_map[model_name], candidate_test_row),
            }
        )

    best_r2_candidate = choose_best_r2_candidate(candidate_rows)
    gate_payload = {
        "stage_name": "candidate_v3_c_real_fall_recall_repair_r2_20260705",
        "fixed_acceptance_label_repair": fixed_acceptance_repair,
        "candidates": candidate_rows,
        "best_r2_candidate": best_r2_candidate["model_name"] if best_r2_candidate else None,
        "allow_shadow_mode": bool(best_r2_candidate),
        "current_mainline_model": str(model_paths[MODEL_LABEL_CANDIDATE]),
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

    final_payload = {
        "stage_name": "candidate_v3_c_real_fall_recall_repair_r2_20260705",
        "stage_result": "PASS" if best_r2_candidate else "FAIL",
        "final_decision": (
            "r2_candidate_allowed_for_shadow_mode"
            if best_r2_candidate
            else "candidate_v3_c_remains_mainline"
        ),
        "shadow_mode_candidate": best_r2_candidate["model_name"] if best_r2_candidate else None,
        "current_mainline_model": str(model_paths[MODEL_LABEL_CANDIDATE]),
        "production_weight_replaced": False,
        "modified_env": False,
        "modified_alert_chain": False,
        "used_acceptance_for_training": False,
        "used_test_for_training": False,
        "best_r2_candidate_metrics": best_r2_candidate if best_r2_candidate else None,
    }
    write_json(RUN_ROOT / "final_decision.json", final_payload)

    comparison_summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_precheck": dataset_precheck_payload,
        "model_locator": model_locator_payload,
        "cuda_environment": cuda_payload,
        "train_payloads": train_payloads,
        "test_metrics": test_metrics,
        "acceptance_metrics": acceptance_metrics,
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
        train_payloads=train_payloads,
        test_metrics=test_metrics,
        acceptance_metrics=acceptance_metrics,
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
