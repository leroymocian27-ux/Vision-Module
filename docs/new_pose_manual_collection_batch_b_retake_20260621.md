# New Pose Manual Collection Batch B Retake

鏃ユ湡: `2026-06-21`

浠撳簱: `D:\Program\vision_service`

commit: `c6da604`

## Runtime Guard

- runtime_profile: `current_camera_live`
- pose_enabled: `false`
- pose_provider: `disabled_placeholder`
- 绂佹閲嶆柊鍚敤鐪熷疄 Pose
- 绂佹淇敼 `8000` no-pose runtime

## Batch B Sessions

| code | session_id | action | suggested_duration_sec | goal |
| --- | --- | --- | ---: | --- |
| B01 | `session_20260621_151001_no_person_retake_b` | `no_person_retake` | 15 | 鐪熸绌哄満, 涓嶅厑璁稿嚭鐜颁汉/鎵?鑴?褰卞瓙 |
| B02 | `session_20260621_151101_sitting_normal_retake_b` | `sitting_normal_retake` | 15 | 娓呮櫚姝ｅ父鍧愬Э, 涓嶆贩鍏ュ€掑湴 |
| B03 | `session_20260621_151201_sitting_side_retake_b` | `sitting_side_retake` | 15 | 渚у悜鍧愬Э, 鑳界湅娓呴珛鑶濊吙 |
| B04 | `session_20260621_151301_squat_retake_b` | `squat_retake` | 20 | 缂撴參涓嬭共鍐嶇珯璧? 涓嶅潗鍦?|
| B05 | `session_20260621_151401_lying_back_retake_b` | `lying_back_retake` | 15 | 娓呮櫚浠拌汉, 涓嶆贩鍏ヨ捣韬?|
| B06 | `session_20260621_151501_fall_simulated_back_retake_b` | `fall_simulated_back_retake` | 30 | 绔欑珛 -> 鍚庡€?-> 浠拌汉淇濇寔 |
| B07 | `session_20260621_151601_recovery_standing_retake_b` | `recovery_standing_retake` | 20 | 浣庡Э鎬?鍊掑湴 -> 缂撴參璧疯韩 -> 绔欑ǔ |

## Recording Protocol

姣忔褰曞埗鍓嶏紝Codex 杈撳嚭:

`鍑嗗寮€濮嬮噰闆?Bxx锛屽姩浣滄槸 xxx锛屾椂闀?xx 绉掋€傝鍑嗗濂藉悗鍥炲锛氬紑濮?Bxx銆俙

鐢ㄦ埛鍥炲鍚庢墠鍚姩褰曞埗銆?
姣忔褰曞埗缁撴潫鍚庯紝Codex 杈撳嚭:

`Bxx 宸插畬鎴愰噰闆嗭紝quality_status=...锛岃鍑嗗涓嬩竴娈点€俙

鑻ヨ川閲忎笉閫氳繃:

- 涓嶈鐩栧凡鏈?session
- 鏍囪 `RETAKE_RECOMMENDED`
- 濡傞渶閲嶅綍锛屽垱寤烘柊鐨?session锛屼笉瑕嗙洊鏃ф枃浠?
## Quality Notes

- `no_person_retake`: 蹇呴』鐪熸鏃犱汉
- `sitting_normal_retake`: 蹇呴』鏄ǔ瀹氬潗濮?- `sitting_side_retake`: 蹇呴』鏄晶鍧愬Э鎬?- `squat_retake`: 蹇呴』鏄笅韫插姩浣? 涓嶈兘婕斿彉鎴愬潗鍦版垨鍊掑湴
- `lying_back_retake`: 蹇呴』鏄话韬洪潤鎬?- `fall_simulated_back_retake`: 蹇呴』鍖呭惈绔欑珛銆佷笅钀姐€佸€掑湴淇濇寔涓変釜闃舵
- `recovery_standing_retake`: 蹇呴』鍖呭惈浣庡Э鎬佸埌绔欑珛鎭㈠鍏ㄨ繃绋?
## Output Expectations

姣忎釜 session 鏈€缁堝簲鍖呭惈:

- `video.mp4`
- `preview.gif`
- `metadata.json`
- `action_script.md`
- `notes.md`
- `qa_report.md`
- `status_samples.jsonl`
- `integration_latest_samples.jsonl`
