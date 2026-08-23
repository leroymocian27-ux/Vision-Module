from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import numpy as np

from app.core.config import Settings
from app.schemas.vision_result import DetectedObject
from app.services.pose_service import PoseService


def test_pose_disabled_returns_placeholder_and_keeps_chain_running():
    settings = replace(Settings(), enable_pose=False, pose_provider="disabled_placeholder")
    service = PoseService(settings)
    objects = [
        DetectedObject(
            label="person",
            confidence=0.91,
            bbox=[20.0, 30.0, 120.0, 220.0],
            track_id=1,
            is_target=True,
        )
    ]

    with patch.object(service, "_get_estimator", side_effect=AssertionError("estimator must stay unloaded")):
        enriched = service.enrich(
            camera_id="camera_01",
            frame=np.zeros((32, 32, 3), dtype=np.uint8),
            objects=objects,
            frame_seq=5,
            tracking_frame_seq=5,
            frame_age_ms=12.5,
            frame_timestamp="2026-07-20T00:00:00Z",
        )

    assert len(enriched) == 1
    assert enriched[0].track_id == 1
    assert isinstance(enriched[0].pose, dict)
    assert enriched[0].pose["pose_provider"] == "disabled_placeholder"
    assert enriched[0].pose["debug"]["pose_disabled"] is True
    assert enriched[0].pose["debug"]["tracking_frame_seq"] == 5


def test_pose_disabled_status_is_explicit():
    settings = replace(Settings(), enable_pose=False, pose_provider="mock")
    status = PoseService(settings).status("camera_01")

    assert status.pose_enabled is False
    assert status.pose_provider == "disabled_placeholder"
    assert status.pose_pipeline_removed is True
    assert status.placeholder_reason == "pose_pipeline_removed_pending_reconfiguration"
    assert status.last_error is None
