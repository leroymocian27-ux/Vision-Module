# New Pose Batch A Quality Triage

鏃ユ湡: `2026-06-21`

浠撳簱: `D:\Program\vision_service`

commit: `c6da604`

## Baseline

- runtime_profile: `current_camera_live`
- pose_enabled: `false`
- pose_provider: `disabled_placeholder`
- no_pose_baseline_check: `PASS`
- no_pose_runtime_unchanged: `PASS`

## Triage Rules

- 涓嶅垹闄や换浣?Batch A 鍘熷鏂囦欢銆?- 涓嶈鐩栦换浣?Batch A `video.mp4`銆?- curated manifest 榛樿鍙洿鎺ョ撼鍏?A 绫汇€?- B 绫讳笌 D 绫婚粯璁や笉杩涘叆涓绘爣娉ㄩ泦锛岄櫎闈炲悗缁汉宸ヤ簩娆＄‘璁ゃ€?- C 绫婚粯璁?`excluded_from_annotation=true`銆?
## A 绫? 鍙繘鍏ヤ富鏍囨敞鍊欓€?
- `session_20260621_160200_standing_front`
- `session_20260621_160300_standing_side`
- `session_20260621_160400_standing_back`
- `session_20260621_160500_walking_slow`

鐢ㄩ€?

- 涓绘爣娉ㄥ€欓€?- 璁粌鍊欓€?- upright / walking 鍩虹嚎鏍锋湰

## B 绫? 浠呬綔浜哄伐浜屾绛涢€夋垨 hard case 鍙傝€?
- `session_20260621_161000_lying_side`
- `session_20260621_161300_fall_simulated_side`
- `session_20260621_161500_fallen_hold`

鐢ㄩ€?

- hard case review
- 浠呭湪浜哄伐纭鏈夋晥甯у悗鎵嶅厑璁歌繘鍏ュ悗缁?curated pool

## C 绫? 涓嶈繘鍏ヤ富鏍囨敞鍊欓€? 闇€瑕侀噸閲?
- `session_20260621_160100_no_person`
- `session_20260621_160600_sitting_normal`
- `session_20260621_160700_sitting_side`
- `session_20260621_160900_squat`
- `session_20260621_161100_lying_back`
- `session_20260621_161400_fall_simulated_back`
- `session_20260621_161600_recovery_standing`

鐢ㄩ€?

- 瀹¤鍙傝€?- 涓嶇撼鍏?curated 涓绘爣娉ㄥ€欓€?- 鐢?Batch B retake 琛ラ綈

## D 绫? 闇€浜哄伐澶嶆煡鍚庡啀鍐冲畾

- `session_20260621_160800_bending_pickup`
- `session_20260621_161200_lying_prone`

鐢ㄩ€?

- 寰呬汉宸ュ鏍?- 榛樿涓嶈繘鍏ヤ富鏍囨敞鍊欓€?
## Default Curated Policy

- A 绫? `curated_include=true`
- B 绫? `curated_include=false`, `curated_role=hard_case_review`
- C 绫? `curated_include=false`, `curated_role=excluded`
- D 绫? `curated_include=false`, `needs_human_review=true`

## Next Step

- 鍒涘缓骞堕噰闆?Batch B retake session锛屼紭鍏堣ˉ榻?C 绫荤己澶卞姩浣溿€?- 瀹屾垚 Batch B 鍚庯紝鍐嶇敤 curated manifest 缁熶竴鍐冲畾鍝簺甯ц兘杩涘叆 Phase 5 鍓?QA銆?
