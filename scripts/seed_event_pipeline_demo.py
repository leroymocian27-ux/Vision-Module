from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.events.archive import EventArchive
from app.core.config import Settings
from app.events.delivery import DeliveryOutbox
from app.events.outbox import SQLiteEventOutbox
from app.events.ring_frame_buffer import KeyframeSelection, RingFrame
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, FallEventRecord, TrustedEventResult

SCENARIOS = {
    "fall_candidate_support",
    "fallen_confirmed_high",
    "adl_suppressed_review",
    "missing_keyframes",
    "vlm_timeout_fallback",
    "vlm_invalid_json_fallback",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed one dev/demo-only event pipeline record.")
    parser.add_argument("--db", default="data/event_outbox.sqlite3", help="SQLite EventOutbox path used by the service.")
    parser.add_argument("--archive-dir", default="logs/event_archive", help="Event archive root used by the service.")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--incident-id", default=None)
    parser.add_argument("--event-type", choices=["fall_candidate", "fallen_confirmed"], default="fall_candidate")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default=None)
    parser.add_argument("--no-keyframes", action="store_true", help="Create JSON-only event with missing keyframes.")
    parser.add_argument("--dry-run", action="store_true", help="Print the demo event summary without writing DB/archive.")
    parser.add_argument("--clear-demo", action="store_true", help="Clear demo-* records and archive folders before seeding.")
    parser.add_argument("--delivery-db", default=None, help="Optional SQLite DeliveryOutbox path for service-level dry-run validation.")
    parser.add_argument("--seed-delivery-dry-run", action="store_true", help="Also create and dry-run a DeliveryOutbox record. Dev/demo only; never POSTs.")
    args = parser.parse_args()

    trigger = datetime.now(timezone.utc).replace(microsecond=0)
    scenario = args.scenario or ("fallen_confirmed_high" if args.event_type == "fallen_confirmed" else "fall_candidate_support")
    incident_id = args.incident_id or f"demo-{args.camera_id}-{trigger.strftime('%Y%m%d%H%M%S')}"
    profile = _scenario_profile(scenario, args.event_type)
    fall_state = profile["fall_state"]
    risk_level = profile["risk_level"]
    event_type = profile["event_type"]
    no_keyframes = bool(args.no_keyframes or scenario == "missing_keyframes")

    event = FallEventRecord(
        incident_id=incident_id,
        camera_id=args.camera_id,
        track_id=1,
        event_type=event_type,
        fall_state=fall_state,
        risk_level=risk_level,
        risk_score=profile["confidence"],
        trigger_frame_seq=100,
        trigger_timestamp=trigger.isoformat(),
        bbox=[100.0, 120.0, 310.0, 340.0],
        fall_probability=profile["fall_probability"],
        fall_evidence_score=profile["fall_evidence_score"],
        adl_suppression_score=profile["adl_suppression_score"],
        metadata={"dev_demo_seed": True, "scenario": scenario},
    )
    evidence = EvidencePackage(
        incident_id=incident_id,
        camera_id=args.camera_id,
        track_id=1,
        trigger_frame_seq=100,
        trigger_timestamp=event.trigger_timestamp,
        keyframes=[
            EvidenceKeyframe(role=_role(offset), offset_ms=offset, fall_state=fall_state)
            for offset in (-3000, -1000, 0, 1000, 3000, 5000)
        ],
        bbox_sequence=[event.bbox or []],
        fall_state_sequence=["standing", "falling", fall_state],
        fall_probability=profile["fall_probability"],
        fall_evidence_score=profile["fall_evidence_score"],
        adl_suppression_score=profile["adl_suppression_score"],
        decision_reason="dev_demo_seed_only",
        degradation_used=profile["degradation_used"] + ([] if not no_keyframes else ["missing_demo_keyframes"]),
    )
    semantics = EventSemantics(
        incident_id=incident_id,
        motion={"main_transition": "standing_to_low_posture", "vertical_drop_detected": True},
        posture={"pre_state": "standing", "trigger_state": "falling", "post_state": "low_posture"},
        evidence={
            "fall_probability": profile["fall_probability"],
            "fall_evidence_score": profile["fall_evidence_score"],
            "adl_suppression_score": profile["adl_suppression_score"],
        },
        risk={"event_type": event_type, "risk_level": risk_level, "confidence": profile["confidence"], "decision": profile["decision"]},
    )
    trusted = TrustedEventResult(
        incident_id=incident_id,
        support_fall_alarm=profile["support_fall_alarm"],
        final_event_type=event_type,
        final_risk_level=risk_level,
        confidence=profile["confidence"],
        explanation=f"Dev/demo synthetic scenario {scenario} for validating event archive and keyframe UI.",
        alarm_title=profile["alarm_title"],
        alarm_body=profile["alarm_body"],
        recommended_action=profile["recommended_action"],
        review_result="demo_seed_rule_only",
        degradation_used=list(evidence.degradation_used),
    )
    if args.dry_run:
        print(f"dry-run incident_id={incident_id} scenario={scenario}")
        print(f"would_write_db={Path(args.db).resolve()}")
        print(f"would_write_archive={Path(args.archive_dir).resolve()}")
        print("dev/demo only: no DB/archive writes and no main-system POST")
        return

    if args.clear_demo:
        _clear_demo(args.db, args.archive_dir)

    selections = [] if no_keyframes else _demo_selections(args.camera_id, trigger)
    archive = EventArchive(args.archive_dir, enabled=True)
    archive_result = archive.archive(evidence, selections, semantics, trusted)
    archived_evidence = archive_result.evidence if archive_result is not None else evidence

    outbox = SQLiteEventOutbox(args.db)
    outbox.add_event(event)
    outbox.mark_evidence_ready(incident_id, archived_evidence)
    outbox.mark_semantic_ready(incident_id, semantics)
    outbox.mark_reviewed(incident_id, trusted)
    outbox.mark_delivery_pending(incident_id)
    if archive_result is not None:
        outbox.mark_archive(incident_id, archive_result.archive_path, archive_result.summary)
    delivery_status = None
    if args.seed_delivery_dry_run:
        delivery_path = args.delivery_db or "data/event_delivery_outbox.sqlite3"
        delivery_outbox = DeliveryOutbox(
            Settings(
                event_delivery_enabled=True,
                event_delivery_mode="dry_run",
                event_delivery_backend="sqlite",
                event_delivery_sqlite_path=delivery_path,
                event_delivery_target_url="",
            )
        )
        delivery = delivery_outbox.enqueue(trusted, archived_evidence, semantics)
        delivered = delivery_outbox.deliver(delivery.delivery_id)
        delivery_status = delivered.delivery_status if delivered is not None else delivery.delivery_status

    print(f"seeded incident_id={incident_id}")
    print(f"scenario={scenario}")
    print(f"event_outbox_sqlite_path={Path(args.db).resolve()}")
    print(f"event_archive_dir={Path(args.archive_dir).resolve()}")
    print(f"check_latest=/events/latest?camera_id={args.camera_id}")
    print(f"check_detail=/events/{incident_id}")
    print(f"check_keyframe=/events/{incident_id}/keyframes/t0")
    if args.seed_delivery_dry_run:
        print(f"event_delivery_sqlite_path={Path(args.delivery_db or 'data/event_delivery_outbox.sqlite3').resolve()}")
        print(f"delivery_status={delivery_status}")
    print("dev/demo only: no main-system POST was sent")


def _scenario_profile(scenario: str, fallback_event_type: str) -> dict:
    event_type = "fallen_confirmed" if scenario == "fallen_confirmed_high" else fallback_event_type
    if scenario == "fallen_confirmed_high":
        return {
            "event_type": "fallen_confirmed",
            "fall_state": "fallen_confirmed",
            "risk_level": "critical",
            "confidence": 0.93,
            "fall_probability": 0.93,
            "fall_evidence_score": 0.91,
            "adl_suppression_score": 0.08,
            "decision": "urgent_attention",
            "support_fall_alarm": True,
            "degradation_used": [],
            "alarm_title": "Demo confirmed fall",
            "alarm_body": "Synthetic confirmed fall event for frontend review only.",
            "recommended_action": "Confirm onsite and review live stream. Demo only.",
        }
    if scenario == "adl_suppressed_review":
        return {
            "event_type": "fall_candidate",
            "fall_state": "fallen_candidate",
            "risk_level": "medium",
            "confidence": 0.72,
            "fall_probability": 0.74,
            "fall_evidence_score": 0.7,
            "adl_suppression_score": 0.88,
            "decision": "need_review",
            "support_fall_alarm": False,
            "degradation_used": [],
            "alarm_title": "Demo review required",
            "alarm_body": "Synthetic ADL-suppressed event for frontend review only.",
            "recommended_action": "Review keyframes before treating as a fall alarm. Demo only.",
        }
    degradation = []
    if scenario == "vlm_timeout_fallback":
        degradation = ["vlm_timeout"]
    elif scenario == "vlm_invalid_json_fallback":
        degradation = ["vlm_invalid_json"]
    elif scenario == "missing_keyframes":
        degradation = ["missing_demo_keyframes"]
    return {
        "event_type": event_type if event_type in {"fall_candidate", "fallen_confirmed"} else "fall_candidate",
        "fall_state": "fallen_candidate",
        "risk_level": "high",
        "confidence": 0.86,
        "fall_probability": 0.86,
        "fall_evidence_score": 0.84,
        "adl_suppression_score": 0.12,
        "decision": "need_attention",
        "support_fall_alarm": True,
        "degradation_used": degradation,
        "alarm_title": "Demo fall candidate",
        "alarm_body": "Synthetic fall candidate event for frontend review only.",
        "recommended_action": "Review demo timeline and live stream. Demo only.",
    }


def _clear_demo(db_path: str, archive_dir: str) -> None:
    path = Path(db_path)
    if path.exists():
        with sqlite3.connect(str(path)) as conn:
            conn.execute("DELETE FROM event_outbox WHERE incident_id LIKE 'demo-%'")
            conn.commit()
    root = Path(archive_dir)
    if root.exists():
        for camera_dir in root.iterdir():
            if not camera_dir.is_dir():
                continue
            for incident_dir in camera_dir.iterdir():
                if incident_dir.is_dir() and incident_dir.name.startswith("demo-"):
                    shutil.rmtree(incident_dir, ignore_errors=True)


def _demo_selections(camera_id: str, trigger: datetime) -> list[KeyframeSelection]:
    selections: list[KeyframeSelection] = []
    for index, offset in enumerate((-3000, -1000, 0, 1000, 3000, 5000)):
        timestamp = trigger + timedelta(milliseconds=offset)
        frame = _demo_frame(index, _label(offset))
        selections.append(
            KeyframeSelection(
                role=_role(offset),
                offset_ms=offset,
                frame=RingFrame(camera_id, 100 + index, timestamp.isoformat(), frame),
            )
        )
    return selections


def _demo_frame(index: int, label: str) -> np.ndarray:
    image = np.zeros((180, 260, 3), dtype=np.uint8)
    image[:, :] = (40 + index * 24, 80 + index * 10, 150)
    import cv2

    cv2.putText(image, label, (20, 58), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(image, "DEMO ONLY", (20, 132), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    return image


def _role(offset_ms: int) -> str:
    if offset_ms <= -2000:
        return "pre_context"
    if offset_ms < 0:
        return "pre_fall"
    if offset_ms == 0:
        return "trigger"
    if offset_ms < 3000:
        return "post_fall"
    return "post_check"


def _label(offset_ms: int) -> str:
    if offset_ms == 0:
        return "T0"
    seconds = abs(offset_ms) // 1000
    return f"T-{seconds}s" if offset_ms < 0 else f"T+{seconds}s"


if __name__ == "__main__":
    main()
