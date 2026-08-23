from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an RTMPose adaptation config stub for project fine-tuning.")
    parser.add_argument(
        "--output",
        default="models/rtmpose/rtmpose_x_pose_adaptation_config.py",
        help="Output config path.",
    )
    parser.add_argument(
        "--dataset-dir",
        default="data/pose_adaptation_dataset_full",
        help="COCO-style pseudo-label dataset directory.",
    )
    args = parser.parse_args()

    dataset_dir = (ROOT / args.dataset_dir).resolve()
    output_path = (ROOT / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = f'''# Auto-generated RTMPose adaptation config stub
# Generated from project-local pseudo-label assets.
#
# This file is intentionally a lightweight starting point rather than a
# guaranteed runnable upstream config, because the exact RTMPose training stack
# available on the target machine may differ.
#
# Dataset root:
#   {dataset_dir.as_posix()}

dataset_type = 'CocoDataset'
data_root = r'{dataset_dir.as_posix()}'

train_dataloader = dict(
    batch_size=8,
    num_workers=2,
    persistent_workers=False,
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file='annotations/pose_pseudolabels_train.json',
        data_prefix=dict(img='images/train/'),
    ),
)

val_dataloader = dict(
    batch_size=8,
    num_workers=2,
    persistent_workers=False,
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file='annotations/pose_pseudolabels_val.json',
        data_prefix=dict(img='images/val/'),
        test_mode=True,
    ),
)

test_dataloader = dict(
    batch_size=8,
    num_workers=2,
    persistent_workers=False,
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        ann_file='annotations/pose_pseudolabels_test.json',
        data_prefix=dict(img='images/test/'),
        test_mode=True,
    ),
)

# Recommended training intent:
# - initialize from RTMPose-X Body 17-keypoint checkpoint
# - treat this dataset as pseudo-label adaptation data
# - start with a short low-LR adaptation run
#
# Suggested next manual steps:
# 1. copy an official RTMPose-X COCO config from MMPose
# 2. merge the dataset paths above
# 3. load the chosen checkpoint as init_cfg / load_from
# 4. reduce LR and epochs for adaptation
'''

    output_path.write_text(text, encoding='utf-8')
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
