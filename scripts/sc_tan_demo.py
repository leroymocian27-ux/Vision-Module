from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import torch
from torch import Tensor, nn


ROOT = Path(__file__).resolve().parents[1]


FEATURE_NAMES = [
    "person_confidence",
    "fall_hint_confidence",
    "hint_falling",
    "hint_fallen",
    "hint_lying",
    "hint_sitting",
    "hint_bending",
    "hint_kneeling",
    "hint_standing",
    "bbox_aspect_ratio",
    "delta_y_norm",
    "velocity_y_norm",
    "speed_norm",
    "pose_available",
    "pose_confidence",
    "torso_angle_norm",
    "head_height_ratio",
    "hip_height_ratio",
    "low_posture",
    "stillness",
    "track_quality",
    "lstm_fall_probability",
    "fall_evidence_score",
    "adl_suppression_score",
    "floor_risk_score",
    "support_surface_score",
]

FLOOR_RISK_INDEX = FEATURE_NAMES.index("floor_risk_score")
SUPPORT_SURFACE_INDEX = FEATURE_NAMES.index("support_surface_score")


@dataclass(frozen=True)
class WindowSample:
    scenario: str
    features: np.ndarray
    valid_mask: np.ndarray
    fall_label: float
    adl_label: float


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int) -> None:
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float32) * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0), persistent=False)

    def forward(self, x: Tensor) -> Tensor:
        return x + self.pe[:, : x.shape[1], :]


class SCTAN(nn.Module):
    """Scene-Constrained Temporal Attention Network demo.

    Input shape:
        features: [batch, window, feature_dim]
        valid_mask: [batch, window], 1 for valid observations and 0 for padding

    Outputs:
        fall_risk: scene-adjusted fall probability
        raw_fall_risk: neural fall probability before scene constraints
        adl_risk: ADL-like probability
        uncertainty: model uncertainty gate
        attention: temporal attention over frames
    """

    def __init__(
        self,
        *,
        feature_dim: int,
        window_size: int,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 2,
        dropout: float = 0.10,
    ) -> None:
        super().__init__()
        self.window_size = window_size
        self.input_norm = nn.LayerNorm(feature_dim)
        self.input_projection = nn.Linear(feature_dim, d_model)
        self.position = PositionalEncoding(d_model=d_model, max_len=window_size)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 3,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=False,
        )
        self.encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=num_layers,
            enable_nested_tensor=False,
        )
        self.attention_score = nn.Linear(d_model, 1)
        self.context_norm = nn.LayerNorm(d_model)
        self.head = nn.Sequential(
            nn.Linear(d_model, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, 3),
        )

    def forward(self, features: Tensor, valid_mask: Tensor) -> dict[str, Tensor]:
        padding_mask = valid_mask <= 0
        x = self.input_projection(self.input_norm(features))
        x = self.position(x)
        encoded = self.encoder(x, src_key_padding_mask=padding_mask)

        logits = self.attention_score(encoded).squeeze(-1)
        logits = logits.masked_fill(padding_mask, -1e9)
        attention = torch.softmax(logits, dim=1)
        context = torch.sum(encoded * attention.unsqueeze(-1), dim=1)
        context = self.context_norm(context)

        raw = self.head(context)
        raw_fall_risk = torch.sigmoid(raw[:, 0])
        adl_risk = torch.sigmoid(raw[:, 1])
        uncertainty = torch.sigmoid(raw[:, 2])

        floor_risk = _masked_mean(features[:, :, FLOOR_RISK_INDEX], valid_mask)
        support_surface = _masked_mean(features[:, :, SUPPORT_SURFACE_INDEX], valid_mask)
        constrained_logit = torch.logit(raw_fall_risk.clamp(1e-4, 1.0 - 1e-4))
        constrained_logit = constrained_logit + 0.80 * floor_risk - 0.65 * support_surface - 0.35 * adl_risk
        fall_risk = torch.sigmoid(constrained_logit)

        return {
            "fall_risk": fall_risk,
            "raw_fall_risk": raw_fall_risk,
            "adl_risk": adl_risk,
            "uncertainty": uncertainty,
            "attention": attention,
        }


def _masked_mean(values: Tensor, valid_mask: Tensor) -> Tensor:
    masked = values * valid_mask
    denom = valid_mask.sum(dim=1).clamp_min(1.0)
    return masked.sum(dim=1) / denom


def make_feature_vector(**values: float) -> np.ndarray:
    vector = np.zeros(len(FEATURE_NAMES), dtype=np.float32)
    defaults = {
        "person_confidence": 0.86,
        "pose_available": 1.0,
        "pose_confidence": 0.80,
        "track_quality": 0.85,
        "hint_standing": 1.0,
        "bbox_aspect_ratio": 0.45,
        "head_height_ratio": 0.18,
        "hip_height_ratio": 0.42,
        "stillness": 0.40,
    }
    defaults.update(values)
    for key, value in defaults.items():
        vector[FEATURE_NAMES.index(key)] = float(value)
    return vector


def synthetic_window(
    kind: Literal["fall", "adl", "normal"],
    *,
    window_size: int,
    rng: random.Random,
) -> WindowSample:
    rows: list[np.ndarray] = []
    for t in range(window_size):
        progress = t / max(1, window_size - 1)
        noise = lambda scale=0.03: rng.uniform(-scale, scale)

        if kind == "fall":
            impact = 1.0 if 0.34 <= progress <= 0.58 else 0.0
            after = 1.0 if progress > 0.58 else 0.0
            falling_hint = 1.0 if impact else 0.0
            fallen_hint = after
            rows.append(
                make_feature_vector(
                    fall_hint_confidence=max(0.0, min(1.0, 0.35 + 0.50 * (impact or after) + noise())),
                    hint_standing=1.0 - max(falling_hint, fallen_hint),
                    hint_falling=falling_hint,
                    hint_fallen=fallen_hint,
                    bbox_aspect_ratio=0.45 + 0.95 * after + 0.45 * impact + noise(0.04),
                    delta_y_norm=max(0.0, 0.05 + 0.95 * impact + noise(0.05)),
                    velocity_y_norm=max(0.0, 0.10 + 1.15 * impact + noise(0.06)),
                    speed_norm=max(0.0, 0.55 * impact + 0.12 * (1.0 - impact) + noise(0.03)),
                    torso_angle_norm=0.05 + 0.70 * after + 0.35 * impact + noise(0.04),
                    head_height_ratio=0.18 + 0.55 * after + 0.25 * impact + noise(0.03),
                    hip_height_ratio=0.42 + 0.40 * after + 0.18 * impact + noise(0.03),
                    low_posture=after,
                    stillness=0.20 + 0.70 * after + noise(0.04),
                    lstm_fall_probability=max(0.0, min(1.0, 0.12 + 0.72 * (impact or after) + noise(0.05))),
                    fall_evidence_score=max(0.0, min(1.0, 0.18 + 0.70 * (impact or after) + noise(0.05))),
                    adl_suppression_score=max(0.0, min(1.0, 0.14 + noise(0.04))),
                    floor_risk_score=0.88 + noise(0.03),
                    support_surface_score=0.05 + noise(0.02),
                    track_quality=0.82 + noise(0.04),
                )
            )
        elif kind == "adl":
            transition = 1.0 if 0.28 <= progress <= 0.55 else 0.0
            seated_or_lying = 1.0 if progress > 0.55 else 0.0
            rows.append(
                make_feature_vector(
                    fall_hint_confidence=max(0.0, min(1.0, 0.20 + 0.22 * seated_or_lying + noise())),
                    hint_standing=1.0 - seated_or_lying,
                    hint_sitting=seated_or_lying,
                    hint_lying=0.35 * seated_or_lying,
                    bbox_aspect_ratio=0.50 + 0.35 * seated_or_lying + noise(0.04),
                    delta_y_norm=max(0.0, 0.04 + 0.25 * transition + noise(0.04)),
                    velocity_y_norm=max(0.0, 0.05 + 0.18 * transition + noise(0.03)),
                    speed_norm=max(0.0, 0.16 + 0.12 * transition + noise(0.03)),
                    torso_angle_norm=0.10 + 0.35 * seated_or_lying + noise(0.04),
                    head_height_ratio=0.18 + 0.25 * seated_or_lying + noise(0.03),
                    hip_height_ratio=0.42 + 0.16 * seated_or_lying + noise(0.03),
                    low_posture=seated_or_lying,
                    stillness=0.35 + 0.40 * seated_or_lying + noise(0.04),
                    lstm_fall_probability=max(0.0, min(1.0, 0.14 + 0.15 * seated_or_lying + noise(0.04))),
                    fall_evidence_score=max(0.0, min(1.0, 0.18 + 0.22 * seated_or_lying + noise(0.04))),
                    adl_suppression_score=max(0.0, min(1.0, 0.50 + 0.35 * seated_or_lying + noise(0.04))),
                    floor_risk_score=0.10 + noise(0.03),
                    support_surface_score=0.82 + noise(0.04),
                    track_quality=0.86 + noise(0.03),
                )
            )
        else:
            walking = 1.0 if 0.20 <= progress <= 0.75 else 0.0
            rows.append(
                make_feature_vector(
                    fall_hint_confidence=max(0.0, min(1.0, 0.08 + noise(0.03))),
                    hint_standing=1.0,
                    bbox_aspect_ratio=0.43 + noise(0.03),
                    delta_y_norm=max(0.0, 0.02 + 0.05 * walking + noise(0.02)),
                    velocity_y_norm=max(0.0, 0.02 + 0.05 * walking + noise(0.02)),
                    speed_norm=max(0.0, 0.10 + 0.28 * walking + noise(0.03)),
                    torso_angle_norm=0.04 + noise(0.02),
                    head_height_ratio=0.16 + noise(0.02),
                    hip_height_ratio=0.40 + noise(0.02),
                    low_posture=0.0,
                    stillness=0.25 + 0.20 * (1.0 - walking) + noise(0.03),
                    lstm_fall_probability=max(0.0, min(1.0, 0.07 + noise(0.03))),
                    fall_evidence_score=max(0.0, min(1.0, 0.08 + noise(0.03))),
                    adl_suppression_score=max(0.0, min(1.0, 0.12 + noise(0.03))),
                    floor_risk_score=0.25 + noise(0.04),
                    support_surface_score=0.05 + noise(0.03),
                    track_quality=0.90 + noise(0.03),
                )
            )

    features = np.stack(rows, axis=0).astype(np.float32)
    valid_mask = np.ones(window_size, dtype=np.float32)
    return WindowSample(
        scenario=kind,
        features=features,
        valid_mask=valid_mask,
        fall_label=1.0 if kind == "fall" else 0.0,
        adl_label=1.0 if kind == "adl" else 0.0,
    )


def build_synthetic_dataset(window_size: int, samples_per_kind: int, seed: int) -> list[WindowSample]:
    rng = random.Random(seed)
    samples: list[WindowSample] = []
    for kind in ("fall", "adl", "normal"):
        for _ in range(samples_per_kind):
            samples.append(synthetic_window(kind, window_size=window_size, rng=rng))
    rng.shuffle(samples)
    return samples


def batch_from_samples(samples: list[WindowSample]) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    features = torch.tensor(np.stack([item.features for item in samples], axis=0), dtype=torch.float32)
    masks = torch.tensor(np.stack([item.valid_mask for item in samples], axis=0), dtype=torch.float32)
    fall = torch.tensor([item.fall_label for item in samples], dtype=torch.float32)
    adl = torch.tensor([item.adl_label for item in samples], dtype=torch.float32)
    return features, masks, fall, adl


def train_demo_model(model: SCTAN, samples: list[WindowSample], epochs: int, lr: float) -> list[float]:
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    features, masks, fall_target, adl_target = batch_from_samples(samples)
    losses: list[float] = []
    bce = nn.BCELoss()
    for _ in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        outputs = model(features, masks)
        loss = bce(outputs["fall_risk"], fall_target) + 0.70 * bce(outputs["adl_risk"], adl_target)
        # Uncertainty should be low on clean synthetic examples.
        loss = loss + 0.10 * outputs["uncertainty"].mean()
        loss.backward()
        optimizer.step()
        losses.append(round(float(loss.detach().cpu()), 6))
    return losses


def summarize_prediction(sample: WindowSample, outputs: dict[str, Tensor]) -> dict[str, object]:
    attention = outputs["attention"][0].detach().cpu().numpy()
    top_indices = np.argsort(attention)[::-1][:5].tolist()
    top_frames = [
        {
            "frame_index": int(index),
            "attention": round(float(attention[index]), 4),
            "fall_evidence_score": round(float(sample.features[index, FEATURE_NAMES.index("fall_evidence_score")]), 4),
            "adl_suppression_score": round(float(sample.features[index, FEATURE_NAMES.index("adl_suppression_score")]), 4),
            "floor_risk_score": round(float(sample.features[index, FLOOR_RISK_INDEX]), 4),
            "support_surface_score": round(float(sample.features[index, SUPPORT_SURFACE_INDEX]), 4),
        }
        for index in top_indices
    ]
    return {
        "scenario": sample.scenario,
        "fall_risk": round(float(outputs["fall_risk"][0].detach().cpu()), 4),
        "raw_fall_risk": round(float(outputs["raw_fall_risk"][0].detach().cpu()), 4),
        "adl_risk": round(float(outputs["adl_risk"][0].detach().cpu()), 4),
        "uncertainty": round(float(outputs["uncertainty"][0].detach().cpu()), 4),
        "top_attention_frames": top_frames,
        "decision": decision_from_outputs(outputs),
    }


def decision_from_outputs(outputs: dict[str, Tensor]) -> str:
    fall = float(outputs["fall_risk"][0].detach().cpu())
    adl = float(outputs["adl_risk"][0].detach().cpu())
    uncertainty = float(outputs["uncertainty"][0].detach().cpu())
    if uncertainty >= 0.45:
        return "need_review"
    if fall >= 0.72 and adl < 0.45:
        return "fallen_confirmed_candidate"
    if fall >= 0.45:
        return "fall_candidate"
    if adl >= 0.60:
        return "adl_suppressed"
    return "normal"


def run_demo(args: argparse.Namespace) -> dict[str, object]:
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)

    train_samples = build_synthetic_dataset(
        window_size=args.window_size,
        samples_per_kind=args.samples_per_kind,
        seed=args.seed,
    )
    model = SCTAN(feature_dim=len(FEATURE_NAMES), window_size=args.window_size)
    losses = train_demo_model(model, train_samples, epochs=args.epochs, lr=args.learning_rate)

    model.eval()
    probe_rng = random.Random(args.seed + 99)
    probes = [
        synthetic_window("fall", window_size=args.window_size, rng=probe_rng),
        synthetic_window("adl", window_size=args.window_size, rng=probe_rng),
        synthetic_window("normal", window_size=args.window_size, rng=probe_rng),
    ]
    predictions = []
    with torch.no_grad():
        for sample in probes:
            features, masks, _, _ = batch_from_samples([sample])
            outputs = model(features, masks)
            predictions.append(summarize_prediction(sample, outputs))

    return {
        "algorithm": "SC-TAN",
        "description": "Scene-Constrained Temporal Attention Network demo for fall-risk fusion.",
        "feature_names": FEATURE_NAMES,
        "window_size": args.window_size,
        "train_samples": len(train_samples),
        "epochs": args.epochs,
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "predictions": predictions,
        "integration_note": (
            "Replace synthetic_window() with features exported from YOLO, ByteTrack, pose, "
            "temporal LSTM, fall evidence, ADL suppressor, and scene context."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the SC-TAN fall-fusion algorithm demo.")
    parser.add_argument("--window-size", type=int, default=32)
    parser.add_argument("--samples-per-kind", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--learning-rate", type=float, default=3e-3)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluations" / "sc_tan_demo_output.json",
        help="Where to write the JSON demo output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_demo(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
