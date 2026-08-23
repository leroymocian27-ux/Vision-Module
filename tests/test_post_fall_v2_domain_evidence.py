from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.post_fall_v2.domain_evidence import (
    DOMAIN_ACCEPTANCE,
    DOMAIN_CALIBRATION,
    GROUND_TRUTH_FALL,
    GROUND_TRUTH_NOFALL,
    SOURCE_NON_DOMAIN_SMOKE,
    SOURCE_TARGET_CAMERA_REPLAY,
    DomainSession,
    analyze_domain_evidence,
    build_split_manifest,
    load_domain_frame_records,
    load_session_manifest,
    longest_consecutive,
    render_markdown_report,
    threshold_sweep,
    validate_record_splits,
    validate_session_splits,
)


THRESHOLD = 0.3979087471961975


def session_payload(**overrides):
    payload = {
        "session_id": "session_001",
        "camera_id": "camera_01",
        "room_id": "room_01",
        "actor_id": "actor_01",
        "scenario_label": "lying_bed",
        "binary_ground_truth": GROUND_TRUTH_NOFALL,
        "split": DOMAIN_ACCEPTANCE,
        "source_type": SOURCE_TARGET_CAMERA_REPLAY,
        "source_path": "recordings/session_001.mp4",
        "sample_fps": 2.0,
        "distance_category": "medium",
        "camera_position_version": "CAM_POS_V1",
        "resolution": "2304x1296",
        "source_width": 2304,
        "source_height": 1296,
    }
    payload.update(overrides)
    return payload


def frame(
    session_id: str,
    scenario_label: str,
    binary_ground_truth: str,
    probability: float,
    *,
    split: str = DOMAIN_ACCEPTANCE,
    domain_source_valid: bool = True,
    distance_category: str = "medium",
    special_scenarios: list[str] | None = None,
):
    return {
        "session_id": session_id,
        "camera_id": "camera_01",
        "room_id": "room_01",
        "actor_id": "actor_01",
        "scenario_label": scenario_label,
        "binary_ground_truth": binary_ground_truth,
        "split": split,
        "source_type": SOURCE_TARGET_CAMERA_REPLAY,
        "domain_source_valid": domain_source_valid,
        "distance_category": distance_category,
        "special_scenarios": special_scenarios or [],
        "frame_id": f"{session_id}_0001",
        "fall_probability": probability,
        "nofall_probability": 1.0 - probability,
        "valid": True,
    }


def complete_domain_records() -> list[dict]:
    records = [
        frame("cal_standing", "standing", GROUND_TRUTH_NOFALL, 0.01, split=DOMAIN_CALIBRATION),
        frame("cal_sitting", "sitting", GROUND_TRUTH_NOFALL, 0.02, split=DOMAIN_CALIBRATION),
        frame("cal_walking", "walking", GROUND_TRUTH_NOFALL, 0.03, split=DOMAIN_CALIBRATION),
        frame("cal_bending", "bending", GROUND_TRUTH_NOFALL, 0.20, split=DOMAIN_CALIBRATION),
        frame("cal_bed", "lying_bed", GROUND_TRUTH_NOFALL, 0.70, split=DOMAIN_CALIBRATION),
        frame("cal_sofa", "lying_sofa", GROUND_TRUTH_NOFALL, 0.72, split=DOMAIN_CALIBRATION),
        frame("cal_floor", "lying_floor_normal", GROUND_TRUTH_NOFALL, 0.65, split=DOMAIN_CALIBRATION),
        frame("cal_exercise", "exercise_floor", GROUND_TRUTH_NOFALL, 0.55, split=DOMAIN_CALIBRATION),
        frame("cal_fall", "fallen_floor_supine", GROUND_TRUTH_FALL, 0.95, split=DOMAIN_CALIBRATION),
        frame("acc_standing", "standing", GROUND_TRUTH_NOFALL, 0.02),
        frame("acc_sitting", "sitting", GROUND_TRUTH_NOFALL, 0.03),
        frame("acc_walking", "walking", GROUND_TRUTH_NOFALL, 0.04),
        frame("acc_bending", "bending", GROUND_TRUTH_NOFALL, 0.30),
        frame("acc_bed", "lying_bed", GROUND_TRUTH_NOFALL, 0.80),
        frame("acc_sofa", "lying_sofa", GROUND_TRUTH_NOFALL, 0.81),
        frame("acc_floor", "lying_floor_normal", GROUND_TRUTH_NOFALL, 0.82),
        frame("acc_exercise", "exercise_floor", GROUND_TRUTH_NOFALL, 0.83),
        frame("acc_fall_supine", "fallen_floor_supine", GROUND_TRUTH_FALL, 0.90, special_scenarios=["POST_FALL_BOOTSTRAP_SCENARIO"]),
        frame("acc_fall_prone", "fallen_floor_prone", GROUND_TRUTH_FALL, 0.91),
        frame("acc_fall_side", "fallen_floor_side", GROUND_TRUTH_FALL, 0.92, special_scenarios=["POST_FALL_RECONNECT_SCENARIO"]),
    ]
    return records


def test_manifest_validates_scenario_ground_truth_and_source() -> None:
    session = DomainSession.from_mapping(session_payload())
    assert session.scenario_label == "lying_bed"
    assert session.binary_ground_truth == GROUND_TRUTH_NOFALL
    assert session.domain_source_valid is True

    with pytest.raises(ValueError, match="binary_ground_truth mismatch"):
        DomainSession.from_mapping(session_payload(binary_ground_truth=GROUND_TRUTH_FALL))

    with pytest.raises(ValueError, match="not valid domain evidence"):
        DomainSession.from_mapping(session_payload(source_type=SOURCE_NON_DOMAIN_SMOKE))

    smoke = DomainSession.from_mapping(
        session_payload(source_type=SOURCE_NON_DOMAIN_SMOKE),
        allow_non_domain_smoke=True,
    )
    assert smoke.domain_source_valid is False


def test_json_manifest_and_session_split_validation(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sessions": [
                    session_payload(session_id="same", split=DOMAIN_CALIBRATION),
                    session_payload(session_id="same", split=DOMAIN_ACCEPTANCE),
                ]
            }
        ),
        encoding="utf-8",
    )
    sessions = load_session_manifest(manifest)
    with pytest.raises(ValueError, match="both calibration and acceptance"):
        validate_session_splits(sessions)


def test_manifest_alias_fields_and_split_manifest_hash_are_stable() -> None:
    session = DomainSession.from_mapping(
        session_payload(distance_category=None, distance="far", occlusion="partial")
    )
    assert session.distance_category == "far"
    assert session.occlusion_level == "partial"
    assert session.camera_position_version == "CAM_POS_V1"
    assert session.source_width == 2304

    split_manifest = build_split_manifest(
        [
            DomainSession.from_mapping(session_payload(session_id="cal_001", split=DOMAIN_CALIBRATION)),
            DomainSession.from_mapping(session_payload(session_id="acc_001", split=DOMAIN_ACCEPTANCE)),
        ]
    )
    assert split_manifest["split_unit"] == "recording_session"
    assert split_manifest["calibration_sessions"] == ["cal_001"]
    assert split_manifest["acceptance_sessions"] == ["acc_001"]
    assert len(split_manifest["sha256"]) == 64


def test_record_split_validation_rejects_frame_level_leakage() -> None:
    records = [
        frame("same_session", "standing", GROUND_TRUTH_NOFALL, 0.01, split=DOMAIN_CALIBRATION),
        frame("same_session", "standing", GROUND_TRUTH_NOFALL, 0.02, split=DOMAIN_ACCEPTANCE),
    ]
    with pytest.raises(ValueError, match="both calibration and acceptance"):
        validate_record_splits(records)


def test_clip_statistics_and_threshold_transfer_with_hard_negative_gate() -> None:
    analysis = analyze_domain_evidence(complete_domain_records(), threshold=THRESHOLD)

    transfer = analysis["threshold_transfer_acceptance"]
    assert transfer["support"] == 11
    assert transfer["TP"] == 3
    assert transfer["FP"] == 4
    assert transfer["recall"] == 1.0
    assert analysis["hard_negative_acceptance"]["HARD_NEGATIVE_FALSE_POSITIVE_RATE"] == 1.0
    assert analysis["gates"]["Domain Dataset Gate"] == "POST_FALL_V2_DOMAIN_DATASET_READY"
    assert analysis["gates"]["Threshold Transfer Gate"] == "POST_FALL_V2_THRESHOLD_TRANSFER_EVALUATED"
    assert analysis["gates"]["Domain Validation Gate"] == "POST_FALL_V2_BINARY_DOMAIN_VALIDATION_BLOCKED"
    assert analysis["gates"]["P3_ALLOWED"] == "YES"

    bed_stats = analysis["scenario_probability_stats"]["lying_bed"]
    assert bed_stats["threshold_hit_ratio"] == 1.0
    assert analysis["distance_probability_stats"]["medium"]["count"] == len(complete_domain_records())
    bootstrap = analysis["special_scenario_analysis"]["POST_FALL_BOOTSTRAP_SCENARIO"]
    assert bootstrap["session_count"] == 1
    assert bootstrap["sessions"][0]["first_sampled_frame_probability"] == 0.90
    assert bootstrap["sessions"][0]["first_threshold_hit_time_seconds"] == 0.0


def test_empty_or_non_domain_data_keeps_domain_blocked() -> None:
    empty = analyze_domain_evidence([], threshold=THRESHOLD)
    assert empty["gates"]["Domain Dataset Gate"] == "POST_FALL_V2_DOMAIN_DATASET_BLOCKED"
    assert empty["gates"]["Threshold Transfer Gate"] == "POST_FALL_V2_THRESHOLD_TRANSFER_NOT_RUN"
    assert empty["gates"]["Domain Validation Gate"] == "POST_FALL_V2_BINARY_DOMAIN_VALIDATION_BLOCKED"
    assert empty["gates"]["P3_ALLOWED"] == "NO"

    non_domain = complete_domain_records()
    for record in non_domain:
        record["domain_source_valid"] = False
    blocked = analyze_domain_evidence(non_domain, threshold=THRESHOLD)
    assert "DOMAIN_COLLECTION_BLOCKED_NO_TARGET_CAMERA_DATA" in blocked["gates"]["blocked_reasons"]


def test_consecutive_stats_and_calibration_only_threshold_sweep() -> None:
    assert longest_consecutive([0.1, 0.5, 0.6, 0.2, 0.8], lambda value: value >= THRESHOLD) == 2
    records = [
        frame("cal_n", "standing", GROUND_TRUTH_NOFALL, 0.1, split=DOMAIN_CALIBRATION),
        frame("cal_p", "fallen_floor_supine", GROUND_TRUTH_FALL, 0.6, split=DOMAIN_CALIBRATION),
        frame("acc_p", "fallen_floor_supine", GROUND_TRUTH_FALL, 0.99, split=DOMAIN_ACCEPTANCE),
    ]
    sweep = threshold_sweep([record for record in records if record["split"] == DOMAIN_CALIBRATION])
    proposal = sweep["DOMAIN_CANDIDATE_THRESHOLD_PROPOSAL"]
    proposed_thresholds = {
        proposal["high_recall_operating_point"]["threshold"],
        proposal["balanced_operating_point"]["threshold"],
        proposal["f1_best_operating_point"]["threshold"],
    }
    assert proposed_thresholds <= {0.1, 0.6}
    assert 0.99 not in proposed_thresholds


def test_jsonl_loading_and_markdown_serialization(tmp_path: Path) -> None:
    path = tmp_path / "domain_frame_results.jsonl"
    path.write_text(
        "\n".join(json.dumps(record) for record in complete_domain_records()[:2]),
        encoding="utf-8",
    )
    records = load_domain_frame_records(path)
    analysis = analyze_domain_evidence(records, threshold=THRESHOLD)
    markdown = render_markdown_report(analysis)

    assert len(records) == 2
    assert "# Post-Fall V2 Current Camera Domain Evidence Report" in markdown
    assert "POST_FALL_V2_DOMAIN_DATASET_BLOCKED" in markdown
