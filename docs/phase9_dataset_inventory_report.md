# Phase 9 Dataset Inventory Report

Generated: `2026-06-08T05:58:04.442797+00:00`

## Video Manifest

- total videos: 460
- trainable videos: 82
- e2e frozen videos: 4
- by label: `{'non_fall': 377, 'fall': 83}`
- by split: `{'test': 68, 'val': 60, 'train': 328, 'e2e_test': 4}`
- by subtype: `{'unknown_adl': 377, 'fall': 83}`

## YOLO Sources

- fall_detect_existing: images=2840, labels=2840, classes=`{'3': 590, '0': 1318, '4': 190, '1': 299, '2': 348, '5': 27}`
- fall_detect_v2_recall_existing: images=7932, labels=7932, classes=`{'3': 1322, '0': 3985, '4': 390, '1': 816, '2': 803, '5': 40}`
- fall_detect_v3_gmdcsa24_autolabel: images=1246, labels=1246, classes=`{'3': 315, '4': 112, '0': 117, '5': 96, '1': 584, '2': 22}`

## Gates

- e2e_fall_count: 1
- e2e_adl_count: 3
- unknown_adl_train_ratio: 0.0000
- yolo_has_train_val_test: True
