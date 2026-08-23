from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a project-specific training manifest for RTMPose adaptation."
    )
    parser.add_argument(
        "--dataset-dir",
        default="data/pose_adaptation_dataset_full",
        help="COCO-style pseudo-label dataset directory.",
    )
    parser.add_argument(
        "--output",
        default="evaluations/phase10_pose_adaptation_training_plan_001.json",
        help="Output manifest json.",
    )
    args = parser.parse_args()

    dataset_dir = ROOT / args.dataset_dir
    images_dir = dataset_dir / "images"
    ann_dir = dataset_dir / "annotations"
    train_json = ann_dir / "pose_pseudolabels_train.json"
    val_json = ann_dir / "pose_pseudolabels_val.json"
    test_json = ann_dir / "pose_pseudolabels_test.json"

    if not train_json.exists():
        raise SystemExit(f"missing training annotations: {train_json}")

    payload = {
        "generated_at": "2026-06-14",
        "dataset_dir": str(dataset_dir),
        "images_dir": str(images_dir),
        "annotations": {
            "train": str(train_json),
            "val": str(val_json),
            "test": str(test_json),
        },
        "recommended_target": {
            "provider": "rtmpose_onnx",
            "model_family": "RTMPose Body 17-keypoints",
            "seed_runtime_model": "models/rtmpose/rtmpose-x-body7-384x288.onnx",
        },
        "next_training_stack": {
            "python": "py -3.10",
            "needs_install": ["mmengine", "mmcv", "mmdet", "mmpose"],
            "note": "Current repo now has adaptation data, but full supervised fine-tuning still requires the OpenMMLab training stack.",
        },
        "suggested_training_policy": {
            "phase": "pseudo-label adaptation bootstrap",
            "review_required": True,
            "priority_cases": [
                "lying_down_normal",
                "sitting",
                "bending",
                "squatting",
                "fall near floor furniture",
                "occluded subjects",
            ],
        },
    }

    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
