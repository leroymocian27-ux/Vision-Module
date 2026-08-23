from __future__ import annotations

import json
import unittest

from scripts.pose_runtime_profile_env import build_profile_payload, render_payload


class PoseRuntimeProfileEnvTest(unittest.TestCase):
    def test_bcpu_profile_uses_cpu_dev_conservative_pose_budget(self) -> None:
        payload = build_profile_payload("Bcpu")
        env = payload["env"]

        self.assertFalse(payload["production_profile"])
        self.assertEqual(env["FALL_DETECTOR_INTERVAL_MS"], "800")
        self.assertEqual(env["POSE_MAX_FRAME_AGE_MS"], "1000")
        self.assertEqual(env["POSE_RESULT_TTL_MS"], "1000")
        self.assertEqual(env["POSE_MAX_TRACKING_FRAME_DELTA"], "2")

    def test_b_profile_remains_production_candidate_with_stricter_age_budget(self) -> None:
        payload = build_profile_payload("B")
        env = payload["env"]

        self.assertTrue(payload["production_profile"])
        self.assertEqual(env["FALL_DETECTOR_INTERVAL_MS"], "200")
        self.assertEqual(env["POSE_MAX_FRAME_AGE_MS"], "800")
        self.assertEqual(env["POSE_RESULT_TTL_MS"], "800")

    def test_render_json_and_powershell_outputs(self) -> None:
        payload = build_profile_payload("Bcpu")

        rendered_json = json.loads(render_payload(payload, "json"))
        rendered_ps = render_payload(payload, "powershell")

        self.assertEqual(rendered_json["profile"], "Bcpu")
        self.assertIn("$env:POSE_MAX_FRAME_AGE_MS='1000'", rendered_ps)


if __name__ == "__main__":
    unittest.main()
