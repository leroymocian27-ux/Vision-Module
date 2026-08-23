from __future__ import annotations

from pathlib import Path
import unittest

from app.schemas.status import StreamRuntimeAlias


class StreamSourceRedactionTest(unittest.TestCase):
    def test_public_status_alias_has_no_raw_source_url_field(self) -> None:
        alias = StreamRuntimeAlias(source_url_masked="rtsp://admin:***@camera.example/stream")
        self.assertNotIn("source_url", alias.model_dump())
        self.assertEqual(alias.source_url_masked, "rtsp://admin:***@camera.example/stream")

    def test_demo_frontend_does_not_embed_or_refill_a_raw_rtsp_url(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "frontend_demo" / "index.html").read_text(encoding="utf-8")
        script = (root / "frontend_demo" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('value="rtsp://', html)
        self.assertNotIn("?.source_url ||", script)
        self.assertIn("source_url_masked", script)
        self.assertIn("function redactStatusForUi", script)
        self.assertIn('"source_url"', script)
        self.assertIn("受控视频源已连接", script)
        self.assertNotIn("统一源(single): ${analysisUrl}", script)
