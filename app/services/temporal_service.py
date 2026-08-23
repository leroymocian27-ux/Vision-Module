from __future__ import annotations

import time

from app.core.config import Settings
from app.core.logger import get_logger
from app.pose.placeholders import pose_runtime_enabled
from app.schemas.vision_result import DetectedObject
from app.temporal.adl_suppressor import ADLSuppressor
from app.temporal.fall_state_machine import FallStateMachine
from app.temporal.fall_evidence_scorer import FallEvidenceScorer
from app.temporal.feature_vectorizer import FeatureVectorizer
from app.temporal.feature_window import FeatureWindow
from app.temporal.mock_sequence_model import MockSequenceModel
from app.temporal.onnx_sequence_model import ONNXSequenceModel
from app.temporal.rf_fusion_shadow import RFFusionShadowConfig, RandomForestFusionShadow
from app.temporal.scene_context import SceneContextResolver
from app.temporal.sc_tan_shadow import SCTANShadowConfig, SCTANShadowFusion
from app.temporal.schemas import FallDecision, RiskLevel, SequencePrediction, TemporalStatus, TemporalV6Scores
from app.temporal.target_feature_extractor import TargetFeatureExtractor
from app.temporal.temporal_motion_features import TemporalMotionFeatureBuilder

logger = get_logger(__name__)


class TemporalService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.extractor = TargetFeatureExtractor(
            pose_enabled=pose_runtime_enabled(settings.enable_pose, settings.pose_provider)
        )
        self.window = FeatureWindow(settings.feature_window_size)
        self.vectorizer = FeatureVectorizer(window_size=settings.temporal_model_window_size)
        self.motion_builder = TemporalMotionFeatureBuilder()
        self.fall_scorer = FallEvidenceScorer(settings)
        self.adl_suppressor = ADLSuppressor(settings)
        self.sc_tan = SCTANShadowFusion(
            SCTANShadowConfig(
                min_window=settings.sc_tan_min_window,
                top_k=settings.sc_tan_top_k,
            )
        )
        self.rf_fusion = RandomForestFusionShadow(
            RFFusionShadowConfig(
                min_window=settings.rf_fusion_min_window,
            )
        )
        self.fallback_model = MockSequenceModel()
        self.model = self._build_sequence_model()
        self.state_machine = FallStateMachine(settings)
        self._feature_extractor_ok = True
        self._last_error: str | None = None
        self._last_key: str | None = None
        self._last_decision = FallDecision()
        self._last_prediction = SequencePrediction(fall_probability=0.0)
        self._fallback_active = self._model_fallback_active()
        self._model_last_error = getattr(self.model, "last_error", None)
        self._sc_tan_last_error: str | None = None
        self._rf_fusion_last_error: str | None = None
        self._spatial_slots: dict[str, dict[str, object]] = {}
        self._spatial_slot_seq: dict[str, int] = {}
        self._no_object_streak: dict[str, int] = {}
        self._no_object_reset_count = 0
        self._last_reset_reason: str | None = None

    def enrich(self, camera_id: str, objects: list[DetectedObject]) -> list[DetectedObject]:
        if not self.settings.enable_temporal:
            return objects

        start = time.perf_counter()
        enriched: list[DetectedObject] = []
        any_success = False
        try:
            processable_count = 0
            for item in objects:
                key = self._temporal_key(camera_id, item)
                if key is None or not self._should_process_object(item):
                    enriched.append(item)
                    continue
                processable_count += 1
                try:
                    enriched_item, prediction, decision = self._enrich_one(camera_id, item, key)
                    enriched.append(enriched_item)
                    any_success = True
                    self._last_key = key
                    self._last_decision = decision
                    self._last_prediction = prediction
                except Exception as exc:
                    logger.exception("temporal_enrich_object_failed camera_id=%s key=%s", camera_id, key)
                    self._feature_extractor_ok = False
                    self._last_error = str(exc)
                    enriched.append(item)

            if processable_count == 0:
                self._handle_no_objects(camera_id)
            else:
                self._no_object_streak[camera_id] = 0

            if any_success:
                self._feature_extractor_ok = True
                self._last_error = None

            elapsed_ms = (time.perf_counter() - start) * 1000
            if elapsed_ms > 5:
                logger.warning("temporal_enrich_slow camera_id=%s elapsed_ms=%.2f", camera_id, elapsed_ms)
            return enriched
        except Exception as exc:
            logger.exception("temporal_enrich_failed camera_id=%s", camera_id)
            self._feature_extractor_ok = False
            self._last_error = str(exc)
            return objects

    def _enrich_one(
        self,
        camera_id: str,
        target: DetectedObject,
        key: str,
    ) -> tuple[DetectedObject, SequencePrediction, FallDecision]:
        previous = self.window.previous(key)
        feature = self.extractor.extract(
            camera_id=camera_id,
            target_object=target,
            timestamp=time.monotonic(),
            previous_feature=previous,
        )
        self.window.append(key, feature)
        window = self.window.get_window(key)
        prediction, shadow_prediction = self._predict(window)
        decision_prediction = self._decision_prediction(prediction)
        scene_context = SceneContextResolver.from_payload(target.temporal)
        v6_scores = self._v6_scores(feature, window, decision_prediction, scene_context=scene_context)
        sc_tan_shadow = self._sc_tan_shadow(target=target, window=window, prediction=decision_prediction, v6_scores=v6_scores)
        rf_fusion_shadow = self._rf_fusion_shadow(target=target, window=window, prediction=decision_prediction, v6_scores=v6_scores)
        decision = self.state_machine.update(key, feature, decision_prediction, v6_scores=v6_scores)
        schema = self.vectorizer.schema()
        temporal_payload = {
            "fall_probability": decision_prediction.fall_probability,
            "source": decision_prediction.source,
            "window_size": len(window),
            "window_ready": len(window) >= self.settings.temporal_model_window_size,
            "model_provider": self.settings.temporal_model_provider,
            "model_name": decision_prediction.model_name,
            "model_available": decision_prediction.model_available,
            "model_latency_ms": decision_prediction.latency_ms,
            "feature_schema_version": schema.schema_version,
            "feature_schema_hash": schema.schema_hash,
            "features": feature.model_dump(exclude={"monotonic_time"}),
            "low_posture": decision.low_posture,
            "body_angle": decision.body_angle,
            "bbox_aspect_ratio": decision.bbox_aspect_ratio,
            "velocity_y": decision.velocity_y,
            "stillness": decision.stillness,
            "candidate_duration_ms": decision.candidate_duration_ms,
            "confirm_duration_ms": decision.confirm_duration_ms,
            "confirm_frames": decision.confirm_frames,
            "rejected_reason": decision.rejected_reason,
        }
        if self.settings.fall_v6_debug_payload and v6_scores is not None:
            temporal_payload.update(
                {
                    "fall_evidence_score": v6_scores.fall.fall_evidence_score,
                    "adl_suppression_score": v6_scores.adl.adl_suppression_score,
                    "motion_path": decision.motion_path,
                    "decision_reason": decision.decision_reason,
                    "suppressed_by_adl": decision.suppressed_by_adl,
                    "uncertain_review": decision.uncertain_review,
                    "fall_latched": decision.fall_latched,
                    "scene_context": scene_context.model_dump(),
                    "v6_scores": {
                        "motion": v6_scores.motion.model_dump(),
                        "fall": v6_scores.fall.model_dump(),
                        "adl": v6_scores.adl.model_dump(),
                    },
                }
            )
        if shadow_prediction is not None:
            temporal_payload["shadow"] = {
                "fall_probability": shadow_prediction.fall_probability,
                "source": "shadow_onnx_lstm"
                if shadow_prediction.source == "onnx_lstm"
                else shadow_prediction.source,
                "model_available": shadow_prediction.model_available,
                "latency_ms": shadow_prediction.latency_ms,
            }
        if sc_tan_shadow is not None:
            temporal_payload["sc_tan"] = sc_tan_shadow
        if rf_fusion_shadow is not None:
            temporal_payload["rf_fusion"] = rf_fusion_shadow
        fall_decision_payload = decision.model_dump()
        fall_decision_payload["source"] = "temporal_state_machine"
        if sc_tan_shadow is not None:
            fall_decision_payload["sc_tan_shadow"] = {
                "fall_risk": sc_tan_shadow.get("fall_risk"),
                "adl_risk": sc_tan_shadow.get("adl_risk"),
                "uncertainty": sc_tan_shadow.get("uncertainty"),
                "decision_hint": sc_tan_shadow.get("decision_hint"),
                "source": sc_tan_shadow.get("source"),
            }
        if rf_fusion_shadow is not None:
            fall_decision_payload["rf_fusion_shadow"] = {
                "fall_risk": rf_fusion_shadow.get("fall_risk"),
                "adl_risk": rf_fusion_shadow.get("adl_risk"),
                "uncertainty": rf_fusion_shadow.get("uncertainty"),
                "decision_hint": rf_fusion_shadow.get("decision_hint"),
                "source": rf_fusion_shadow.get("source"),
            }
        if decision.fall_state != "fallen_confirmed":
            fall_decision_payload["suppressed_reason"] = decision.rejected_reason or "awaiting_temporal_confirmation"
        alarm_preview = {
            "risk_level": decision.risk_level,
            "countdown_ms": decision.countdown_ms,
            "confirmed": decision.fall_state == "fallen_confirmed",
            "source": "temporal_state_machine",
            "fall_probability": decision.fall_probability,
        }
        if sc_tan_shadow is not None:
            alarm_preview["sc_tan_shadow"] = fall_decision_payload["sc_tan_shadow"]
        if rf_fusion_shadow is not None:
            alarm_preview["rf_fusion_shadow"] = fall_decision_payload["rf_fusion_shadow"]
        if decision.fall_state != "fallen_confirmed":
            alarm_preview["suppressed_reason"] = decision.rejected_reason or "awaiting_temporal_confirmation"
        return (
            target.model_copy(
                update={
                    "temporal": temporal_payload,
                    "fall_decision": fall_decision_payload,
                    "alarm_preview": alarm_preview,
                }
            ),
            decision_prediction,
            decision,
        )

    def _sc_tan_shadow(
        self,
        *,
        target: DetectedObject,
        window,
        prediction: SequencePrediction,
        v6_scores: TemporalV6Scores | None,
    ) -> dict | None:
        if not self.settings.sc_tan_shadow_enabled:
            return None
        payload = self.sc_tan.predict(
            target=target,
            window=window,
            prediction=prediction,
            v6_scores=v6_scores,
        )
        self._sc_tan_last_error = self.sc_tan.last_error
        return payload

    def _rf_fusion_shadow(
        self,
        *,
        target: DetectedObject,
        window,
        prediction: SequencePrediction,
        v6_scores: TemporalV6Scores | None,
    ) -> dict | None:
        if not self.settings.rf_fusion_shadow_enabled:
            return None
        payload = self.rf_fusion.predict(
            target=target,
            window=window,
            prediction=prediction,
            v6_scores=v6_scores,
        )
        self._rf_fusion_last_error = self.rf_fusion.last_error
        return payload

    def _v6_scores(
        self,
        feature,
        window,
        prediction: SequencePrediction,
        *,
        scene_context,
    ) -> TemporalV6Scores | None:
        if not self.settings.fall_v6_scoring_enabled:
            return None
        motion = self.motion_builder.build(window)
        fall = self.fall_scorer.score(
            feature=feature,
            prediction=prediction,
            motion=motion,
            frame_height=self.settings.mock_camera_height,
        )
        adl = self.adl_suppressor.score(feature=feature, motion=motion, fall=fall, scene_context=scene_context)
        return TemporalV6Scores(motion=motion, fall=fall, adl=adl, scene=scene_context)

    def _predict(self, window) -> tuple[SequencePrediction, SequencePrediction | None]:
        provider = self.settings.temporal_model_provider.strip().lower()
        if provider == "mock":
            return self._mock_prediction(window), None
        if provider == "shadow":
            mock_prediction = self._mock_prediction(window)
            shadow_prediction = self._onnx_prediction(window)
            return mock_prediction, shadow_prediction
        prediction = self._onnx_prediction(window)
        if prediction.source.startswith("fallback_mock") or prediction.source == "warming_up":
            return self._fallback_prediction(window, prediction.source), None
        return prediction, None

    def _decision_prediction(self, prediction: SequencePrediction) -> SequencePrediction:
        return prediction

    def _mock_prediction(self, window) -> SequencePrediction:
        prediction = self.fallback_model.predict(window)
        return prediction.model_copy(
            update={
                "source": "mock",
                "model_name": "mock_sequence_model",
                "model_available": True,
                "window_ready": len(window) >= self.settings.temporal_warmup_min_size,
                "window_size": len(window),
                "feature_dim": self.vectorizer.input_dim,
            }
        )

    def _fallback_prediction(self, window, source: str) -> SequencePrediction:
        prediction = self._mock_prediction(window)
        return prediction.model_copy(update={"source": source})

    def _onnx_prediction(self, window) -> SequencePrediction:
        try:
            prediction = self.model.predict(window)
            self._model_last_error = getattr(self.model, "last_error", None)
            self._fallback_active = self._model_fallback_active() or prediction.source.startswith("fallback_mock")
            return prediction
        except Exception as exc:
            logger.exception("temporal_sequence_model_failed fallback=mock")
            self._model_last_error = str(exc)
            self._fallback_active = True
            return SequencePrediction(
                source="fallback_mock_inference_error",
                fall_probability=0.0,
                model_name=getattr(self.model, "model_name", "onnx_lstm"),
                model_available=False,
                window_ready=len(window) >= self.settings.temporal_model_window_size,
                window_size=len(window),
                feature_dim=self.vectorizer.input_dim,
            )

    def status(self, camera_id: str | None = None) -> TemporalStatus:
        del camera_id
        window_status = self.window.status()
        return TemporalStatus(
            enabled=self.settings.enable_temporal,
            feature_extractor_ok=self._feature_extractor_ok,
            window_size=window_status["window_size"],
            active_tracks=window_status["active_tracks"],
            fall_state=self._last_decision.fall_state,
            fall_probability=self._last_prediction.fall_probability,
            risk_level=self._last_decision.risk_level,
            last_error=self._last_error,
            model_provider=self.settings.temporal_model_provider,
            model_loaded=bool(getattr(self.model, "available", True)),
            model_path=getattr(self.model, "model_path", None),
            model_input_size=self.vectorizer.input_dim,
            feature_schema_version=self.vectorizer.schema_version,
            feature_schema_hash=self.vectorizer.schema_hash,
            model_last_error=self._model_last_error,
            fallback_active=self._fallback_active,
            sc_tan_shadow_enabled=self.settings.sc_tan_shadow_enabled,
            sc_tan_last_error=self._sc_tan_last_error,
            rf_fusion_shadow_enabled=self.settings.rf_fusion_shadow_enabled,
            rf_fusion_last_error=self._rf_fusion_last_error,
            no_object_reset_count=self._no_object_reset_count,
            last_reset_reason=self._last_reset_reason,
        )

    def reset_camera(self, camera_id: str, reason: str | None = None) -> None:
        prefixes = (f"track:{camera_id}:", f"person:{camera_id}:", f"spatial:{camera_id}:")
        for key in list(self.window.keys()):
            if key.startswith(prefixes):
                self.window.clear(key)
                self.state_machine.clear(key)
        if self._last_key and self._last_key.startswith(prefixes):
            self._last_key = None
            self._last_decision = FallDecision()
            self._last_prediction = SequencePrediction(fall_probability=0.0)
            self._last_error = None
            self._feature_extractor_ok = True
        self._spatial_slots.pop(camera_id, None)
        self._spatial_slot_seq.pop(camera_id, None)
        self._no_object_streak[camera_id] = 0
        if reason is not None:
            self._no_object_reset_count += 1
            self._last_reset_reason = reason

    def _build_sequence_model(self):
        if self.settings.pipeline_mode == "post_fall_v2":
            return self.fallback_model
        provider = self.settings.temporal_model_provider.strip().lower()
        if provider not in {"onnx_lstm", "shadow"}:
            return self.fallback_model
        model = ONNXSequenceModel(
            model_path=self.settings.temporal_onnx_model_path,
            schema_path=self.settings.temporal_feature_schema_path,
            providers=self.settings.temporal_onnx_providers,
            vectorizer=self.vectorizer,
            window_size=self.settings.temporal_model_window_size,
            input_dim=self.settings.temporal_model_input_dim,
            frame_width=self.settings.mock_camera_width,
            frame_height=self.settings.mock_camera_height,
        )
        if not model.available:
            logger.warning(
                "temporal_onnx_unavailable model_path=%s error=%s fallback=mock_sequence_model",
                self.settings.temporal_onnx_model_path,
                model.last_error,
            )
        return model

    def _model_fallback_active(self) -> bool:
        provider = self.settings.temporal_model_provider.strip().lower()
        return provider in {"onnx_lstm", "shadow"} and not bool(getattr(self.model, "available", False))

    def _should_process_object(self, obj: DetectedObject) -> bool:
        if obj.label != "person":
            return False
        mode = self.settings.temporal_track_mode.strip().lower()
        if mode == "target_only":
            return obj.is_target
        return True

    def _handle_no_objects(self, camera_id: str) -> None:
        streak = self._no_object_streak.get(camera_id, 0) + 1
        self._no_object_streak[camera_id] = streak
        if streak < max(1, self.settings.temporal_no_object_reset_frames):
            return
        self.reset_camera(camera_id, reason="no_objects_reset_temporal")

    @staticmethod
    def _select_target(objects: list[DetectedObject]) -> DetectedObject | None:
        targets = [item for item in objects if item.is_target]
        if targets:
            return max(targets, key=TemporalService._area)
        candidates = [item for item in objects if item.track_id is not None]
        if not candidates:
            return None
        return max(candidates, key=TemporalService._area)

    def _temporal_key(self, camera_id: str, obj: DetectedObject) -> str | None:
        key_mode = self.settings.temporal_sequence_key_mode.strip().lower()
        if key_mode == "spatial":
            return self._spatial_temporal_key(camera_id, obj)
        if obj.person_id:
            return f"person:{camera_id}:{obj.person_id}"
        if obj.track_id is not None:
            return f"track:{camera_id}:{obj.track_id}"
        return None

    def _spatial_temporal_key(self, camera_id: str, obj: DetectedObject) -> str:
        slots = self._spatial_slots.setdefault(camera_id, {})
        now = time.monotonic()
        bbox = [float(value) for value in obj.bbox]
        center = self._bbox_center(bbox)
        best_key: str | None = None
        best_score = float("inf")
        for key, slot in list(slots.items()):
            last_seen = float(slot.get("last_seen", 0.0))
            if (now - last_seen) > 8.0:
                slots.pop(key, None)
                self.window.clear(key)
                self.state_machine.clear(key)
                continue
            slot_bbox = slot.get("bbox")
            if not isinstance(slot_bbox, list):
                continue
            iou = self._iou(bbox, slot_bbox)
            slot_center = self._bbox_center(slot_bbox)
            distance = ((center[0] - slot_center[0]) ** 2 + (center[1] - slot_center[1]) ** 2) ** 0.5
            dynamic_limit = max(180.0, 0.85 * (self._bbox_size(bbox) + self._bbox_size(slot_bbox)) / 2)
            if iou < 0.02 and distance > dynamic_limit:
                continue
            score = distance - (iou * 240.0)
            if score < best_score:
                best_key = key
                best_score = score
        if best_key is None:
            seq = self._spatial_slot_seq.get(camera_id, 0) + 1
            self._spatial_slot_seq[camera_id] = seq
            best_key = f"spatial:{camera_id}:{seq}"
        slots[best_key] = {"bbox": bbox, "last_seen": now}
        return best_key

    @staticmethod
    def _bbox_center(bbox: list[float]) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @staticmethod
    def _bbox_size(bbox: list[float]) -> float:
        x1, y1, x2, y2 = bbox
        return max(1.0, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)

    @staticmethod
    def _iou(a: list[float], b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter = inter_w * inter_h
        if inter <= 0:
            return 0.0
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    @staticmethod
    def _area(item: DetectedObject) -> float:
        x1, y1, x2, y2 = item.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)
