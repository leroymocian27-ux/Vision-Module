from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Literal


DOMAIN_CALIBRATION = "DOMAIN_CALIBRATION"
DOMAIN_ACCEPTANCE = "DOMAIN_ACCEPTANCE"
VALID_SPLITS = {DOMAIN_CALIBRATION, DOMAIN_ACCEPTANCE}

SOURCE_LIVE = "LIVE"
SOURCE_TARGET_CAMERA_REPLAY = "TARGET_CAMERA_REPLAY"
SOURCE_NON_DOMAIN_SMOKE = "NON_DOMAIN_SMOKE"
VALID_DOMAIN_SOURCE_TYPES = {SOURCE_LIVE, SOURCE_TARGET_CAMERA_REPLAY}

GROUND_TRUTH_FALL = "Fall"
GROUND_TRUTH_NOFALL = "noFall"
VALID_BINARY_GROUND_TRUTH = {GROUND_TRUTH_FALL, GROUND_TRUTH_NOFALL}

SCENARIO_TO_BINARY_GROUND_TRUTH: dict[str, str] = {
    "standing": GROUND_TRUTH_NOFALL,
    "walking": GROUND_TRUTH_NOFALL,
    "sitting": GROUND_TRUTH_NOFALL,
    "bending": GROUND_TRUTH_NOFALL,
    "squatting": GROUND_TRUTH_NOFALL,
    "kneeling": GROUND_TRUTH_NOFALL,
    "lying_bed": GROUND_TRUTH_NOFALL,
    "lying_sofa": GROUND_TRUTH_NOFALL,
    "lying_floor_normal": GROUND_TRUTH_NOFALL,
    "exercise_floor": GROUND_TRUTH_NOFALL,
    "fallen_floor_supine": GROUND_TRUTH_FALL,
    "fallen_floor_prone": GROUND_TRUTH_FALL,
    "fallen_floor_side": GROUND_TRUTH_FALL,
    "fallen_near_furniture": GROUND_TRUTH_FALL,
    "partial_occlusion_fallen": GROUND_TRUTH_FALL,
    "no_person": GROUND_TRUTH_NOFALL,
    "unknown": GROUND_TRUTH_NOFALL,
}

HARD_NEGATIVE_SCENARIOS = {
    "lying_bed",
    "lying_sofa",
    "lying_floor_normal",
    "exercise_floor",
}

FALLEN_FLOOR_SCENARIOS = {
    "fallen_floor_supine",
    "fallen_floor_prone",
    "fallen_floor_side",
    "fallen_near_furniture",
    "partial_occlusion_fallen",
}

SPECIAL_SCENARIOS = {
    "POST_FALL_BOOTSTRAP_SCENARIO",
    "POST_FALL_RECONNECT_SCENARIO",
}

CORE_NOFALL_SCENARIOS = {"standing", "sitting", "walking", "bending"}
REQUIRED_HARD_NEGATIVE_SCENARIOS = HARD_NEGATIVE_SCENARIOS
REQUIRED_FALL_SCENARIOS = {"fallen_floor_supine", "fallen_floor_prone", "fallen_floor_side"}


@dataclass(frozen=True)
class DomainSession:
    session_id: str
    camera_id: str
    room_id: str
    actor_id: str
    scenario_label: str
    binary_ground_truth: str
    split: Literal["DOMAIN_CALIBRATION", "DOMAIN_ACCEPTANCE"]
    source_type: str
    recorded_at: str | None = None
    lighting: str | None = None
    distance_category: str | None = None
    occlusion_level: str | None = None
    camera_position_version: str | None = None
    resolution: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    source_path: str | None = None
    source_url: str | None = None
    sample_fps: float = 2.0
    input_policy: str = "FULL_FRAME_TRAIN_MATCHED"
    model_hash: str | None = None
    special_scenarios: list[str] = field(default_factory=list)
    domain_source_valid: bool = True

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], *, allow_non_domain_smoke: bool = False) -> "DomainSession":
        data = {str(key): value for key, value in payload.items()}
        required = [
            "session_id",
            "camera_id",
            "room_id",
            "actor_id",
            "scenario_label",
            "binary_ground_truth",
            "split",
            "source_type",
        ]
        missing = [key for key in required if not str(data.get(key, "")).strip()]
        if missing:
            raise ValueError(f"missing required session fields: {', '.join(missing)}")

        scenario_label = str(data["scenario_label"]).strip()
        if scenario_label not in SCENARIO_TO_BINARY_GROUND_TRUTH:
            raise ValueError(f"unsupported scenario_label: {scenario_label}")

        binary_ground_truth = str(data["binary_ground_truth"]).strip()
        if binary_ground_truth not in VALID_BINARY_GROUND_TRUTH:
            raise ValueError(f"unsupported binary_ground_truth: {binary_ground_truth}")
        expected_gt = SCENARIO_TO_BINARY_GROUND_TRUTH[scenario_label]
        if binary_ground_truth != expected_gt:
            raise ValueError(
                f"binary_ground_truth mismatch for {scenario_label}: expected {expected_gt}, got {binary_ground_truth}"
            )

        split = str(data["split"]).strip()
        if split not in VALID_SPLITS:
            raise ValueError(f"unsupported split: {split}")

        source_type = str(data["source_type"]).strip()
        domain_source_valid = source_type in VALID_DOMAIN_SOURCE_TYPES
        if not domain_source_valid and not allow_non_domain_smoke:
            raise ValueError(f"source_type is not valid domain evidence: {source_type}")

        source_path = _optional_str(data.get("source_path"))
        source_url = _optional_str(data.get("source_url"))
        if source_path and source_path.lower().startswith("mock://"):
            domain_source_valid = False
            if not allow_non_domain_smoke:
                raise ValueError("mock:// sources cannot be used as domain evidence")
        if source_url and source_url.lower().startswith("mock://"):
            domain_source_valid = False
            if not allow_non_domain_smoke:
                raise ValueError("mock:// sources cannot be used as domain evidence")

        if source_type == SOURCE_TARGET_CAMERA_REPLAY and not source_path:
            raise ValueError("TARGET_CAMERA_REPLAY requires source_path")
        if source_type == SOURCE_LIVE and not source_url:
            raise ValueError("LIVE requires source_url")
        if source_type not in VALID_DOMAIN_SOURCE_TYPES and not (source_path or source_url):
            raise ValueError(f"{source_type} requires source_path or source_url")

        sample_fps = float(data.get("sample_fps", 2.0) or 2.0)
        if sample_fps <= 0:
            raise ValueError("sample_fps must be > 0")

        special_scenarios = _coerce_special_scenarios(data.get("special_scenarios"))
        unknown_special = [item for item in special_scenarios if item not in SPECIAL_SCENARIOS]
        if unknown_special:
            raise ValueError(f"unsupported special_scenarios: {', '.join(unknown_special)}")

        return cls(
            session_id=str(data["session_id"]).strip(),
            camera_id=str(data["camera_id"]).strip(),
            room_id=str(data["room_id"]).strip(),
            actor_id=str(data["actor_id"]).strip(),
            scenario_label=scenario_label,
            binary_ground_truth=binary_ground_truth,
            split=split,  # type: ignore[arg-type]
            source_type=source_type,
            recorded_at=_optional_str(data.get("recorded_at")),
            lighting=_optional_str(data.get("lighting")),
            distance_category=_optional_str(data.get("distance_category") or data.get("distance")),
            occlusion_level=_optional_str(data.get("occlusion_level") or data.get("occlusion")),
            camera_position_version=_optional_str(data.get("camera_position_version")),
            resolution=_optional_str(data.get("resolution")),
            source_width=_optional_int(data.get("source_width")),
            source_height=_optional_int(data.get("source_height")),
            source_path=source_path,
            source_url=source_url,
            sample_fps=sample_fps,
            input_policy=str(data.get("input_policy") or "FULL_FRAME_TRAIN_MATCHED").strip(),
            model_hash=_optional_str(data.get("model_hash")),
            special_scenarios=special_scenarios,
            domain_source_valid=domain_source_valid,
        )

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def load_session_manifest(path: str | Path, *, allow_non_domain_smoke: bool = False) -> list[DomainSession]:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    if manifest_path.suffix.lower() == ".csv":
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return [DomainSession.from_mapping(row, allow_non_domain_smoke=allow_non_domain_smoke) for row in rows]

    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        rows = payload.get("sessions")
        if rows is None:
            rows = [payload]
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("manifest must be a JSON array, a {sessions: [...]} object, or a CSV")
    return [DomainSession.from_mapping(row, allow_non_domain_smoke=allow_non_domain_smoke) for row in rows]


def validate_session_splits(sessions: Iterable[DomainSession]) -> None:
    splits_by_session: dict[str, set[str]] = {}
    for session in sessions:
        splits_by_session.setdefault(session.session_id, set()).add(session.split)
    overlapping = {
        session_id: sorted(splits)
        for session_id, splits in splits_by_session.items()
        if DOMAIN_CALIBRATION in splits and DOMAIN_ACCEPTANCE in splits
    }
    if overlapping:
        raise ValueError(f"session_id cannot appear in both calibration and acceptance: {overlapping}")


def build_split_manifest(sessions: Iterable[DomainSession]) -> dict[str, Any]:
    split_manifest = {
        "split_unit": "recording_session",
        "calibration_sessions": sorted(
            session.session_id for session in sessions if session.split == DOMAIN_CALIBRATION
        ),
        "acceptance_sessions": sorted(
            session.session_id for session in sessions if session.split == DOMAIN_ACCEPTANCE
        ),
    }
    canonical = json.dumps(split_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    split_manifest["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return split_manifest


def build_domain_frame_record(session: DomainSession, result: Any) -> dict[str, Any]:
    record = {
        "session": session.to_record(),
        "session_id": session.session_id,
        "camera_id": session.camera_id,
        "room_id": session.room_id,
        "actor_id": session.actor_id,
        "scenario_label": session.scenario_label,
        "binary_ground_truth": session.binary_ground_truth,
        "split": session.split,
        "source_type": session.source_type,
        "domain_source_valid": session.domain_source_valid,
        "special_scenarios": session.special_scenarios,
        "lighting": session.lighting,
        "distance_category": session.distance_category,
        "occlusion_level": session.occlusion_level,
        "camera_position_version": session.camera_position_version,
        "resolution": session.resolution,
        "source_width": session.source_width,
        "source_height": session.source_height,
        "result": result.to_record() if hasattr(result, "to_record") else dict(result),
    }
    result_payload = record["result"]
    for key in [
        "frame_id",
        "captured_at",
        "sampled_at",
        "inferred_at",
        "prediction",
        "fall_probability",
        "nofall_probability",
        "shadow_candidate_hint",
        "valid",
    ]:
        record[key] = result_payload.get(key)
    threshold = result_payload.get("threshold") or {}
    record["threshold"] = threshold.get("value")
    return record


def load_domain_frame_records(path: str | Path) -> list[dict[str, Any]]:
    root = Path(path)
    files: list[Path]
    if root.is_file():
        files = [root]
    elif root.is_dir():
        preferred = root / "domain_frame_results.jsonl"
        files = [preferred] if preferred.is_file() else sorted(root.rglob("*frame_results*.jsonl"))
    else:
        raise FileNotFoundError(root)

    records: list[dict[str, Any]] = []
    for file_path in files:
        with file_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(normalize_domain_frame_record(json.loads(stripped)))
                except Exception as exc:
                    raise ValueError(f"invalid JSONL record in {file_path}:{line_number}: {exc}") from exc
    return records


def normalize_domain_frame_record(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result") or {}
    session = record.get("session") or {}
    normalized = dict(record)
    for key in [
        "session_id",
        "camera_id",
        "room_id",
        "actor_id",
        "scenario_label",
        "binary_ground_truth",
        "split",
        "source_type",
        "domain_source_valid",
        "special_scenarios",
        "lighting",
        "distance_category",
        "occlusion_level",
        "input_policy",
        "model_hash",
        "camera_position_version",
        "resolution",
        "source_width",
        "source_height",
    ]:
        if normalized.get(key) is None and session.get(key) is not None:
            normalized[key] = session.get(key)
    for key in ["frame_id", "fall_probability", "nofall_probability", "prediction", "valid"]:
        if normalized.get(key) is None and result.get(key) is not None:
            normalized[key] = result.get(key)
    if normalized.get("threshold") is None:
        threshold = result.get("threshold") or {}
        normalized["threshold"] = threshold.get("value")
    normalized["fall_probability"] = _optional_float(normalized.get("fall_probability"))
    normalized["threshold"] = _optional_float(normalized.get("threshold"))
    normalized["domain_source_valid"] = bool(normalized.get("domain_source_valid", False))
    return normalized


def analyze_domain_evidence(
    records: list[dict[str, Any]],
    *,
    threshold: float,
    run_calibration_sweep: bool = True,
) -> dict[str, Any]:
    threshold = float(threshold)
    valid_records = [
        record
        for record in records
        if record.get("valid", True) is True
        and record.get("fall_probability") is not None
        and record.get("binary_ground_truth") in VALID_BINARY_GROUND_TRUTH
    ]
    validate_record_splits(valid_records)

    sessions = _session_summary(valid_records, threshold)
    scenario_stats = _group_probability_stats(valid_records, "scenario_label", threshold)
    distance_stats = _group_probability_stats(valid_records, "distance_category", threshold)
    person_scale_stats = _person_scale_report(valid_records)
    special_scenario_stats = _special_scenario_report(valid_records, threshold)
    acceptance_records = [record for record in valid_records if record.get("split") == DOMAIN_ACCEPTANCE]
    calibration_records = [record for record in valid_records if record.get("split") == DOMAIN_CALIBRATION]

    threshold_transfer = frame_level_metrics(acceptance_records, threshold)
    all_frame_metrics = frame_level_metrics(valid_records, threshold)
    hard_negative_records = [
        record
        for record in acceptance_records
        if record.get("scenario_label") in HARD_NEGATIVE_SCENARIOS
    ]
    hard_negative_metrics = frame_level_metrics(hard_negative_records, threshold)
    coverage = coverage_report(valid_records)
    gates = gate_report(
        valid_records,
        coverage,
        threshold_transfer,
        hard_negative_metrics,
    )
    calibration_sweep = None
    if run_calibration_sweep and calibration_records:
        calibration_sweep = threshold_sweep(calibration_records)

    return {
        "threshold": threshold,
        "record_count": len(records),
        "valid_frame_count": len(valid_records),
        "invalid_frame_count": len(records) - len(valid_records),
        "recording_session_count": len({record.get("session_id") for record in valid_records}),
        "source_types": sorted({str(record.get("source_type")) for record in valid_records if record.get("source_type")}),
        "domain_source_valid": all(bool(record.get("domain_source_valid")) for record in valid_records) if valid_records else False,
        "coverage": coverage,
        "frame_level_metrics_all": all_frame_metrics,
        "threshold_transfer_acceptance": threshold_transfer,
        "hard_negative_acceptance": {
            **hard_negative_metrics,
            "HARD_NEGATIVE_FALSE_POSITIVE_RATE": hard_negative_metrics.get("false_positive_rate"),
        },
        "scenario_probability_stats": scenario_stats,
        "distance_probability_stats": distance_stats,
        "person_scale_analysis": person_scale_stats,
        "special_scenario_analysis": special_scenario_stats,
        "clip_session_statistics": sessions,
        "calibration_threshold_sweep": calibration_sweep,
        "gates": gates,
    }


def validate_record_splits(records: Iterable[dict[str, Any]]) -> None:
    splits_by_session: dict[str, set[str]] = {}
    for record in records:
        session_id = str(record.get("session_id") or "")
        split = str(record.get("split") or "")
        if not session_id or split not in VALID_SPLITS:
            continue
        splits_by_session.setdefault(session_id, set()).add(split)
    overlapping = {
        session_id: sorted(splits)
        for session_id, splits in splits_by_session.items()
        if DOMAIN_CALIBRATION in splits and DOMAIN_ACCEPTANCE in splits
    }
    if overlapping:
        raise ValueError(f"session_id cannot appear in both calibration and acceptance: {overlapping}")


def coverage_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = {str(record.get("scenario_label")) for record in records if record.get("scenario_label")}
    splits = {str(record.get("split")) for record in records if record.get("split")}
    gt_counts = {
        GROUND_TRUTH_FALL: sum(1 for record in records if record.get("binary_ground_truth") == GROUND_TRUTH_FALL),
        GROUND_TRUTH_NOFALL: sum(1 for record in records if record.get("binary_ground_truth") == GROUND_TRUTH_NOFALL),
    }
    special = set()
    for record in records:
        special.update(record.get("special_scenarios") or [])
    missing = {
        "splits": sorted(VALID_SPLITS - splits),
        "core_nofall_scenarios": sorted(CORE_NOFALL_SCENARIOS - scenarios),
        "hard_negative_scenarios": sorted(REQUIRED_HARD_NEGATIVE_SCENARIOS - scenarios),
        "fallen_floor_scenarios": sorted(REQUIRED_FALL_SCENARIOS - scenarios),
        "special_scenarios": sorted(SPECIAL_SCENARIOS - special),
    }
    sufficient = (
        bool(records)
        and not missing["splits"]
        and not missing["core_nofall_scenarios"]
        and gt_counts[GROUND_TRUTH_FALL] > 0
        and gt_counts[GROUND_TRUTH_NOFALL] > 0
        and not missing["hard_negative_scenarios"]
        and not missing["fallen_floor_scenarios"]
    )
    return {
        "scenarios": sorted(scenarios),
        "splits": sorted(splits),
        "binary_ground_truth_frame_counts": gt_counts,
        "special_scenarios": sorted(special),
        "missing": missing,
        "sufficient_for_domain_dataset_ready": sufficient,
    }


def gate_report(
    records: list[dict[str, Any]],
    coverage: dict[str, Any],
    threshold_transfer: dict[str, Any],
    hard_negative_metrics: dict[str, Any],
) -> dict[str, Any]:
    no_target_data = not records or not all(bool(record.get("domain_source_valid")) for record in records)
    dataset_ready = bool(records) and not no_target_data and bool(coverage["sufficient_for_domain_dataset_ready"])
    transfer_evaluated = dataset_ready and threshold_transfer["support"] > 0
    recall = threshold_transfer.get("recall")
    hard_negative_fpr = hard_negative_metrics.get("false_positive_rate")

    domain_ready = False
    domain_block_reasons: list[str] = []
    if not dataset_ready:
        domain_block_reasons.append("DOMAIN_COLLECTION_BLOCKED_NO_TARGET_CAMERA_DATA" if no_target_data else "DOMAIN_COVERAGE_INSUFFICIENT")
    if not transfer_evaluated:
        domain_block_reasons.append("THRESHOLD_TRANSFER_NOT_RUN")
    if transfer_evaluated:
        if recall is None or recall < 0.85:
            domain_block_reasons.append("FALLEN_FLOOR_RECALL_INSUFFICIENT")
        if hard_negative_fpr is not None and hard_negative_fpr > 0.25:
            domain_block_reasons.append("HARD_NEGATIVE_FALSE_POSITIVE_RATE_HIGH")
        domain_ready = not domain_block_reasons

    p3_allowed = "NO"
    p3_reason = "not evaluable until target-camera domain data exists"
    if transfer_evaluated:
        if recall is not None and recall >= 0.80:
            p3_allowed = "YES"
            p3_reason = "fall recall is viable for first-stage screening; hard negatives can be handled by P3/P5 design"
        else:
            p3_reason = "first-stage fall recall is insufficient; fix binary/domain viability before P3"

    return {
        "Domain Dataset Gate": "POST_FALL_V2_DOMAIN_DATASET_READY" if dataset_ready else "POST_FALL_V2_DOMAIN_DATASET_BLOCKED",
        "Threshold Transfer Gate": (
            "POST_FALL_V2_THRESHOLD_TRANSFER_EVALUATED"
            if transfer_evaluated
            else "POST_FALL_V2_THRESHOLD_TRANSFER_NOT_RUN"
        ),
        "Domain Validation Gate": (
            "POST_FALL_V2_BINARY_DOMAIN_VALIDATION_READY"
            if domain_ready
            else "POST_FALL_V2_BINARY_DOMAIN_VALIDATION_BLOCKED"
        ),
        "P3_ALLOWED": p3_allowed,
        "p3_reason": p3_reason,
        "blocked_reasons": domain_block_reasons,
    }


def frame_level_metrics(records: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    y_true: list[int] = []
    y_score: list[float] = []
    for record in records:
        probability = _optional_float(record.get("fall_probability"))
        ground_truth = record.get("binary_ground_truth")
        if probability is None or ground_truth not in VALID_BINARY_GROUND_TRUTH:
            continue
        y_true.append(1 if ground_truth == GROUND_TRUTH_FALL else 0)
        y_score.append(probability)

    tp = fp = tn = fn = 0
    for target, score in zip(y_true, y_score):
        predicted = 1 if score >= threshold else 0
        if predicted == 1 and target == 1:
            tp += 1
        elif predicted == 1 and target == 0:
            fp += 1
        elif predicted == 0 and target == 0:
            tn += 1
        else:
            fn += 1

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    specificity = _safe_div(tn, tn + fp)
    fpr = _safe_div(fp, fp + tn)
    f1 = _safe_div(2 * precision * recall, precision + recall) if precision is not None and recall is not None else None

    return {
        "support": len(y_true),
        "positive_support": sum(y_true),
        "negative_support": len(y_true) - sum(y_true),
        "TP": tp,
        "FP": fp,
        "TN": tn,
        "FN": fn,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": fpr,
        "F1": f1,
        "ROC_AUC": roc_auc(y_true, y_score),
        "PR_AUC": pr_auc(y_true, y_score),
    }


def _special_scenario_report(records: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    report = {}
    for special in sorted(SPECIAL_SCENARIOS):
        groups: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if special in (record.get("special_scenarios") or []):
                groups.setdefault(str(record.get("session_id")), []).append(record)
        sessions = []
        all_probabilities: list[float] = []
        for session_id, group in sorted(groups.items()):
            ordered = sorted(group, key=lambda record: str(record.get("frame_id") or ""))
            probabilities = [
                _optional_float(record.get("fall_probability"))
                for record in ordered
                if _optional_float(record.get("fall_probability")) is not None
            ]
            if not probabilities:
                continue
            sample_fps = _session_sample_fps(ordered[0])
            first_hit_index = next(
                (index for index, value in enumerate(probabilities) if value >= threshold),
                None,
            )
            sessions.append(
                {
                    "session_id": session_id,
                    "frame_count": len(probabilities),
                    "first_sampled_frame_probability": probabilities[0],
                    "first_threshold_hit_time_seconds": (
                        first_hit_index / sample_fps if first_hit_index is not None else None
                    ),
                    "first_1s": probability_stats(probabilities[: max(1, round(sample_fps * 1))], threshold),
                    "first_2s": probability_stats(probabilities[: max(1, round(sample_fps * 2))], threshold),
                    "first_3s": probability_stats(probabilities[: max(1, round(sample_fps * 3))], threshold),
                }
            )
            all_probabilities.extend(probabilities)
        report[special] = {
            "session_count": len(sessions),
            "sessions": sessions,
            "overall": probability_stats(all_probabilities, threshold),
        }
    return report


def _person_scale_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = []
    for record in records:
        analysis_only = record.get("analysis_only") or {}
        if not analysis_only and isinstance(record.get("result"), dict):
            analysis_only = record["result"].get("analysis_only") or {}
        ratio = _optional_float(analysis_only.get("largest_person_area_ratio"))
        probability = _optional_float(record.get("fall_probability"))
        if ratio is not None and probability is not None:
            pairs.append({"largest_person_area_ratio": ratio, "fall_probability": probability})
    return {
        "available": bool(pairs),
        "count": len(pairs),
        "note": "analysis_only; YOLO/person scale is not a classifier precondition",
        "largest_person_area_ratio_vs_fall_probability": pairs,
    }


def threshold_sweep(records: list[dict[str, Any]]) -> dict[str, Any]:
    scores = sorted({_optional_float(record.get("fall_probability")) for record in records if record.get("fall_probability") is not None})
    thresholds = [score for score in scores if score is not None]
    if not thresholds:
        return {"support": 0, "DOMAIN_CANDIDATE_THRESHOLD_PROPOSAL": None}
    candidates = []
    for threshold in thresholds:
        metrics = frame_level_metrics(records, threshold)
        candidates.append({"threshold": threshold, **metrics})
    high_recall = sorted(
        candidates,
        key=lambda item: (
            -(item["recall"] if item["recall"] is not None else -1),
            item["false_positive_rate"] if item["false_positive_rate"] is not None else 1,
            item["threshold"],
        ),
    )[0]
    balanced = sorted(
        candidates,
        key=lambda item: (
            -_balanced_accuracy(item),
            item["false_positive_rate"] if item["false_positive_rate"] is not None else 1,
            item["threshold"],
        ),
    )[0]
    f1_best = sorted(
        candidates,
        key=lambda item: (
            -(item["F1"] if item["F1"] is not None else -1),
            item["false_positive_rate"] if item["false_positive_rate"] is not None else 1,
            item["threshold"],
        ),
    )[0]
    return {
        "support": len(records),
        "DOMAIN_CANDIDATE_THRESHOLD_PROPOSAL": {
            "high_recall_operating_point": high_recall,
            "balanced_operating_point": balanced,
            "f1_best_operating_point": f1_best,
        },
        "note": "calibration-only proposal; not a production threshold",
    }


def _session_summary(records: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record.get("session_id")), []).append(record)
    summaries = []
    for session_id, group in sorted(grouped.items()):
        probabilities = [_optional_float(record.get("fall_probability")) for record in group]
        values = [value for value in probabilities if value is not None]
        base = group[0]
        summaries.append(
            {
                "session_id": session_id,
                "camera_id": base.get("camera_id"),
                "camera_position_version": base.get("camera_position_version"),
                "scenario_label": base.get("scenario_label"),
                "binary_ground_truth": base.get("binary_ground_truth"),
                "split": base.get("split"),
                "frame_count": len(values),
                **probability_stats(values, threshold),
                "longest_consecutive_above_threshold": longest_consecutive(values, lambda value: value >= threshold),
                "longest_consecutive_below_threshold": longest_consecutive(values, lambda value: value < threshold),
            }
        )
    return summaries


def _group_probability_stats(records: list[dict[str, Any]], key: str, threshold: float) -> dict[str, Any]:
    grouped: dict[str, list[float]] = {}
    for record in records:
        group_key = record.get(key)
        value = _optional_float(record.get("fall_probability"))
        if group_key is None or value is None:
            continue
        grouped.setdefault(str(group_key), []).append(value)
    return {name: probability_stats(values, threshold) for name, values in sorted(grouped.items())}


def probability_stats(values: list[float], threshold: float) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "median": None,
            "max": None,
            "P90": None,
            "P95": None,
            "threshold_hit_ratio": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "mean": mean(values),
        "median": median(values),
        "max": max(values),
        "P90": percentile(values, 90),
        "P95": percentile(values, 95),
        "threshold_hit_ratio": _safe_div(sum(1 for value in values if value >= threshold), len(values)),
    }


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percentile_value / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def longest_consecutive(values: list[float], predicate: Any) -> int:
    best = 0
    current = 0
    for value in values:
        if predicate(value):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def roc_auc(y_true: list[int], y_score: list[float]) -> float | None:
    positives = [(score, index) for index, (target, score) in enumerate(zip(y_true, y_score)) if target == 1]
    negatives = [(score, index) for index, (target, score) in enumerate(zip(y_true, y_score)) if target == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    total = len(positives) * len(negatives)
    for positive_score, _ in positives:
        for negative_score, _ in negatives:
            if positive_score > negative_score:
                wins += 1.0
            elif positive_score == negative_score:
                wins += 0.5
    return wins / total


def pr_auc(y_true: list[int], y_score: list[float]) -> float | None:
    positive_count = sum(y_true)
    if positive_count == 0:
        return None
    pairs = sorted(zip(y_score, y_true), key=lambda item: item[0], reverse=True)
    tp = 0
    fp = 0
    last_recall = 0.0
    area = 0.0
    for _, target in pairs:
        if target == 1:
            tp += 1
        else:
            fp += 1
        precision = tp / (tp + fp)
        recall = tp / positive_count
        area += precision * max(0.0, recall - last_recall)
        last_recall = recall
    return area


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_markdown_report(analysis: dict[str, Any]) -> str:
    gates = analysis["gates"]
    coverage = analysis["coverage"]
    transfer = analysis["threshold_transfer_acceptance"]
    hard_negative = analysis["hard_negative_acceptance"]
    special = analysis.get("special_scenario_analysis") or {}
    lines = [
        "# Post-Fall V2 Current Camera Domain Evidence Report",
        "",
        "## Scope",
        "",
        "- Phase: P2.5_CURRENT_CAMERA_DOMAIN_EVIDENCE_COLLECTION",
        "- Algorithm changes: none",
        "- Runtime main-link integration: none",
        "- VLM / external POST / alert delivery: not called",
        "- Fixed threshold transfer value: " + str(analysis["threshold"]),
        "",
        "## Data Summary",
        "",
        f"- Recording sessions: {analysis['recording_session_count']}",
        f"- Valid frames: {analysis['valid_frame_count']}",
        f"- Source types: {', '.join(analysis['source_types']) if analysis['source_types'] else 'none'}",
        f"- Scenarios: {', '.join(coverage['scenarios']) if coverage['scenarios'] else 'none'}",
        f"- Splits: {', '.join(coverage['splits']) if coverage['splits'] else 'none'}",
        f"- Fall / noFall frames: {coverage['binary_ground_truth_frame_counts']['Fall']} / {coverage['binary_ground_truth_frame_counts']['noFall']}",
        f"- Special scenarios: {', '.join(coverage['special_scenarios']) if coverage['special_scenarios'] else 'none'}",
        "",
        "## Threshold Transfer",
        "",
        f"- Support: {transfer['support']}",
        f"- Precision: {_fmt(transfer['precision'])}",
        f"- Recall: {_fmt(transfer['recall'])}",
        f"- FPR: {_fmt(transfer['false_positive_rate'])}",
        f"- ROC-AUC: {_fmt(transfer['ROC_AUC'])}",
        f"- PR-AUC: {_fmt(transfer['PR_AUC'])}",
        f"- HARD_NEGATIVE_FALSE_POSITIVE_RATE: {_fmt(hard_negative['HARD_NEGATIVE_FALSE_POSITIVE_RATE'])}",
        "",
        "## Gates",
        "",
        f"- Domain Dataset Gate: {gates['Domain Dataset Gate']}",
        f"- Threshold Transfer Gate: {gates['Threshold Transfer Gate']}",
        f"- Domain Validation Gate: {gates['Domain Validation Gate']}",
        f"- P3_ALLOWED: {gates['P3_ALLOWED']}",
        f"- P3 reason: {gates['p3_reason']}",
        f"- Blocked reasons: {', '.join(gates['blocked_reasons']) if gates['blocked_reasons'] else 'none'}",
        "",
        "## Bootstrap / Reconnect",
        "",
    ]
    for name in sorted(SPECIAL_SCENARIOS):
        stats = special.get(name) or {}
        overall = stats.get("overall") or {}
        first_times = [
            session.get("first_threshold_hit_time_seconds")
            for session in stats.get("sessions", [])
            if session.get("first_threshold_hit_time_seconds") is not None
        ]
        first_hit = min(first_times) if first_times else None
        lines.append(
            f"- {name}: sessions={stats.get('session_count', 0)}, "
            f"first_hit_seconds={_fmt(first_hit)}, median={_fmt(overall.get('median'))}, "
            f"hit_ratio={_fmt(overall.get('threshold_hit_ratio'))}"
        )
    lines.extend([
        "",
        "## Missing Coverage",
        "",
    ])
    for key, values in coverage["missing"].items():
        lines.append(f"- {key}: {', '.join(values) if values else 'none'}")
    lines.extend(["", "## Scenario Probability Stats", ""])
    for scenario, stats in analysis["scenario_probability_stats"].items():
        lines.append(
            f"- {scenario}: count={stats['count']}, mean={_fmt(stats['mean'])}, "
            f"median={_fmt(stats['median'])}, P90={_fmt(stats['P90'])}, "
            f"P95={_fmt(stats['P95'])}, hit_ratio={_fmt(stats['threshold_hit_ratio'])}"
        )
    if not analysis["scenario_probability_stats"]:
        lines.append("- none")
    lines.extend(["", "## Clip Session Statistics", ""])
    for clip in analysis["clip_session_statistics"]:
        lines.append(
            f"- {clip['session_id']} ({clip['scenario_label']}, {clip['split']}): "
            f"frames={clip['frame_count']}, median={_fmt(clip['median'])}, "
            f"P95={_fmt(clip['P95'])}, hit_ratio={_fmt(clip['threshold_hit_ratio'])}, "
            f"longest_above={clip['longest_consecutive_above_threshold']}, "
            f"longest_below={clip['longest_consecutive_below_threshold']}"
        )
    if not analysis["clip_session_statistics"]:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _balanced_accuracy(metrics: dict[str, Any]) -> float:
    recall = metrics.get("recall")
    specificity = metrics.get("specificity")
    if recall is None or specificity is None:
        return -1.0
    return (recall + specificity) / 2.0


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _session_sample_fps(record: dict[str, Any]) -> float:
    session = record.get("session") or {}
    value = session.get("sample_fps") or record.get("sample_fps") or 2.0
    try:
        return max(0.01, float(value))
    except (TypeError, ValueError):
        return 2.0


def _coerce_special_scenarios(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
