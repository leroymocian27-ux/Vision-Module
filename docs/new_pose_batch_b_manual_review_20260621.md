# New Pose Batch B Manual Review

鏃ユ湡: `2026-06-21`

浠撳簱: `D:\Program\vision_service`

commit: `c6da604`

## Review Basis

鍩轰簬浠ヤ笅 contact sheet 鍋氫汉宸ュ鏍?

- [session_20260621_151001_no_person_retake_b/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_151001_no_person_retake_b/contact_sheet.jpg)
- [session_20260621_151101_sitting_normal_retake_b/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_151101_sitting_normal_retake_b/contact_sheet.jpg)
- [session_20260621_151201_sitting_side_retake_b/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_151201_sitting_side_retake_b/contact_sheet.jpg)
- [session_20260621_151301_squat_retake_b/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_151301_squat_retake_b/contact_sheet.jpg)
- [session_20260621_151401_lying_back_retake_b/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_151401_lying_back_retake_b/contact_sheet.jpg)
- [session_20260621_151501_fall_simulated_back_retake_b/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_151501_fall_simulated_back_retake_b/contact_sheet.jpg)
- [session_20260621_151601_recovery_standing_retake_b/contact_sheet.jpg](/D:/Program/vision_service/datasets/new_pose_frames/camera_01/session_20260621_151601_recovery_standing_retake_b/contact_sheet.jpg)

## Manual Result

### RETAKE_PASS

- `session_20260621_151601_recovery_standing_retake_b`

璇存槑:

- 瀛樺湪娓呮櫚鐨勪綆濮挎€?鍊掑湴 -> 璧疯韩 -> 绔欑珛鎭㈠杩囩▼銆?
### RETAKE_REVIEW

- `session_20260621_151401_lying_back_retake_b`

璇存槑:

- 涓悗娈靛瓨鍦ㄥ彲鐢ㄤ话韬虹獥鍙ｃ€?- 浣嗗墠娈垫贩鍏ヤ笅韬鸿繃娓″拰濮挎€佽皟鏁达紝褰撳墠涓嶇洿鎺ヨ繘鍏?curated 涓绘爣娉ㄥ€欓€夈€?
### RETAKE_FAIL

- `session_20260621_151001_no_person_retake_b`
  - 鍘熷洜: 鐢婚潰鎸佺画鏈変汉浣撳嚭鐜帮紝涓嶆槸鐪熸绌哄満銆?- `session_20260621_151101_sitting_normal_retake_b`
  - 鍘熷洜: 瀹為檯涓昏涓虹珯绔嬶紝涓嶆槸绋冲畾鍧愬Э銆?- `session_20260621_151201_sitting_side_retake_b`
  - 鍘熷洜: 瀹為檯鍖呭惈韬哄湴銆佽捣韬拰绔欑珛锛屽拰渚у潗鏍囩涓嶇銆?- `session_20260621_151301_squat_retake_b`
  - 鍘熷洜: 鏈舰鎴愭槑纭笅韫蹭富娈碉紝鍑犱箮鍏ㄧ▼绔欑珛銆?- `session_20260621_151501_fall_simulated_back_retake_b`
  - 鍘熷洜: 鏈舰鎴愭槑纭悗鍊掑拰浠拌汉淇濇寔涓绘锛屽熀鏈负绔欑珛鐢婚潰銆?
## Impact

- Batch B 褰撳墠鍙ˉ榻愪簡 `recovery_standing_retake`銆?- `lying_back_retake` 浠呴€傚悎浣滀负 review pool銆?- `no_person_retake / sitting_normal_retake / sitting_side_retake / squat_retake / fall_simulated_back_retake` 浠嶉渶閲嶆柊閲囬泦銆?
