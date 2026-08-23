# Phase 7 Dataset Inventory

Generated: `2026-06-07T01:19:45.145544+00:00`

## Video Sources

- `vision_datasets`: exists=True, videos=296, domain=phase6_public_private, root=`D:\Program\vision_service\datasets`
- `private_raw_videos`: exists=True, videos=2, domain=private_field, root=`D:\Program\model_test\fall_detection_model_bundle\v3_upgrade_lab\datasets\private_raw_videos`
- `private_dryrun_videos`: exists=True, videos=2, domain=screen_replay, root=`D:\Program\model_test\fall_detection_model_bundle\v3_upgrade_lab\datasets\private_dryrun_videos`
- `external_authorized`: exists=True, videos=160, domain=authorized_external, root=`D:\Program\model_test\fall_detection_model_bundle\v3_upgrade_lab\datasets\external_authorized`

## Phase 7 Video Labels

- rows: 644
- usable_training_rows: 250
- binary_label_counts: `{'non_fall': 87, 'fall': 163}`
- subtype_counts: `{'squatting': 8, 'picking_object': 3, 'bending': 7, 'sitting': 16, 'lying_down_normal': 30, 'fall': 163, 'walking': 16, 'standing': 7}`
- split_counts: `{'val': 35, 'train': 173, 'test': 42}`
- unknown_adl_ratio: 0.0000

## YOLO Sources

- `fall_detect_existing`: exists=True, images=2840, labels=2840, missing_labels=0, splits=`{'train': 2135, 'val': 678, 'test': 27}`, classes=`{'3': 590, '0': 1318, '4': 190, '1': 299, '2': 348, '5': 27}`
- `fall_detect_v2_recall_existing`: exists=True, images=7932, labels=7932, missing_labels=0, splits=`{'train': 3406, 'val': 1014, 'test': 3512}`, classes=`{'3': 1322, '0': 3985, '4': 390, '1': 816, '2': 803, '5': 40}`
- `fall_detect_v3_gmdcsa24_autolabel`: exists=True, images=1246, labels=1246, missing_labels=0, splits=`{'train': 632, 'val': 334, 'test': 280}`, classes=`{'3': 315, '4': 112, '0': 117, '5': 96, '1': 584, '2': 22}`

## Gate Notes

- `D:\Program\数据集` currently acts as an index folder. Phase 7 uses the real dataset roots directly.
- `private_field` and `screen_replay` videos are kept in the manifest; items with uncertain subtype stay `usable_for_training=false` until reviewed.
- YOLO v4 data yaml uses absolute image directories and does not overwrite v3 datasets.
