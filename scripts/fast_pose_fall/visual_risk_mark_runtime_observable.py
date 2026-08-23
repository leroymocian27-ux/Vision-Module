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


def _cap_mark(mark: str, cap: str) -> str:
    return MARK_ORDER[min(MARK_ORDER.index(mark), MARK_ORDER.index(cap))]


def assign_runtime_observable_risk_mark(features: dict[str, Any]) -> dict[str, Any]:
    """Assign an offline-audited, runtime-observable Visual Risk Mark.

    The rule intentionally reads only live numeric/motion fields or aggregates
    derived from them. Review metadata is intentionally ignored.
    """

    fall_score = _float(features, "max_fall_score", "fall_score")
    person_confidence = _float(features, "max_person_confidence", "person_confidence", default=0.0)
    bbox_width = _float(features, "max_bbox_width", "bbox_width")
    bbox_height = _float(features, "max_bbox_height", "bbox_height")
    aspect_ratio = _float(features, "max_aspect_ratio", "bbox_aspect_ratio")
    center_y_delta = _float(features, "max_center_y_delta", "bbox_center_y_delta")
    height_delta = _float(features, "max_height_delta", "bbox_height_delta")
    velocity_y = _float(features, "max_velocity_y", "velocity_y")
    speed = _float(features, "mean_speed", "speed")
    max_speed = _float(features, "max_speed", "speed")
    track_age = _float(features, "max_track_age_sec", "track_age_sec")
    stillness = _float(features, "max_stillness_duration_sec", "stillness_duration_sec")
    first_threshold_time = features.get("first_threshold_time_sec")
    try:
        first_threshold_time = float(first_threshold_time)
    except (TypeError, ValueError):
        first_threshold_time = None

    is_low_confidence_person = person_confidence < 0.20
    track_is_stable = track_age >= 1.0 and person_confidence >= 0.20
    has_recent_descent = center_y_delta >= 80.0 and velocity_y >= 300.0
    has_strong_transition = center_y_delta >= 160.0 and velocity_y >= 500.0
    is_fast_vertical_motion = velocity_y >= 300.0
    is_horizontal_posture = aspect_ratio >= 2.5 or (bbox_height > 0.0 and bbox_width / bbox_height >= 2.5)
    has_fallen_hold_stillness = track_age >= 1.5 and stillness >= 1.5
    is_moving_continuously = (speed >= 140.0 or max_speed >= 400.0) and stillness < 1.5
    is_static_lying_like = is_horizontal_posture and stillness >= 1.5 and speed < 80.0
    transition_window_ok = first_threshold_time is None or 2.0 <= first_threshold_time <= 9.0

    reasons: list[str] = []
    downgraded = False

    if fall_score < 0.25 and not has_recent_descent and not is_horizontal_posture:
        mark = "MARK_0_NORMAL"
        reasons.append("low fall score and no runtime abnormal motion")
    elif fall_score < 0.40 or is_low_confidence_person or not track_is_stable:
        mark = "MARK_1_LOW_CONFIDENCE"
        if fall_score < 0.40:
            reasons.append("low fall score")
        if is_low_confidence_person:
            reasons.append("low person confidence")
        if not track_is_stable:
            reasons.append("unstable or short track")
    elif is_horizontal_posture or center_y_delta >= 14.0 or height_delta >= 60.0:
        mark = "MARK_2_ABNORMAL_POSTURE"
        reasons.append("runtime posture or bbox motion abnormality")
    else:
        mark = "MARK_1_LOW_CONFIDENCE"
        reasons.append("moderate score without runtime posture/descent evidence")

    if fall_score >= 0.54 and (is_horizontal_posture or center_y_delta >= 14.0 or is_fast_vertical_motion):
        mark = "MARK_3_FALL_SUSPECTED"
        reasons.append("fall score with runtime posture/descent evidence")

    candidate_evidence = fall_score >= 0.74 and has_recent_descent and transition_window_ok
    if candidate_evidence:
        mark = "MARK_4_FALL_CANDIDATE"
        reasons.append("high score with recent descent in plausible transition window")

    confirmed_evidence = (
        candidate_evidence
        and fall_score >= 0.82
        and has_strong_transition
        and has_fallen_hold_stillness
    )
    if confirmed_evidence:
        mark = "MARK_5_FALL_CONFIRMED"
        reasons.append("strong transition with fallen-hold persistence")

    if is_low_confidence_person:
        mark = _cap_mark(mark, "MARK_1_LOW_CONFIDENCE")
        downgraded = True
        reasons.append("low confidence person gate")

    if not track_is_stable:
        mark = _cap_mark(mark, "MARK_3_FALL_SUSPECTED")
        downgraded = True
        reasons.append("track age too short for confirmation")

    if is_moving_continuously and not has_fallen_hold_stillness:
        if first_threshold_time is None or first_threshold_time > 9.0 or fall_score < 0.74:
            mark = _cap_mark(mark, "MARK_3_FALL_SUSPECTED")
            downgraded = True
            reasons.append("continuous movement without fallen-hold stillness")

    if is_horizontal_posture and not (
        has_strong_transition and fall_score >= 0.82 and has_fallen_hold_stillness
    ):
        if not candidate_evidence:
            mark = _cap_mark(mark, "MARK_3_FALL_SUSPECTED")
            downgraded = True
            reasons.append("horizontal posture without confirmed fall transition")

    if is_static_lying_like and not confirmed_evidence:
        mark = _cap_mark(mark, "MARK_3_FALL_SUSPECTED")
        downgraded = True
        reasons.append("static lying-like posture lacks transition confirmation")

    predicted_fall = mark in {"MARK_4_FALL_CANDIDATE", "MARK_5_FALL_CONFIRMED"}
    should_confirm_fall = mark == "MARK_5_FALL_CONFIRMED" and predicted_fall
    return {
        "visual_risk_mark": mark,
        "risk_level": RISK_LEVEL[mark],
        "predicted_fall": predicted_fall,
        "should_confirm_fall": should_confirm_fall,
        "should_send_alert": False,
        "downgraded": downgraded,
        "reasons": reasons,
        "runtime_features": {
            "track_is_stable": track_is_stable,
            "has_recent_descent": has_recent_descent,
            "has_fallen_hold_stillness": has_fallen_hold_stillness,
            "is_low_confidence_person": is_low_confidence_person,
            "is_fast_vertical_motion": is_fast_vertical_motion,
            "is_horizontal_posture": is_horizontal_posture,
            "is_moving_continuously": is_moving_continuously,
            "is_static_lying_like": is_static_lying_like,
        },
    }
