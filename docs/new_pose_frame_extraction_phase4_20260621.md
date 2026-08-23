# New Pose Frame Extraction Phase 4

鏃ユ湡: `2026-06-21`

浠撳簱: `D:\Program\vision_service`

commit: `c6da604`

## Baseline Check

- runtime_profile: `current_camera_live`
- pose_enabled: `false`
- pose_provider: `disabled_placeholder`
- no_pose_baseline_check: `PASS`
- no_pose_runtime_unchanged: `PASS`
- dirty_worktree_risk: `HIGH`

鏈疆鏈噸鏂板惎鐢ㄧ湡瀹?Pose锛屼篃鏈慨鏀?`8000` 姝ｅ紡 no-pose runtime銆?
## Commands Executed

```powershell
python tools/new_pose_dataset/validate_raw_dataset.py --root datasets/new_pose_raw
python tools/new_pose_dataset/extract_frames.py --raw-root datasets/new_pose_raw --frames-root datasets/new_pose_frames --camera-id camera_01 --all --strategy balanced --dry-run
python tools/new_pose_dataset/extract_frames.py --raw-root datasets/new_pose_raw --frames-root datasets/new_pose_frames --camera-id camera_01 --all --strategy balanced
python tools/new_pose_dataset/build_contact_sheet.py --manifest datasets/new_pose_frames/camera_01/frame_manifest_all.jsonl
python tools/new_pose_dataset/frame_selection_report.py --manifest datasets/new_pose_frames/camera_01/frame_manifest_all.jsonl --output datasets/new_pose_frames/frame_selection_report_20260621.md
python -m pytest tests/test_pose_service.py tests/test_temporal_service.py tests/test_result_publisher_service.py tests/test_fall_event_reporter_service.py tests/test_fall_alert_polling_api.py tests/test_end_to_end_pipeline.py tests/test_pose_service_provider_selection.py -q
```

## Tool Outputs

- extract tool: [extract_frames.py](/D:/Program/vision_service/tools/new_pose_dataset/extract_frames.py)
- contact sheet tool: [build_contact_sheet.py](/D:/Program/vision_service/tools/new_pose_dataset/build_contact_sheet.py)
- selection report tool: [frame_selection_report.py](/D:/Program/vision_service/tools/new_pose_dataset/frame_selection_report.py)
- global manifest: [frame_manifest_all.jsonl](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/frame_manifest_all.jsonl)
- batch contact sheet: [batch_a_contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/batch_a_contact_sheet.jpg)
- selection report: [frame_selection_report_20260621.md](/D:/Program/vision_service/datasets/new_pose_frames/frame_selection_report_20260621.md)

## Extraction Summary

- raw_batch_a_sessions: `16`
- total_frames_extracted: `655`
- negative_frames: `16`
- annotation_needed_frames: `639`
- hard_case_frames: `369`
- excluded_frames: `0`
- quality_warnings: `none`
- session_manifests: `16/16 present`
- session_contact_sheets: `16/16 present`
- batch_contact_sheet: `present`
- tests: `42 passed`

### Frames By Action

- `no_person`: `16`
- `standing_front`: `30`
- `standing_side`: `30`
- `standing_back`: `30`
- `walking_slow`: `48`
- `sitting_normal`: `30`
- `sitting_side`: `30`
- `bending_pickup`: `48`
- `squat`: `48`
- `lying_side`: `30`
- `lying_back`: `30`
- `lying_prone`: `30`
- `fall_simulated_side`: `89`
- `fall_simulated_back`: `88`
- `fallen_hold`: `30`
- `recovery_standing`: `48`

### Frames By Phase

- `empty_scene`: `16`
- `static_pose`: `270`
- `motion_start`: `33`
- `motion_mid`: `72`
- `motion_end`: `39`
- `pre_fall_standing`: `28`
- `falling_transition`: `59`
- `fallen_hold`: `62`
- `recovery_if_present`: `28`
- `low_posture_start`: `10`
- `recovery_transition`: `23`
- `upright_recovery`: `15`

## Manual Spot Check

鎶芥渚濇嵁:

- [batch_a_contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/batch_a_contact_sheet.jpg)
- [session_20260621_160100_no_person/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_160100_no_person/contact_sheet.jpg)
- [session_20260621_160200_standing_front/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_160200_standing_front/contact_sheet.jpg)
- [session_20260621_160600_sitting_normal/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_160600_sitting_normal/contact_sheet.jpg)
- [session_20260621_160700_sitting_side/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_160700_sitting_side/contact_sheet.jpg)
- [session_20260621_160800_bending_pickup/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_160800_bending_pickup/contact_sheet.jpg)
- [session_20260621_160900_squat/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_160900_squat/contact_sheet.jpg)
- [session_20260621_161000_lying_side/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_161000_lying_side/contact_sheet.jpg)
- [session_20260621_161100_lying_back/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_161100_lying_back/contact_sheet.jpg)
- [session_20260621_161300_fall_simulated_side/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_161300_fall_simulated_side/contact_sheet.jpg)
- [session_20260621_161400_fall_simulated_back/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_161400_fall_simulated_back/contact_sheet.jpg)
- [session_20260621_161500_fallen_hold/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_161500_fallen_hold/contact_sheet.jpg)
- [session_20260621_161600_recovery_standing/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_161600_recovery_standing/contact_sheet.jpg)

缁撹:

- `standing_front` 鎶藉抚涓庢爣绛惧熀鏈竴鑷达紝鍙綔涓虹ǔ瀹?upright 鏍锋湰銆?- `no_person` 鏄庢樉琚薄鏌擄紝绾?`8s` 涔嬪悗鏈変汉杩涘叆鐢婚潰锛屼笉鑳界洿鎺ュ綋璐熸牱鏈富闆嗕娇鐢ㄣ€?- `sitting_normal` 鏈嚭鐜扮ǔ瀹氬潗濮跨獥鍙ｏ紝鍓嶆澶氫负绔欑珛锛屽悗娈靛嚭鐜板€掑湴/浣庡Э鎬侊紝涓嶉€傚悎鐩存帴杩涘叆鏍囨敞涓婚泦銆?- `sitting_side` 涓昏鏄珯绔嬬敾闈紝娌℃湁褰㈡垚鍙俊渚у潗鏍锋湰銆?- `bending_pickup` 鍖呭惈绔欑珛鍜屽€掑湴娈碉紝鍔ㄤ綔鏍囩涓嶇函锛岄渶瑕佷汉宸ヨ繃婊ゆ垨閲嶉噰銆?- `squat` 鎶芥涓湭瑙佺ǔ瀹氭繁韫蹭富娈碉紝鍩烘湰涓嶉€傚悎浣滀负褰撳墠鏍囩鏍锋湰銆?- `lying_side` 涓瀛樺湪鍙敤渚ц汉绐楀彛锛屼絾鍓嶅悗鍖呭惈鏄庢樉璧疯韩/绔欑珛姹℃煋锛岄渶浜屾绛涢€夈€?- `lying_back` 鎶芥涓ぇ閮ㄥ垎涓虹珯绔嬶紝涓嶇鍚堟爣绛鹃鏈熴€?- `fall_simulated_side` 鍚庢瀛樺湪鍙鍊掑湴淇濇寔锛屽彲淇濈暀涓洪毦渚嬪€欓€夛紝浣嗛渶瑕佸彧鎸戦€夋槑纭穼鍊掕繃娓″拰鍊掑湴娈点€?- `fall_simulated_back` 鏈娊鍒板彲淇″悗浠拌穼鍊掍富娈碉紝褰撳墠涓嶅缓璁洿鎺ユ爣娉ㄣ€?- `fallen_hold` 鍓嶄腑娈靛瓨鍦ㄥ€掑湴淇濇寔锛屼絾鍚庢閲嶆柊鍑虹幇璧疯韩/绔欑珛锛岄渶鍙繚鐣?hold 娈点€?- `recovery_standing` 鎶芥涓富瑕佹槸绔欑珛锛岀己灏戞槑纭仮澶嶈繃绋嬶紝涓嶅缓璁洿鎺ユ爣娉ㄤ负 recovery銆?
## Sessions Need Review

寮虹儓寤鸿閲嶉噰:

- `session_20260621_160100_no_person`
- `session_20260621_160600_sitting_normal`
- `session_20260621_160700_sitting_side`
- `session_20260621_160900_squat`
- `session_20260621_161100_lying_back`
- `session_20260621_161400_fall_simulated_back`
- `session_20260621_161600_recovery_standing`

寤鸿浜哄伐浜屾绛涢€夊悗鍐嶅喅瀹氭槸鍚︿繚鐣?

- `session_20260621_160800_bending_pickup`
- `session_20260621_161000_lying_side`
- `session_20260621_161300_fall_simulated_side`
- `session_20260621_161500_fallen_hold`

鐩稿鍙敤:

- `session_20260621_160200_standing_front`
- `session_20260621_160300_standing_side`
- `session_20260621_160400_standing_back`
- `session_20260621_160500_walking_slow`

## Recommendation

鏈疆缁撹涓嶆槸鈥滃伐鍏峰け璐モ€濓紝鑰屾槸鈥滃伐鍏锋垚鍔熸妸 raw session 杞垚浜嗗彲瀹℃煡鐨?frame 鏁版嵁锛屼絾 raw 鍔ㄤ綔鎵ц璐ㄩ噺涓嶈冻浠ョ洿鎺ヨ繘鍏?Phase 5 鍏ㄩ噺鏍囨敞鈥濄€?
寤鸿涓嬩竴姝?

1. 淇濈暀褰撳墠鎶藉抚浜х墿锛屼綔涓?Phase 4 瀹¤鍩虹嚎銆?2. 瀵光€滅浉瀵瑰彲鐢ㄢ€?session 鍏堣繘鍏ュ皬鑼冨洿鏍囨敞璇曡窇銆?3. 瀵光€滃缓璁汉宸ヤ簩娆＄瓫閫夆€?session锛屽彧淇濈暀鏄庣‘鍔ㄤ綔涓绘锛屼笉瑕佹暣娈垫帹杩涙爣娉ㄣ€?4. 瀵光€滃己鐑堝缓璁噸閲団€?session 閲嶆柊閲囬泦锛屽啀鎵ц涓€娆?Phase 4 鎶藉抚銆?5. `A01 no_person` 褰撳墠涓嶈兘鐩存帴浣滀负楂樿川閲忚礋鏍锋湰涓婚泦锛屽彧鑳戒綔涓烘薄鏌撴牱鏈璁″弬鑰冦€?
褰撳墠涓嶅缓璁繘鍏?`ReadyForPhase5AnnotationGuidelineAndQA`锛屾洿鍚堢悊鐨勬槸:

- `recommended_action=NeedRetakeSomeSessions`
