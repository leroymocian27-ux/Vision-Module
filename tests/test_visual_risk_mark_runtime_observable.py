from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "fast_pose_fall"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from visual_risk_mark_runtime_observable import assign_runtime_observable_risk_mark


class GuardedFeatures(dict):
    forbidden = {
        "scene_tags",
        "label",
        "hard_negative",
        "split",
        "dataset",
        "group_id",
        "asset_id",
        "video_id",
        "path",
    }

    def get(self, key, default=None):  # type: ignore[override]
        if key in self.forbidden:
            raise AssertionError(f"runtime rule read forbidden key: {key}")
        return super().get(key, default)


def base_features(**overrides):
    data = GuardedFeatures(
        {
            "max_fall_score": 0.2,
            "max_person_confidence": 0.9,
            "max_aspect_ratio": 0.5,
            "max_center_y_delta": 0.0,
            "max_velocity_y": 0.0,
            "max_track_age_sec": 3.0,
            "max_stillness_duration_sec": 0.0,
            "mean_speed": 20.0,
            "max_speed": 30.0,
            "first_threshold_time_sec": None,
        }
    )
    data.update(overrides)
    return data


def test_runtime_rule_does_not_read_offline_keys() -> None:
    result = assign_runtime_observable_risk_mark(
        base_features(
            scene_tags=["walking_slow"],
            label="non_fall",
            hard_negative=True,
            split="local_test",
            dataset="local_camera_01",
            group_id="camera_01_session",
        )
    )
    assert result["predicted_fall"] is False


def test_walking_like_continuous_motion_without_stillness_is_not_fall() -> None:
    result = assign_runtime_observable_risk_mark(
        base_features(
            max_fall_score=0.78,
            max_aspect_ratio=3.4,
            max_center_y_delta=138.0,
            max_velocity_y=550.0,
            mean_speed=340.0,
            max_speed=900.0,
            max_stillness_duration_sec=0.0,
            first_threshold_time_sec=12.75,
        )
    )
    assert result["predicted_fall"] is False
    assert result["visual_risk_mark"] == "MARK_3_FALL_SUSPECTED"


def test_lying_like_posture_without_recent_descent_is_not_fall() -> None:
    result = assign_runtime_observable_risk_mark(
        base_features(
            max_fall_score=0.76,
            max_aspect_ratio=3.0,
            max_center_y_delta=20.0,
            max_velocity_y=80.0,
            max_stillness_duration_sec=0.25,
            first_threshold_time_sec=4.0,
        )
    )
    assert result["predicted_fall"] is False


def test_low_person_confidence_is_not_fall() -> None:
    result = assign_runtime_observable_risk_mark(
        base_features(
            max_fall_score=0.95,
            max_person_confidence=0.1,
            max_aspect_ratio=3.0,
            max_center_y_delta=200.0,
            max_velocity_y=700.0,
            max_track_age_sec=4.0,
            max_stillness_duration_sec=2.0,
            first_threshold_time_sec=5.0,
        )
    )
    assert result["predicted_fall"] is False
    assert result["visual_risk_mark"] == "MARK_1_LOW_CONFIDENCE"


def test_strong_descent_high_score_can_be_candidate() -> None:
    result = assign_runtime_observable_risk_mark(
        base_features(
            max_fall_score=0.8,
            max_aspect_ratio=3.0,
            max_center_y_delta=110.0,
            max_velocity_y=440.0,
            max_track_age_sec=3.0,
            max_stillness_duration_sec=0.4,
            first_threshold_time_sec=5.0,
        )
    )
    assert result["predicted_fall"] is True
    assert result["visual_risk_mark"] == "MARK_4_FALL_CANDIDATE"


def test_strong_descent_high_score_with_persistence_can_confirm() -> None:
    result = assign_runtime_observable_risk_mark(
        base_features(
            max_fall_score=0.9,
            max_aspect_ratio=3.0,
            max_center_y_delta=180.0,
            max_velocity_y=650.0,
            max_track_age_sec=3.0,
            max_stillness_duration_sec=2.0,
            first_threshold_time_sec=5.0,
        )
    )
    assert result["predicted_fall"] is True
    assert result["visual_risk_mark"] == "MARK_5_FALL_CONFIRMED"


def test_track_age_too_short_cannot_mark_5() -> None:
    result = assign_runtime_observable_risk_mark(
        base_features(
            max_fall_score=0.95,
            max_aspect_ratio=3.0,
            max_center_y_delta=200.0,
            max_velocity_y=700.0,
            max_track_age_sec=0.5,
            max_stillness_duration_sec=2.0,
            first_threshold_time_sec=5.0,
        )
    )
    assert result["visual_risk_mark"] != "MARK_5_FALL_CONFIRMED"
