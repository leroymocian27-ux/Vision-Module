from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATCH_ID = "batch_031_hardcase_audit"
BATCH_DIR = ROOT / "datasets" / "fall_hint_v2_raw" / BATCH_ID
VALIDATION_PATH = BATCH_DIR / "meta" / "review_validation_summary.json"
PIPELINE_DOC = ROOT / "docs" / "FALL_HINT_BATCH_031_POSTREVIEW_WORKFLOW_2026-07-04.md"


def load_validation_summary() -> dict[str, object]:
    if not VALIDATION_PATH.exists():
        return {
            "batch_id": BATCH_ID,
            "batch_dir": str(BATCH_DIR),
            "frame_count": 0,
            "status_counts": {},
            "reviewed_valid_count": 0,
            "invalid_review_items": 0,
            "reviewed_class_counts": {},
            "ready_for_merge": False,
        }
    return json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))


def build_status_report() -> dict[str, object]:
    validation = load_validation_summary()
    frame_count = int(validation.get("frame_count") or 0)
    status_counts = validation.get("status_counts") or {}
    reviewed = int(validation.get("reviewed_valid_count") or 0)
    invalid = int(validation.get("invalid_review_items") or 0)
    ready = bool(validation.get("ready_for_merge") is True)
    remaining = max(0, frame_count - reviewed)
    next_action = (
        "run scripts/run_fall_hint_batch031_refine_pipeline.py --overwrite-merged"
        if ready
        else "continue reviewing batch_031_hardcase_audit in http://127.0.0.1:8082/ until Reviewed 120/120"
    )
    return {
        "batch_id": BATCH_ID,
        "batch_dir": str(BATCH_DIR),
        "progress": {
            "frame_count": frame_count,
            "reviewed_valid": reviewed,
            "draft_or_unreviewed": int(status_counts.get("draft") or remaining),
            "remaining": remaining,
            "invalid_review_items": invalid,
        },
        "status_counts": status_counts,
        "ready_for_merge": ready,
        "next_action": next_action,
        "help": {
            "labeler_url": "http://127.0.0.1:8082/",
            "workflow_doc": str(PIPELINE_DOC),
            "save_shortcut": "Ctrl/Cmd+S",
            "save_next_draft_shortcut": "Shift+S",
        },
    }


def main() -> int:
    print(json.dumps(build_status_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
