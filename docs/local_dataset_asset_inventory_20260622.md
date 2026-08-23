# LocalDatasetAssetInventoryBeforePublicDownload Result

Generated: 2026-06-22T16:47:06

```text
【LocalDatasetAssetInventoryBeforePublicDownload Result】

scan_status:
PASS

searched_roots:
- EXISTS D:\Program\vision_service (scanned)
- EXISTS D:\Program\vision_service\datasets (scanned)
- EXISTS D:\Program\vision_service\data (scanned)
- EXISTS D:\Program\vision_service\logs (scanned)
- EXISTS D:\Program\vision_service\artifacts (scanned)
- EXISTS D:\Program\vision_service\evaluations (scanned)
- EXISTS D:\Program\vision_service\models (scanned)
- MISSING/SKIPPED D:\Program\vision_service\videos (not_scanned)
- EXISTS D:\Program\vision_service\scripts (scanned)
- MISSING/SKIPPED D:\datasets (not_scanned)
- EXISTS D:\data (scanned)
- MISSING/SKIPPED D:\fall_dataset (not_scanned)
- MISSING/SKIPPED D:\fall_datasets (not_scanned)
- MISSING/SKIPPED D:\public_datasets (not_scanned)
- MISSING/SKIPPED D:\学校 (not_scanned)
- MISSING/SKIPPED F:\学校 (not_scanned)
- MISSING/SKIPPED F:\datasets (not_scanned)
- MISSING/SKIPPED F:\data (not_scanned)

video_assets_found:
336
dataset_dirs_found:
195
label_files_found:
739
model_files_found:
33
reports_found:
315

candidate_public_datasets:
195
candidate_local_videos:
127
candidate_hard_negative_videos:
166
candidate_replay_videos:
0
existing_labels:
739
existing_pose_or_fall_models:
29

manifest_files:
- D:\Program\vision_service\datasets\fast_pose_fall\local_asset_manifest_20260622.csv
- D:\Program\vision_service\datasets\fast_pose_fall\local_asset_manifest_20260622.jsonl
- D:\Program\vision_service\docs\local_dataset_asset_inventory_20260622.md

recommended_next_action:
- Review candidate public dataset dirs before any re-download; verify completeness and license/source manually.
- Use local real camera videos for local_val first; do not put all local videos into training.
- If local_test is still missing, record/freeze additional held-out videos before tuning against them.
- Manually confirm label semantics, timestamp frame basis, and reviewed/pseudo status before training/eval use.

warnings:
- 9 requested roots were missing/skipped.
- Model weight files were found; they are inference assets and should not be committed unless explicitly intended.

no_files_modified_except_reports:
YES (reports/manifests only)

git_status_after:
?? docs/local_dataset_asset_inventory_20260622.md
?? docs/vscode_startup_guide_20260622.md
note: datasets/fast_pose_fall/local_asset_manifest_20260622.csv and .jsonl are ignored by existing .gitignore rule: datasets/
```

## Searched Roots

|root|status|
|---|---|
|D:\Program\vision_service|EXISTS|
|D:\Program\vision_service\datasets|EXISTS|
|D:\Program\vision_service\data|EXISTS|
|D:\Program\vision_service\logs|EXISTS|
|D:\Program\vision_service\artifacts|EXISTS|
|D:\Program\vision_service\evaluations|EXISTS|
|D:\Program\vision_service\models|EXISTS|
|D:\Program\vision_service\videos|MISSING/SKIPPED|
|D:\Program\vision_service\scripts|EXISTS|
|D:\datasets|MISSING/SKIPPED|
|D:\data|EXISTS|
|D:\fall_dataset|MISSING/SKIPPED|
|D:\fall_datasets|MISSING/SKIPPED|
|D:\public_datasets|MISSING/SKIPPED|
|D:\学校|MISSING/SKIPPED|
|F:\学校|MISSING/SKIPPED|
|F:\datasets|MISSING/SKIPPED|
|F:\data|MISSING/SKIPPED|

## Video Assets

|path|size|duration_sec|fps|frames|resolution|can_open|source|dataset|fall?|non_fall?|usable_for|notes|
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\01.mp4|7.64 MB|8.274|29.612|245|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\02.mp4|6.36 MB|6.69|29.598|198|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\03.mp4|6.29 MB|6.689|29.748|199|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\04.mp4|5.66 MB|5.809|29.263|170|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\05.mp4|9.89 MB|10.546|29.775|314|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\06.mp4|11.85 MB|12.226|29.774|364|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\07.mp4|7.38 MB|7.537|29.719|224|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\08.mp4|6.01 MB|6.289|29.732|187|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\09.mp4|4.61 MB|4.994|29.438|147|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\10.mp4|3.67 MB|3.921|29.328|115|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\11.mp4|8.87 MB|9.314|29.742|277|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\12.mp4|7.36 MB|7.33|29.743|218|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\13.mp4|5.93 MB|6.306|29.656|187|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\14.mp4|5.58 MB|5.858|29.534|173|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\15.mp4|6.90 MB|7.169|29.571|212|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL\16.mp4|3.42 MB|3.521|29.534|104|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\01.mp4|6.57 MB|6.866|29.568|203|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\02.mp4|6.12 MB|6.369|29.673|189|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\03.mp4|5.75 MB|5.922|29.722|176|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\04.mp4|4.74 MB|4.961|29.428|146|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\05.mp4|5.60 MB|5.858|29.705|174|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\06.mp4|5.56 MB|5.697|29.664|169|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\07.mp4|4.84 MB|5.153|29.689|153|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\08.mp4|4.14 MB|4.353|29.632|129|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\09.mp4|4.37 MB|4.482|29.231|131|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\10.mp4|4.14 MB|4.497|29.573|133|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\11.mp4|5.68 MB|6.097|29.685|181|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\12.mp4|6.29 MB|6.833|29.268|200|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\13.mp4|1.32 MB|4.321|29.62|128|640x480|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\14.mp4|1.80 MB|5.697|29.663|169|640x480|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\15.mp4|1.91 MB|6.002|29.659|178|640x480|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall\16.mp4|5.74 MB|6.097|29.685|181|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\01.mp4|11.08 MB|11.394|29.841|340|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\02.mp4|11.31 MB|11.793|29.847|352|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\03.mp4|11.61 MB|11.937|29.822|356|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\04.mp4|7.92 MB|7.842|29.841|234|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\05.mp4|10.65 MB|10.818|29.859|323|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\06.mp4|10.81 MB|10.753|29.851|321|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\07.mp4|12.72 MB|12.993|29.861|388|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\08.mp4|13.35 MB|13.666|29.856|408|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\09.mp4|10.72 MB|10.96|29.834|327|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\10.mp4|7.37 MB|7.568|29.862|226|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\11.mp4|9.67 MB|9.985|29.844|298|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\12.mp4|7.43 MB|7.602|29.862|227|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\13.mp4|4.81 MB|4.848|29.907|145|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\14.mp4|5.68 MB|11.058|15.012|166|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\15.mp4|6.18 MB|11.921|15.015|179|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\16.mp4|5.89 MB|11.537|14.995|173|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\17.mp4|6.04 MB|11.666|15.001|175|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\18.mp4|5.95 MB|11.665|15.002|175|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\19.mp4|5.82 MB|11.329|15.005|170|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\20.mp4|5.97 MB|11.665|15.002|175|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\21.mp4|5.44 MB|10.529|15.006|158|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\22.mp4|6.10 MB|12.129|15.005|182|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\23.mp4|6.03 MB|11.81|14.988|177|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\24.mp4|2.12 MB|11.457|15.012|172|640x480|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\25.mp4|1.36 MB|7.28|14.972|109|640x480|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL\26.mp4|2.19 MB|11.793|15.008|177|640x480|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\01.mp4|6.17 MB|6.368|29.836|190|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\02.mp4|8.20 MB|8.448|29.83|252|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\03.mp4|6.87 MB|7.042|29.823|210|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\04.mp4|10.09 MB|10.21|29.874|305|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\05.mp4|4.52 MB|4.528|29.814|135|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\06.mp4|6.33 MB|6.496|29.864|194|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\07.mp4|4.50 MB|4.528|29.814|135|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\08.mp4|5.95 MB|6.064|29.847|181|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\09.mp4|5.58 MB|5.6|29.821|167|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\10.mp4|5.73 MB|11.138|14.994|167|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\11.mp4|5.48 MB|10.593|15.009|159|1280x720|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\12.mp4|2.28 MB|12.257|15.011|184|640x480|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\13.mp4|1.54 MB|8.896|14.951|133|640x480|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall\14.mp4|2.07 MB|11.201|14.998|168|640x480|True|unknown|fall|True|False|local_val|path/name suggests fall video; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL\01.mp4|8.50 MB|8.754|29.817|261|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL\02.mp4|8.95 MB|9.138|29.877|273|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL\03.mp4|9.63 MB|9.922|29.833|296|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL\04.mp4|9.82 MB|10.05|29.852|300|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL\05.mp4|5.16 MB|5.169|29.791|154|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL\06.mp4|8.66 MB|8.945|29.848|267|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL\07.mp4|3.43 MB|3.345|29.891|100|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|
|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL\08.mp4|4.93 MB|4.896|29.819|146|1280x720|True|unknown|fall|True|True|hard_negative_test|path/name suggests fall video; path/name suggests non-fall or hard negative; source unclear|

_... 256 more rows omitted; see manifest files._

## Dataset Directory Candidates

|dataset_name_guess|path|file_count|video_count|label_file_count|size|status|usable_for|
|---|---|---|---|---|---|---|---|
|URFall|D:\Program\vision_service\data\temporal_sequences\ur_fall|21|0|21|1.36 MB|partial|public_train, public_val|
|URFall|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall|64|0|64|3.55 MB|partial|public_train, public_val|
|URFall|D:\Program\vision_service\data\temporal_sequences_phase6d\ur_fall|64|0|64|3.55 MB|partial|public_train, public_val|
|URFall|D:\Program\vision_service\data\temporal_sequences_phase6d\ur_fall_cam1|3|0|3|42.95 KB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51|120|112|6|688.20 MB|complete|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1|34|32|2|182.02 MB|complete|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL|16|16|0|107.41 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall|16|16|0|74.60 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2|42|40|2|269.55 MB|complete|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL|26|26|0|194.22 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall|14|14|0|75.32 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3|42|40|2|236.63 MB|complete|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL|20|20|0|128.09 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\Fall|20|20|0|108.53 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151501_fall_simulated_back_retake_b|92|0|1|5.49 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151501_fall_simulated_back_retake_b\images|89|0|0|4.64 MB|unknown|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161300_fall_simulated_side|92|0|1|5.57 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161300_fall_simulated_side\images|89|0|0|4.70 MB|unknown|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161400_fall_simulated_back|91|0|1|5.36 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161400_fall_simulated_back\images|88|0|0|4.50 MB|unknown|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161500_fallen_hold|33|0|1|1.86 MB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161500_fallen_hold\images|30|0|0|1.58 MB|unknown|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_fall_simulated_back_long_take_ec4c95|5|0|2|181.00 KB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_fall_simulated_back_short_take_20eab7|5|0|2|176.11 KB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_mixed_fall_and_seated_recovery_87b7d5|5|0|2|190.25 KB|partial|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151501_fall_simulated_back_retake_b|8|1|3|8.49 MB|complete|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151501_fall_simulated_back_retake_b\frames_optional|0|0|0|0.00 B|unknown|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161300_fall_simulated_side|8|1|3|12.94 MB|complete|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161300_fall_simulated_side\frames_optional|0|0|0|0.00 B|unknown|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161400_fall_simulated_back|8|1|3|12.78 MB|complete|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161400_fall_simulated_back\frames_optional|0|0|0|0.00 B|unknown|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161500_fallen_hold|8|1|3|9.96 MB|complete|public_train, public_val|
|fall|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161500_fallen_hold\frames_optional|0|0|0|0.00 B|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall|12076|70|0|8.52 GB|partial|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw|12006|0|0|8.36 GB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-01-cam0-rgb|150|0|0|65.85 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-01-cam0-rgb\adl-01-cam0-rgb|150|0|0|65.85 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-02-cam0-rgb|180|0|0|79.58 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-02-cam0-rgb\adl-02-cam0-rgb|180|0|0|79.58 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-03-cam0-rgb|180|0|0|80.46 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-03-cam0-rgb\adl-03-cam0-rgb|180|0|0|80.46 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-04-cam0-rgb|150|0|0|67.38 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-04-cam0-rgb\adl-04-cam0-rgb|150|0|0|67.38 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-05-cam0-rgb|180|0|0|81.34 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-05-cam0-rgb\adl-05-cam0-rgb|180|0|0|81.34 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-06-cam0-rgb|230|0|0|103.24 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-06-cam0-rgb\adl-06-cam0-rgb|230|0|0|103.24 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-07-cam0-rgb|180|0|0|80.50 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-07-cam0-rgb\adl-07-cam0-rgb|180|0|0|80.50 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-08-cam0-rgb|180|0|0|79.93 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-08-cam0-rgb\adl-08-cam0-rgb|180|0|0|79.93 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-09-cam0-rgb|150|0|0|66.33 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-09-cam0-rgb\adl-09-cam0-rgb|150|0|0|66.33 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-10-cam0-rgb|300|0|0|133.74 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-10-cam0-rgb\adl-10-cam0-rgb|300|0|0|133.74 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-11-cam0-rgb|300|0|0|132.73 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-11-cam0-rgb\adl-11-cam0-rgb|300|0|0|132.73 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-12-cam0-rgb|250|0|0|104.35 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-12-cam0-rgb\adl-12-cam0-rgb|250|0|0|104.35 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-13-cam0-rgb|265|0|0|109.54 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-13-cam0-rgb\adl-13-cam0-rgb|265|0|0|109.54 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-14-cam0-rgb|235|0|0|97.34 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-14-cam0-rgb\adl-14-cam0-rgb|235|0|0|97.34 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-15-cam0-rgb|275|0|0|115.03 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-15-cam0-rgb\adl-15-cam0-rgb|275|0|0|115.03 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-16-cam0-rgb|240|0|0|99.00 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-16-cam0-rgb\adl-16-cam0-rgb|240|0|0|99.00 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-17-cam0-rgb|230|0|0|95.25 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-17-cam0-rgb\adl-17-cam0-rgb|230|0|0|95.25 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-18-cam0-rgb|265|0|0|110.39 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-18-cam0-rgb\adl-18-cam0-rgb|265|0|0|110.39 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-19-cam0-rgb|250|0|0|104.58 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-19-cam0-rgb\adl-19-cam0-rgb|250|0|0|104.58 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-20-cam0-rgb|270|0|0|112.81 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-20-cam0-rgb\adl-20-cam0-rgb|270|0|0|112.81 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-21-cam0-rgb|280|0|0|116.52 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-21-cam0-rgb\adl-21-cam0-rgb|280|0|0|116.52 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-22-cam0-rgb|240|0|0|100.18 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-22-cam0-rgb\adl-22-cam0-rgb|240|0|0|100.18 MB|unknown|public_train, public_val|
|URFall|D:\Program\vision_service\datasets\ur_fall\raw\adl-23-cam0-rgb|220|0|0|92.43 MB|unknown|public_train, public_val|

_... 115 more rows omitted; see manifest files._

## Label Files

|path|format_guess|contains_fall_label|contains_bbox|contains_keypoints|contains_timestamps|reviewed_or_pseudo|notes|
|---|---|---|---|---|---|---|---|
|D:\Program\vision_service\requirements.txt|txt|False|False|True|False|unknown|contains keypoint/pose token|
|D:\Program\vision_service\.vscode\tasks.json|json|False|False|False|False|unknown|label-like path/content; manual confirmation needed|
|D:\Program\vision_service\data\alert_probe_target.json|json|True|False|False|False|unknown|contains fall label/token|
|D:\Program\vision_service\data\phase6_labels\phase6_labels.jsonl|jsonl|True|False|False|False|unknown|contains fall label/token|
|D:\Program\vision_service\data\phase7_labels\phase7_video_labels.jsonl|jsonl|True|False|False|False|unknown|contains fall label/token|
|D:\Program\vision_service\data\phase7_labels\phase7_yolo_labels_manifest.jsonl|jsonl|True|False|False|False|unknown|contains fall label/token|
|D:\Program\vision_service\data\phase9_labels\phase9_e2e_test_manifest.jsonl|jsonl|True|False|False|False|unknown|contains fall label/token|
|D:\Program\vision_service\data\phase9_labels\phase9_video_manifest.jsonl|jsonl|True|False|False|False|unknown|contains fall label/token|
|D:\Program\vision_service\data\pose_adaptation_dataset\summary.json|json|False|False|False|False|unknown|label-like path/content; manual confirmation needed|
|D:\Program\vision_service\data\pose_adaptation_dataset\annotations\pose_pseudolabels_test.json|json|True|True|True|False|pseudo|contains fall label/token; contains bbox token; contains keypoint/pose token|
|D:\Program\vision_service\data\pose_adaptation_dataset\annotations\pose_pseudolabels_train.json|json|True|True|True|False|pseudo|contains fall label/token; contains bbox token; contains keypoint/pose token|
|D:\Program\vision_service\data\pose_adaptation_dataset\annotations\pose_pseudolabels_val.json|json|True|True|True|False|pseudo|contains fall label/token; contains bbox token; contains keypoint/pose token|
|D:\Program\vision_service\data\pose_adaptation_dataset_full\summary.json|json|False|False|False|False|unknown|label-like path/content; manual confirmation needed|
|D:\Program\vision_service\data\pose_adaptation_dataset_full\annotations\pose_pseudolabels_test.json|json|True|True|True|False|pseudo|contains fall label/token; contains bbox token; contains keypoint/pose token|
|D:\Program\vision_service\data\pose_adaptation_dataset_full\annotations\pose_pseudolabels_train.json|json|True|False|True|False|pseudo|contains fall label/token; contains keypoint/pose token|
|D:\Program\vision_service\data\pose_adaptation_dataset_full\annotations\pose_pseudolabels_val.json|json|True|True|True|False|pseudo|contains fall label/token; contains bbox token; contains keypoint/pose token|
|D:\Program\vision_service\data\pose_pseudolabels\actor_1_fall_01.jsonl|jsonl|True|True|True|False|pseudo|contains fall label/token; contains bbox token; contains keypoint/pose token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-01.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-02.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-03.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-04.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-05.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-06.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-07.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-08.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-09.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-10.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-11.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\adl-12.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\export_summary.json|json|True|False|False|False|unknown|contains fall label/token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\fall-01.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\fall-02.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\fall-03.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\fall-04.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\fall-05.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\fall-06.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\fall-07.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\fall-08.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-01.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-02.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-03.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-04.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-05.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-06.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-07.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-08.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-09.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-10.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-11.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-12.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-13.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-14.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-15.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-16.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-17.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-18.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-19.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-20.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-21.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-22.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-23.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-24.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-25.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-26.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-27.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-28.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-29.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-30.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-35.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-36.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\adl-37.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\export_summary.json|json|True|False|False|False|unknown|contains fall label/token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\fall-01.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\fall-02.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\fall-03.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\fall-04.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\fall-05.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\fall-06.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\fall-07.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\fall-08.jsonl|jsonl|True|True|True|True|unknown|contains fall label/token; contains bbox token; contains keypoint/pose token; contains timestamp/frame range token|

_... 659 more rows omitted; see manifest files._

## Model Files

|path|model_type_guess|file_size|mtime|should_not_commit|notes|
|---|---|---|---|---|---|
|D:\Program\vision_service\yolo11m.pt|detector|38.80 MB|2026-06-08T09:27:39|YES|should_not_commit=true; YOLO family|
|D:\Program\vision_service\yolo11n-pose.pt|pose|5.97 MB|2026-06-18T10:00:48|YES|should_not_commit=true; YOLO family|
|D:\Program\vision_service\yolo11n.pt|detector|5.35 MB|2026-06-07T09:25:08|YES|should_not_commit=true; YOLO family|
|D:\Program\vision_service\yolo11s-pose.pt|pose|19.43 MB|2026-06-08T13:09:56|YES|should_not_commit=true; YOLO family|
|D:\Program\vision_service\yolo11s.pt|detector|18.42 MB|2026-06-08T09:27:35|YES|should_not_commit=true; YOLO family|
|D:\Program\vision_service\yolo26n-pose.pt|pose|7.51 MB|2026-05-18T14:14:59|YES|should_not_commit=true; YOLO family|
|D:\Program\vision_service\yolov8n-pose.pt|pose|6.52 MB|2026-06-03T16:42:11|YES|should_not_commit=true; requested重点权重; YOLO family|
|D:\Program\vision_service\yolov8n.pt|detector|6.25 MB|2026-06-02T10:10:13|YES|should_not_commit=true; requested重点权重; YOLO family|
|D:\Program\vision_service\yolo_fall_detector_v2_recall_probe_best.pt|fall/classifier|18.28 MB|2026-05-06T12:46:47|YES|should_not_commit=true; YOLO family; fall-related name|
|D:\Program\vision_service\models\fall_lstm.onnx|fall/classifier|83.23 KB|2026-06-05T10:43:42|YES|should_not_commit=true; fall-related name|
|D:\Program\vision_service\models\fall_lstm_v2.onnx|fall/classifier|83.62 KB|2026-06-05T11:52:30|YES|should_not_commit=true; fall-related name|
|D:\Program\vision_service\models\fall_lstm_v3.onnx|fall/classifier|83.62 KB|2026-06-05T15:11:26|YES|should_not_commit=true; fall-related name|
|D:\Program\vision_service\models\fall_lstm_v4.onnx|fall/classifier|83.62 KB|2026-06-07T09:57:28|YES|should_not_commit=true; fall-related name|
|D:\Program\vision_service\models\fall_lstm_v5.onnx|fall/classifier|83.62 KB|2026-06-08T14:42:06|YES|should_not_commit=true; fall-related name|
|D:\Program\vision_service\models\yolo_fall_detector_phase8_selected.pt|fall/classifier|18.29 MB|2026-06-08T11:02:38|YES|should_not_commit=true; YOLO family; fall-related name|
|D:\Program\vision_service\models\yolo_fall_detector_phase9_selected.pt|fall/classifier|18.29 MB|2026-06-08T11:02:38|YES|should_not_commit=true; YOLO family; fall-related name|
|D:\Program\vision_service\models\yolo_fall_detector_v4_best.pt|fall/classifier|15.37 MB|2026-06-07T09:48:10|YES|should_not_commit=true; YOLO family; fall-related name|
|D:\Program\vision_service\models\yolo_fall_detector_v5_best.pt|fall/classifier|18.29 MB|2026-06-08T11:02:38|YES|should_not_commit=true; YOLO family; fall-related name|
|D:\Program\vision_service\models\yolo_fall_detector_v6_best.pt|fall/classifier|115.51 MB|2026-06-08T14:21:05|YES|should_not_commit=true; YOLO family; fall-related name|
|D:\Program\vision_service\models\rtmpose\rtmpose-l-aic-coco-384x288-state_dict.pth|pose|106.34 MB|2026-06-15T12:58:29|YES|should_not_commit=true|
|D:\Program\vision_service\models\rtmpose\rtmpose-l-aic-coco-384x288.pth|pose|106.27 MB|2023-04-18T14:29:14|YES|should_not_commit=true|
|D:\Program\vision_service\models\rtmpose\rtmpose-l-pose-adapted-best.pth|pose|106.38 MB|2026-06-15T13:03:56|YES|should_not_commit=true|
|D:\Program\vision_service\models\rtmpose\rtmpose-x-body7-384x288.onnx|pose|188.50 MB|2023-08-31T12:19:18|YES|should_not_commit=true|
|D:\Program\vision_service\models\rtmpose\rtmpose-x-body7-384x288\20230831\rtmpose_onnx\rtmpose-x_simcc-body7_pt-body7_700e-384x288-71d7b7e9_20230629\end2end.onnx|pose|188.50 MB|2023-08-31T12:19:18|YES|should_not_commit=true|
|D:\Program\vision_service\runs\phase7_yolo_v4\fall_detector_v4\weights\best.pt|fall/classifier|15.37 MB|2026-06-07T09:48:10|YES|should_not_commit=true|
|D:\Program\vision_service\runs\phase7_yolo_v4\fall_detector_v4\weights\last.pt|fall/classifier|15.37 MB|2026-06-07T09:48:10|YES|should_not_commit=true|
|D:\Program\vision_service\runs\phase8_yolo_v5\fall_detector_v5_yolo11s\weights\best.pt|fall/classifier|18.29 MB|2026-06-08T11:02:38|YES|should_not_commit=true|
|D:\Program\vision_service\runs\phase8_yolo_v5\fall_detector_v5_yolo11s\weights\last.pt|fall/classifier|18.29 MB|2026-06-08T11:02:38|YES|should_not_commit=true|
|D:\Program\vision_service\runs\phase9_yolo_v6\fall_detector_v6\weights\best.pt|fall/classifier|115.51 MB|2026-06-08T14:21:05|YES|should_not_commit=true|
|D:\Program\vision_service\runs\phase9_yolo_v6\fall_detector_v6\weights\last.pt|fall/classifier|115.51 MB|2026-06-08T14:21:05|YES|should_not_commit=true|
|D:\Program\vision_service\runs\rtmpose_adaptation_l_384x288\best_coco_AP_epoch_3.pth|pose|106.38 MB|2026-06-15T13:03:56|YES|should_not_commit=true|
|D:\Program\vision_service\runs\rtmpose_adaptation_l_384x288\epoch_1.pth|pose|318.65 MB|2026-06-15T13:01:41|YES|should_not_commit=true|
|D:\Program\vision_service\runs\rtmpose_adaptation_l_384x288\epoch_3.pth|pose|318.65 MB|2026-06-15T13:03:59|YES|should_not_commit=true|

## Existing Reports / Experiment Results

|path|summary_guess|related_to_fall|related_to_pose|related_to_dataset|
|---|---|---|---|---|
|D:\Program\vision_service\README.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\data\phase6_labels\README.md|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\data\pose_adaptation_dataset\summary.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\data\pose_adaptation_dataset_full\summary.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\data\temporal_sequences\ur_fall\export_summary.json|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall\export_summary.json|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\data\temporal_sequences_phase6d\gmdcsa24\export_summary.json|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\data\temporal_sequences_phase6d\ur_fall\export_summary.json|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\data\temporal_sequences_phase6d\ur_fall_cam1\export_summary.json|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\datasets\new_pose_frames\frame_selection_curated_report_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\frame_selection_report_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\frame_selection_report_after_retake_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151001_no_person_retake_b\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151101_sitting_normal_retake_b\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151201_sitting_side_retake_b\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151301_squat_retake_b\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151401_lying_back_retake_b\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151501_fall_simulated_back_retake_b\frame_qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151601_recovery_standing_retake_b\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160100_no_person\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160200_standing_front\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160300_standing_side\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160400_standing_back\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160500_walking_slow\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160600_sitting_normal\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160700_sitting_side\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160800_bending_pickup\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_160900_squat\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161000_lying_side\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161100_lying_back\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161200_lying_prone\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161300_fall_simulated_side\frame_qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161400_fall_simulated_back\frame_qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161500_fallen_hold\frame_qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161600_recovery_standing\frame_qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175141_standing_front_long_take_a64f9b\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175141_standing_front_long_take_a64f9b\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_fall_simulated_back_long_take_ec4c95\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_fall_simulated_back_long_take_ec4c95\qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_fall_simulated_back_short_take_20eab7\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_fall_simulated_back_short_take_20eab7\qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_mixed_fall_and_seated_recovery_87b7d5\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_mixed_fall_and_seated_recovery_87b7d5\qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_mixed_floor_sit_transition_574c42\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_mixed_floor_sit_transition_574c42\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\dataset_raw_qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\README.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151001_no_person_retake_b\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151001_no_person_retake_b\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151101_sitting_normal_retake_b\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151101_sitting_normal_retake_b\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151201_sitting_side_retake_b\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151201_sitting_side_retake_b\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151301_squat_retake_b\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151301_squat_retake_b\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151401_lying_back_retake_b\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151401_lying_back_retake_b\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151501_fall_simulated_back_retake_b\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151501_fall_simulated_back_retake_b\qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151601_recovery_standing_retake_b\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151601_recovery_standing_retake_b\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160100_no_person\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160100_no_person\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160200_standing_front\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160200_standing_front\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160300_standing_side\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160300_standing_side\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160400_standing_back\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160400_standing_back\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160500_walking_slow\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160500_walking_slow\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160600_sitting_normal\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160600_sitting_normal\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160700_sitting_side\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160700_sitting_side\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160800_bending_pickup\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160800_bending_pickup\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160900_squat\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_160900_squat\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161000_lying_side\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161000_lying_side\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161100_lying_back\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161100_lying_back\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161200_lying_prone\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161200_lying_prone\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161300_fall_simulated_side\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161300_fall_simulated_side\qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161400_fall_simulated_back\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161400_fall_simulated_back\qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161500_fallen_hold\metadata.json|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161500_fallen_hold\qa_report.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161600_recovery_standing\metadata.json|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161600_recovery_standing\qa_report.md|pose-related; dataset-related|False|True|True|
|D:\Program\vision_service\docs\bridge_integration_final_handoff_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\codex_debug_rules.md|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\docs\current_issue_inventory_2026-06-20.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\engineer_handoff_2026-06-19.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\expert_handoff_10h_execution_plan.md|pose-related|False|True|False|
|D:\Program\vision_service\docs\expert_handoff_project_status.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\fall_alarm_popup_failure_analysis_2026-06-16.md|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\docs\fall_replay_dryrun_final_handoff_20260622.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\health_main_fall_event_integration.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\interface_api_spec_2026-06-19.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\interface_function_spec_2026-06-19.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\interface_requirements_2026-06-15.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\legacy_69_service_audit_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\legacy_69_service_checkout_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\main_system_integration_plan.md|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\docs\main_system_interface_status_2026-06-16.md|fall-related; dataset-related|True|False|True|
|D:\Program\vision_service\docs\new_pose_batch_b_manual_review_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_collection_protocol_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_contract_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_dataset_structure_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_data_audit_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_external_mp4_intake_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_frame_extraction_phase4_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_manual_collection_batch_a_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_manual_collection_batch_b_retake_20260621.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_model_training_reintegration_plan_2026-06-21.md|fall-related; pose-related; dataset-related|True|True|True|
|D:\Program\vision_service\docs\new_pose_reintegration_plan_20260621.md|fall-related; pose-related; dataset-related|True|True|True|

_... 195 more rows omitted; see manifest files._

## Initial Classification

|class|path|reason|
|---|---|---|
|A public_train/public_val candidate|D:\Program\vision_service\data\temporal_sequences\ur_fall|dataset_guess=URFall; file_count=21; video_count=0; label_file_count=21; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\data\temporal_sequences_phase6c\ur_fall|dataset_guess=URFall; file_count=64; video_count=0; label_file_count=64; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\data\temporal_sequences_phase6d\ur_fall|dataset_guess=URFall; file_count=64; video_count=0; label_file_count=64; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\data\temporal_sequences_phase6d\ur_fall_cam1|dataset_guess=URFall; file_count=3; video_count=0; label_file_count=3; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51|dataset_guess=fall; file_count=120; video_count=112; label_file_count=6; status=complete|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1|dataset_guess=fall; file_count=34; video_count=32; label_file_count=2; status=complete|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\ADL|dataset_guess=fall; file_count=16; video_count=16; label_file_count=0; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 1\Fall|dataset_guess=fall; file_count=16; video_count=16; label_file_count=0; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2|dataset_guess=fall; file_count=42; video_count=40; label_file_count=2; status=complete|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\ADL|dataset_guess=fall; file_count=26; video_count=26; label_file_count=0; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 2\Fall|dataset_guess=fall; file_count=14; video_count=14; label_file_count=0; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3|dataset_guess=fall; file_count=42; video_count=40; label_file_count=2; status=complete|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\ADL|dataset_guess=fall; file_count=20; video_count=20; label_file_count=0; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\gmdcsa24\source\ekramalam-GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos-75b2c51\Actor 3\Fall|dataset_guess=fall; file_count=20; video_count=20; label_file_count=0; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151501_fall_simulated_back_retake_b|dataset_guess=fall; file_count=92; video_count=0; label_file_count=1; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_151501_fall_simulated_back_retake_b\images|dataset_guess=fall; file_count=89; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161300_fall_simulated_side|dataset_guess=fall; file_count=92; video_count=0; label_file_count=1; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161300_fall_simulated_side\images|dataset_guess=fall; file_count=89; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161400_fall_simulated_back|dataset_guess=fall; file_count=91; video_count=0; label_file_count=1; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161400_fall_simulated_back\images|dataset_guess=fall; file_count=88; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161500_fallen_hold|dataset_guess=fall; file_count=33; video_count=0; label_file_count=1; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_frames\camera_01\session_20260621_161500_fallen_hold\images|dataset_guess=fall; file_count=30; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_fall_simulated_back_long_take_ec4c95|dataset_guess=fall; file_count=5; video_count=0; label_file_count=2; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_fall_simulated_back_short_take_20eab7|dataset_guess=fall; file_count=5; video_count=0; label_file_count=2; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_imports\camera_01\session_20260621_175142_mixed_fall_and_seated_recovery_87b7d5|dataset_guess=fall; file_count=5; video_count=0; label_file_count=2; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151501_fall_simulated_back_retake_b|dataset_guess=fall; file_count=8; video_count=1; label_file_count=3; status=complete|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_151501_fall_simulated_back_retake_b\frames_optional|dataset_guess=fall; file_count=0; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161300_fall_simulated_side|dataset_guess=fall; file_count=8; video_count=1; label_file_count=3; status=complete|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161300_fall_simulated_side\frames_optional|dataset_guess=fall; file_count=0; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161400_fall_simulated_back|dataset_guess=fall; file_count=8; video_count=1; label_file_count=3; status=complete|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161400_fall_simulated_back\frames_optional|dataset_guess=fall; file_count=0; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161500_fallen_hold|dataset_guess=fall; file_count=8; video_count=1; label_file_count=3; status=complete|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\new_pose_raw\camera_01\session_20260621_161500_fallen_hold\frames_optional|dataset_guess=fall; file_count=0; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall|dataset_guess=URFall; file_count=12076; video_count=70; label_file_count=0; status=partial|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw|dataset_guess=URFall; file_count=12006; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-01-cam0-rgb|dataset_guess=URFall; file_count=150; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-01-cam0-rgb\adl-01-cam0-rgb|dataset_guess=URFall; file_count=150; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-02-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-02-cam0-rgb\adl-02-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-03-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-03-cam0-rgb\adl-03-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-04-cam0-rgb|dataset_guess=URFall; file_count=150; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-04-cam0-rgb\adl-04-cam0-rgb|dataset_guess=URFall; file_count=150; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-05-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-05-cam0-rgb\adl-05-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-06-cam0-rgb|dataset_guess=URFall; file_count=230; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-06-cam0-rgb\adl-06-cam0-rgb|dataset_guess=URFall; file_count=230; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-07-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-07-cam0-rgb\adl-07-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-08-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-08-cam0-rgb\adl-08-cam0-rgb|dataset_guess=URFall; file_count=180; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-09-cam0-rgb|dataset_guess=URFall; file_count=150; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-09-cam0-rgb\adl-09-cam0-rgb|dataset_guess=URFall; file_count=150; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-10-cam0-rgb|dataset_guess=URFall; file_count=300; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-10-cam0-rgb\adl-10-cam0-rgb|dataset_guess=URFall; file_count=300; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-11-cam0-rgb|dataset_guess=URFall; file_count=300; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-11-cam0-rgb\adl-11-cam0-rgb|dataset_guess=URFall; file_count=300; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-12-cam0-rgb|dataset_guess=URFall; file_count=250; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-12-cam0-rgb\adl-12-cam0-rgb|dataset_guess=URFall; file_count=250; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-13-cam0-rgb|dataset_guess=URFall; file_count=265; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-13-cam0-rgb\adl-13-cam0-rgb|dataset_guess=URFall; file_count=265; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-14-cam0-rgb|dataset_guess=URFall; file_count=235; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-14-cam0-rgb\adl-14-cam0-rgb|dataset_guess=URFall; file_count=235; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-15-cam0-rgb|dataset_guess=URFall; file_count=275; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-15-cam0-rgb\adl-15-cam0-rgb|dataset_guess=URFall; file_count=275; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-16-cam0-rgb|dataset_guess=URFall; file_count=240; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-16-cam0-rgb\adl-16-cam0-rgb|dataset_guess=URFall; file_count=240; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-17-cam0-rgb|dataset_guess=URFall; file_count=230; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-17-cam0-rgb\adl-17-cam0-rgb|dataset_guess=URFall; file_count=230; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-18-cam0-rgb|dataset_guess=URFall; file_count=265; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-18-cam0-rgb\adl-18-cam0-rgb|dataset_guess=URFall; file_count=265; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-19-cam0-rgb|dataset_guess=URFall; file_count=250; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-19-cam0-rgb\adl-19-cam0-rgb|dataset_guess=URFall; file_count=250; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-20-cam0-rgb|dataset_guess=URFall; file_count=270; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-20-cam0-rgb\adl-20-cam0-rgb|dataset_guess=URFall; file_count=270; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-21-cam0-rgb|dataset_guess=URFall; file_count=280; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-21-cam0-rgb\adl-21-cam0-rgb|dataset_guess=URFall; file_count=280; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-22-cam0-rgb|dataset_guess=URFall; file_count=240; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-22-cam0-rgb\adl-22-cam0-rgb|dataset_guess=URFall; file_count=240; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-23-cam0-rgb|dataset_guess=URFall; file_count=220; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-23-cam0-rgb\adl-23-cam0-rgb|dataset_guess=URFall; file_count=220; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-24-cam0-rgb|dataset_guess=URFall; file_count=70; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-24-cam0-rgb\adl-24-cam0-rgb|dataset_guess=URFall; file_count=70; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-25-cam0-rgb|dataset_guess=URFall; file_count=110; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-25-cam0-rgb\adl-25-cam0-rgb|dataset_guess=URFall; file_count=110; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-26-cam0-rgb|dataset_guess=URFall; file_count=95; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-26-cam0-rgb\adl-26-cam0-rgb|dataset_guess=URFall; file_count=95; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-27-cam0-rgb|dataset_guess=URFall; file_count=100; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-27-cam0-rgb\adl-27-cam0-rgb|dataset_guess=URFall; file_count=100; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-28-cam0-rgb|dataset_guess=URFall; file_count=85; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-28-cam0-rgb\adl-28-cam0-rgb|dataset_guess=URFall; file_count=85; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-29-cam0-rgb|dataset_guess=URFall; file_count=125; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-29-cam0-rgb\adl-29-cam0-rgb|dataset_guess=URFall; file_count=125; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-30-cam0-rgb|dataset_guess=URFall; file_count=400; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-30-cam0-rgb\adl-30-cam0-rgb|dataset_guess=URFall; file_count=400; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-31-cam0-rgb|dataset_guess=URFall; file_count=250; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-31-cam0-rgb\adl-31-cam0-rgb|dataset_guess=URFall; file_count=250; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-32-cam0-rgb|dataset_guess=URFall; file_count=200; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-32-cam0-rgb\adl-32-cam0-rgb|dataset_guess=URFall; file_count=200; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-33-cam0-rgb|dataset_guess=URFall; file_count=200; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-33-cam0-rgb\adl-33-cam0-rgb|dataset_guess=URFall; file_count=200; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-34-cam0-rgb|dataset_guess=URFall; file_count=191; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-34-cam0-rgb\adl-34-cam0-rgb|dataset_guess=URFall; file_count=191; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-35-cam0-rgb|dataset_guess=URFall; file_count=280; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-35-cam0-rgb\adl-35-cam0-rgb|dataset_guess=URFall; file_count=280; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-36-cam0-rgb|dataset_guess=URFall; file_count=340; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-36-cam0-rgb\adl-36-cam0-rgb|dataset_guess=URFall; file_count=340; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-37-cam0-rgb|dataset_guess=URFall; file_count=350; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-37-cam0-rgb\adl-37-cam0-rgb|dataset_guess=URFall; file_count=350; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-38-cam0-rgb|dataset_guess=URFall; file_count=345; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-38-cam0-rgb\adl-38-cam0-rgb|dataset_guess=URFall; file_count=345; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-39-cam0-rgb|dataset_guess=URFall; file_count=270; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-39-cam0-rgb\adl-39-cam0-rgb|dataset_guess=URFall; file_count=270; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-40-cam0-rgb|dataset_guess=URFall; file_count=330; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\adl-40-cam0-rgb\adl-40-cam0-rgb|dataset_guess=URFall; file_count=330; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-01-cam0-rgb|dataset_guess=URFall; file_count=160; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-01-cam0-rgb\fall-01-cam0-rgb|dataset_guess=URFall; file_count=160; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-02-cam0-rgb|dataset_guess=URFall; file_count=110; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-02-cam0-rgb\fall-02-cam0-rgb|dataset_guess=URFall; file_count=110; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-03-cam0-rgb|dataset_guess=URFall; file_count=215; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-03-cam0-rgb\fall-03-cam0-rgb|dataset_guess=URFall; file_count=215; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-04-cam0-rgb|dataset_guess=URFall; file_count=96; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-04-cam0-rgb\fall-04-cam0-rgb|dataset_guess=URFall; file_count=96; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-05-cam0-rgb|dataset_guess=URFall; file_count=151; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-05-cam0-rgb\fall-05-cam0-rgb|dataset_guess=URFall; file_count=151; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-06-cam0-rgb|dataset_guess=URFall; file_count=100; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-06-cam0-rgb\fall-06-cam0-rgb|dataset_guess=URFall; file_count=100; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-07-cam0-rgb|dataset_guess=URFall; file_count=156; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-07-cam0-rgb\fall-07-cam0-rgb|dataset_guess=URFall; file_count=156; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-08-cam0-rgb|dataset_guess=URFall; file_count=91; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-08-cam0-rgb\fall-08-cam0-rgb|dataset_guess=URFall; file_count=91; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-09-cam0-rgb|dataset_guess=URFall; file_count=185; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-09-cam0-rgb\fall-09-cam0-rgb|dataset_guess=URFall; file_count=185; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-10-cam0-rgb|dataset_guess=URFall; file_count=130; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-10-cam0-rgb\fall-10-cam0-rgb|dataset_guess=URFall; file_count=130; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-11-cam0-rgb|dataset_guess=URFall; file_count=130; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-11-cam0-rgb\fall-11-cam0-rgb|dataset_guess=URFall; file_count=130; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-12-cam0-rgb|dataset_guess=URFall; file_count=110; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-12-cam0-rgb\fall-12-cam0-rgb|dataset_guess=URFall; file_count=110; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-13-cam0-rgb|dataset_guess=URFall; file_count=85; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-13-cam0-rgb\fall-13-cam0-rgb|dataset_guess=URFall; file_count=85; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-14-cam0-rgb|dataset_guess=URFall; file_count=61; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-14-cam0-rgb\fall-14-cam0-rgb|dataset_guess=URFall; file_count=61; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-15-cam0-rgb|dataset_guess=URFall; file_count=71; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-15-cam0-rgb\fall-15-cam0-rgb|dataset_guess=URFall; file_count=71; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-16-cam0-rgb|dataset_guess=URFall; file_count=55; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-16-cam0-rgb\fall-16-cam0-rgb|dataset_guess=URFall; file_count=55; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-17-cam0-rgb|dataset_guess=URFall; file_count=95; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-17-cam0-rgb\fall-17-cam0-rgb|dataset_guess=URFall; file_count=95; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-18-cam0-rgb|dataset_guess=URFall; file_count=65; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-18-cam0-rgb\fall-18-cam0-rgb|dataset_guess=URFall; file_count=65; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-19-cam0-rgb|dataset_guess=URFall; file_count=100; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-19-cam0-rgb\fall-19-cam0-rgb|dataset_guess=URFall; file_count=100; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-20-cam0-rgb|dataset_guess=URFall; file_count=110; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-20-cam0-rgb\fall-20-cam0-rgb|dataset_guess=URFall; file_count=110; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-21-cam0-rgb|dataset_guess=URFall; file_count=55; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-21-cam0-rgb\fall-21-cam0-rgb|dataset_guess=URFall; file_count=55; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-22-cam0-rgb|dataset_guess=URFall; file_count=56; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-22-cam0-rgb\fall-22-cam0-rgb|dataset_guess=URFall; file_count=56; video_count=0; label_file_count=0; status=unknown|
|A public_train/public_val candidate|D:\Program\vision_service\datasets\ur_fall\raw\fall-23-cam0-rgb|dataset_guess=URFall; file_count=75; video_count=0; label_file_count=0; status=unknown|

_... 1111 more rows omitted; see manifest files._
