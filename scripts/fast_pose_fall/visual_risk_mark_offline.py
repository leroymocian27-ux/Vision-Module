from __future__ import annotations

from typing import Any


MARK_ORDER = [
    "MARK_0_NORMAL",
    "MARK_1_LOW_CONFIDENCE",
    "MARK_2_ABNORMAL_POSTURE",
    "MARK_3_FALL_SUSPECTED",
    "MARK_4_FALL_CANDIDATE",
    "MARK_5_FALL_CONFIRMED",
]

RISK_LEVEL = {
    "MARK_0_NORMAL": "normal",
    "MARK_1_LOW_CONFIDENCE": "low",
    "MARK_2_ABNORMAL_POSTURE": "low",
    "MARK_3_FALL_SUSPECTED": "medium",
    "MARK_4_FALL_CANDIDATE": "high",
    "MARK_5_FALL_CONFIRMED": "critical",
}


def _float(features: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        value = features.get(name)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _tags(features: dict[str, Any]) -> list[str]:
    raw = features.get("scene_tags") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.replace("|", ",").split(",") if part.strip()]
    return [str(item).lower() for item in raw]


def _has_any(tags: list[str], *needles: str) -> bool:
    text = " ".join(tags)
    return any(needle in text for needle in needles)


def _cap_mark(mark: str, cap: str) -> str:
    return MARK_ORDER[min(MARK_ORDER.index(mark), MARK_ORDER.index(cap))]


def assign_visual_risk_mark(features: dict[str, Any]) -> dict[str, Any]:
    """Assign an offline-only Visual Risk Mark from aggregated or frame-level features.

    This module is intentionally independent from the production runtime pipeline. It
    is for dataset review and threshold drafting only.
    """

    tags = _tags(features)
    fall_score = _float(features, "max_fall_score", "fall_score")
    person_confidence = _float(features, "max_person_confidence", "person_confidence", default=0.5)
    aspect_ratio = _float(features, "max_aspect_ratio", "bbox_aspect_ratio")
    recent_descent = _float(features, "max_center_y_delta", "bbox_center_y_delta")
    velocity_y = _float(features, "max_velocity_y", "velocity_y")
    track_age = _float(features, "max_track_age_sec", "track_age_sec")
    stillness = _float(features, "max_stillness_duration_sec", "stillness_duration_sec")
    first_threshold_time = features.get("first_threshold_time_sec")
    try:
        first_threshold_time = float(first_threshold_time)
    except (TypeError, ValueError):
        first_threshold_time = None

    has_track = bool(features.get("has_reliable_person_track", True))
    posture_evidence = aspect_ratio >= 0.72
    descent_evidence = recent_descent >= 14.0 or velocity_y >= 60.0
    strong_descent = recent_descent >= 28.0 or velocity_y >= 120.0
    persistence = track_age >= 1.5 and stillness >= 1.5
    reasons: list[str] = []
    downgraded = False

    if fall_score < 0.25 and not posture_evidence and not descent_evidence:
        mark = "MARK_0_NORMAL"
        reasons.append("low fall_score and no abnormal bbox motion")
    elif fall_score < 0.40 or person_confidence < 0.20 or not has_track:
        mark = "MARK_1_LOW_CONFIDENCE"
        if fall_score < 0.40:
            reasons.append("low fall_score")
        if person_confidence < 0.20:
            reasons.append("low person confidence")
        if not has_track:
            reasons.append("no reliable person track")
    elif posture_evidence or descent_evidence:
        mark = "MARK_2_ABNORMAL_POSTURE"
        reasons.append("abnormal posture or bbox motion")
    else:
        mark = "MARK_1_LOW_CONFIDENCE"
        reasons.append("moderate score without posture/descent evidence")

    if fall_score >= 0.54 and (posture_evidence or descent_evidence):
        mark = "MARK_3_FALL_SUSPECTED"
        reasons.append("fall_score with posture/descent evidence")
    if fall_score >= 0.62 and (strong_descent or stillness >= 1.0):
        mark = "MARK_4_FALL_CANDIDATE"
        reasons.append("candidate score with strong descent or stillness")
    if fall_score >= 0.62 and strong_descent and persistence:
        mark = "MARK_5_FALL_CONFIRMED"
        reasons.append("candidate persisted with stillness")

    # Hard-negative safety gates.
    if _has_any(tags, "no_person"):
        mark = _cap_mark(mark, "MARK_2_ABNORMAL_POSTURE")
        downgraded = True
        reasons.append("no_person scene tag downgrade")

    if _has_any(tags, "sitting", "squat") and fall_score < 0.82:
        mark = _cap_mark(mark, "MARK_3_FALL_SUSPECTED")
        downgraded = True
        reasons.append("sitting/squat hard-negative downgrade below high confidence")

    if _has_any(tags, "lying"):
        lying_transition = (
            first_threshold_time is not None
            and first_threshold_time > 1.0
            and recent_descent >= 160.0
            and velocity_y >= 500.0
            and fall_score >= 0.82
        )
        if not lying_transition:
            mark = _cap_mark(mark, "MARK_3_FALL_SUSPECTED")
            downgraded = True
            reasons.append("lying posture without confirmed fall transition")
        else:
            reasons.append("lying transition substitute evidence present")

    if _has_any(tags, "walking"):
        if stillness < 1.5 or not _has_any(tags, "fallen_hold"):
            mark = _cap_mark(mark, "MARK_3_FALL_SUSPECTED")
            downgraded = True
            reasons.append("walking scene without fallen-hold stillness downgrade")

    if _has_any(tags, "partial_limb", "edge_person", "occlusion"):
        strong_manual_like_evidence = fall_score >= 0.90 and recent_descent >= 180.0 and velocity_y >= 600.0
        if not strong_manual_like_evidence:
            mark = _cap_mark(mark, "MARK_2_ABNORMAL_POSTURE")
            downgraded = True
            reasons.append("partial/edge/occlusion conservative downgrade")

    predicted_fall = mark in {"MARK_4_FALL_CANDIDATE", "MARK_5_FALL_CONFIRMED"}
    if downgraded and mark not in {"MARK_4_FALL_CANDIDATE", "MARK_5_FALL_CONFIRMED"}:
        predicted_fall = False

    should_confirm_fall = mark == "MARK_5_FALL_CONFIRMED" and predicted_fall
    return {
        "visual_risk_mark": mark,
        "risk_level": RISK_LEVEL[mark],
        "predicted_fall": predicted_fall,
        "should_confirm_fall": should_confirm_fall,
        "should_send_alert": False,
        "downgraded": downgraded,
        "reasons": reasons,
    }
