# No-Pose Placeholder Runtime Report

鏃ユ湡: `2026-06-21`

浠撳簱: `D:\Program\vision_service`

鍩虹嚎鎻愪氦: `c6da604`

## 1. 鑳屾櫙

褰撳墠 live 鍦烘櫙涓紝Pose 楠ㄦ灦閾捐矾闀挎湡瀛樺湪浠ヤ笅闂:

- 楠ㄦ灦鍏抽敭鐐规紓绉绘槑鏄撅紝灏ゅ叾鏄吙閮ㄧ偣涓嶇ǔ瀹?- 鍘嗗彶涓婂皾璇曡繃 provider 鍒囨崲銆佷綆缃俊杩囨护銆佽竟鐣岀偣杩囨护銆佸墠绔繃婊ゃ€丷OI 璋冩暣绛夋柟妗?- 鐜板満鏁堟灉浠嶄笉绋冲畾锛岄毦浠ヤ綔涓烘寮忚穼鍊掗棴鐜殑鍙潬渚濊禆

鍥犳锛屾湰杞笉鍐嶇户缁紭鍖?Pose / skeleton 鏈韩锛岃€屾槸鎵ц缁撴瀯鎬ц皟鏁?

- 灏?Pose 浠庢寮忚繍琛岄摼璺腑鎾や笅
- 淇濈暀鎺ュ彛鍗犱綅绗︼紝閬垮厤鍓嶇銆佺姸鎬佹帴鍙ｃ€乮ntegration payload銆亀ebsocket 鍥犲瓧娈电己澶辨姤閿?- 璁╃郴缁熶互 `no-pose` 妯″紡缁х画杩愯璺屽€掓娴嬩富閾捐矾

## 2. 鏈疆鐩爣

鐩爣瀹氫箟涓?

1. 姝ｅ紡 runtime 涓嶅啀鎵ц Pose 鎺ㄧ悊
2. 姝ｅ紡 runtime 涓嶅啀杈撳嚭鐪熷疄 keypoints
3. 鍓嶇涓嶅啀缁樺埗鐪熷疄楠ㄦ灦
4. Temporal 涓嶅啀渚濊禆 Pose 鍑犱綍鐗瑰緛浣滀负姝ｅ紡蹇呰鏉′欢
5. Result / Integration / Status / WebSocket 淇濇寔瀛楁鍏煎
6. 璺屽€掓娴嬬户缁繚鐣?
   - person detection
   - tracking
   - fall detector
   - bbox-only temporal features
   - field rule / detector hint
   - reporter / snapshot / integration / polling

## 3. 渚濊禆瀹¤缁撹

### 3.1 鍚庣 Pose 鎺ㄧ悊鍏ュ彛

鏍稿績鍏ュ彛鍘熶綅浜?

- [app/services/pose_service.py](D:/Program/vision_service/app/services/pose_service.py)
- [app/services/pose_worker_service.py](D:/Program/vision_service/app/services/pose_worker_service.py)
- [app/services/stream_service.py](D:/Program/vision_service/app/services/stream_service.py)

鍏朵腑:

- `PoseService` 鍘熷厛浼氬姞杞界湡瀹?pose estimator
- `PoseWorkerService` 鍘熷厛浼氫粠 tracking/detection 蹇収涓彇甯у苟鎵ц `pose_service.enrich()`
- `StreamService.start()` 鍘熷厛浼氬惎鍔?pose worker

### 3.2 Temporal 瀵?Pose 鐨勪緷璧?
鍘熶緷璧栫偣:

- [app/temporal/target_feature_extractor.py](D:/Program/vision_service/app/temporal/target_feature_extractor.py)
- [app/temporal/fall_state_machine.py](D:/Program/vision_service/app/temporal/fall_state_machine.py)

鍏朵腑鍘熷厛浼氳鍙?

- `pose_available`
- `torso_angle`
- `head_height_ratio`
- `hip_height_ratio`

### 3.3 Result / Status / Integration 瀵?Pose 鐨勪緷璧?
涓昏渚濊禆鐐?

- [app/services/result_publisher_service.py](D:/Program/vision_service/app/services/result_publisher_service.py)
- [app/services/status_service.py](D:/Program/vision_service/app/services/status_service.py)
- [app/api/integration_api.py](D:/Program/vision_service/app/api/integration_api.py)
- [app/schemas/status.py](D:/Program/vision_service/app/schemas/status.py)
- [app/pose/schemas.py](D:/Program/vision_service/app/pose/schemas.py)

鍘熷厛浼氳鍐?

- `pose_available`
- `pose_debug`
- `pose_provider`
- `keypoints`
- `skeleton_confidence`
- `pose_bbox`

### 3.4 鍓嶇楠ㄦ灦缁樺埗浣嶇疆

涓昏浣嶄簬:

- [frontend_demo/overlay.js](D:/Program/vision_service/frontend_demo/overlay.js)
- [frontend_demo/app.js](D:/Program/vision_service/frontend_demo/app.js)

鍖呮嫭:

- skeleton lines 缁樺埗
- keypoint dots 缁樺埗
- pose cache
- stale pose 鏍￠獙
- pose bbox / track / frame 瀵归綈鏍￠獙

## 4. 瀹炴柦鏂规

### 4.1 鏂板缁熶竴鍗犱綅绗﹀眰

鏂板鏂囦欢:

- [app/pose/placeholders.py](D:/Program/vision_service/app/pose/placeholders.py)

缁熶竴瀹氫箟:

- `POSE_DISABLED_PROVIDER = "disabled_placeholder"`
- `POSE_DISABLED_REASON = "pose_pipeline_removed_pending_reconfiguration"`
- placeholder payload builder
- placeholder 璇嗗埆閫昏緫
- 鈥滄槸鍚︽湁鐪熷疄鍙 keypoints鈥?鐨勭粺涓€鍒ゆ柇閫昏緫

### 4.2 PoseService 鏀逛负姝ｅ紡鏀寔 disabled placeholder

淇敼:

- [app/services/pose_service.py](D:/Program/vision_service/app/services/pose_service.py)

缁撴灉:

- 褰?`ENABLE_POSE=false` 鎴?`POSE_PROVIDER=disabled_placeholder` 鏃?  - 涓嶅姞杞戒换浣?pose estimator
  - 涓嶆墽琛屾帹鐞?  - 涓嶉樆濉?runtime
  - 瀵?person object 鑷姩琛ュ厖 pose placeholder

placeholder 鍙ｅ緞:

```json
{
  "pose_provider": "disabled_placeholder",
  "keypoints": [],
  "pose_bbox": null,
  "skeleton_confidence": null,
  "debug": {
    "pose_disabled": true,
    "pose_pipeline_removed": true,
    "placeholder": true,
    "reason": "pose_pipeline_removed_pending_reconfiguration"
  }
}
```

### 4.3 Pose worker 涓嶅啀鍙備笌姝ｅ紡 runtime

淇敼:

- [app/services/pose_worker_service.py](D:/Program/vision_service/app/services/pose_worker_service.py)

缁撴灉:

- disabled placeholder 妯″紡涓嬩笉鍐嶅惎鍔ㄧ湡瀹?pose worker 寰幆
- 閬垮厤鏃犳剰涔夌嚎绋嬪拰鎺ㄧ悊璋冪敤

### 4.4 Temporal 鏀逛负 bbox-only pose placeholder 妯″紡

淇敼:

- [app/services/temporal_service.py](D:/Program/vision_service/app/services/temporal_service.py)
- [app/temporal/target_feature_extractor.py](D:/Program/vision_service/app/temporal/target_feature_extractor.py)

缁撴灉:

- extractor 鏀寔 `pose_enabled=False`
- 鍦?no-pose 妯″紡涓嬭緭鍑?
  - `pose_available=false`
  - `pose_confidence=0.0`
  - `torso_angle=null`
  - `head_height_ratio=null`
  - `hip_height_ratio=null`
- temporal window 浠嶆甯告洿鏂?- 璺屽€掍富閾捐矾缁х画渚濋潬 bbox / detector / temporal 搴忓垪璇佹嵁

### 4.5 Result Publisher 鏀逛负 Pose optional

淇敼:

- [app/services/result_publisher_service.py](D:/Program/vision_service/app/services/result_publisher_service.py)

缁撴灉:

- 鍦?no-pose 妯″紡涓嬭嚜鍔ㄤ负 person object 娉ㄥ叆 placeholder pose payload
- `_has_person_evidence()` 涓嶅啀鎶?pose keypoints 褰撲綔蹇呰璇佹嵁
- `pose_available` 鍒ゆ柇鏀逛负缁熶竴 helper
- 鐜版湁 detector-only / field-rule / incident 鐩稿叧淇濇姢淇濇寔鏈夋晥

### 4.6 Status 鏀逛负 disabled placeholder 鍙ｅ緞

淇敼:

- [app/services/status_service.py](D:/Program/vision_service/app/services/status_service.py)
- [app/schemas/status.py](D:/Program/vision_service/app/schemas/status.py)
- [app/pose/schemas.py](D:/Program/vision_service/app/pose/schemas.py)

缁撴灉:

- `/status.pose.pose_enabled=false`
- `/status.pose.pose_provider=disabled_placeholder`
- `/status.pose.pose_pipeline_removed=true`
- `latest_result.pose_available=false`

### 4.7 鍓嶇鎾や笅鐪熷疄楠ㄦ灦缁樺埗

淇敼:

- [frontend_demo/overlay.js](D:/Program/vision_service/frontend_demo/overlay.js)
- [frontend_demo/app.js](D:/Program/vision_service/frontend_demo/app.js)

缁撴灉:

- 閬囧埌 disabled placeholder 鏃?
  - 涓嶇敾 skeleton line
  - 涓嶇敾 keypoint dot
  - 娓呯悊 pose smoothing / pose cache
  - 涓嶅啀杩涘叆鐪熷疄楠ㄦ灦瀵归綈鍜岀粯鍒舵祦绋?- 淇濈暀鍘?overlay 鍖哄煙
- 鐢ㄧǔ瀹氱殑 placeholder 鐘舵€佷唬鏇?
鍓嶇琛ㄧ幇:

- `poseState` 灞曠ず涓?`pose placeholder`
- overlay 鍖哄煙鏄剧ず `Pose Placeholder`

### 4.8 鍚姩鑴氭湰榛樿鍒囦负 no-pose

淇敼:

- [scripts/start_current_camera.py](D:/Program/vision_service/scripts/start_current_camera.py)

缁撴灉:

- 榛樿 `--disable-pose`
- 榛樿 `POSE_PROVIDER=disabled_placeholder`
- 榛樿 `ENABLE_BEHAVIOR=false`
- 濡傞渶閲嶆柊鎺ュ洖鏃?Pose锛屽彧鑳芥樉寮?`--enable-pose --pose-provider ...`

## 5. 娴嬭瘯缁撴灉

鎵ц鍛戒护:

```powershell
python -m pytest tests/test_pose_service.py tests/test_temporal_service.py tests/test_result_publisher_service.py tests/test_fall_event_reporter_service.py tests/test_fall_alert_polling_api.py tests/test_end_to_end_pipeline.py tests/test_pose_service_provider_selection.py -q
```

缁撴灉:

- `42 passed`

鏂板/瑕嗙洊閲嶇偣:

- pose disabled mode 涓嶅姞杞芥ā鍨?- pose disabled mode 杩斿洖 placeholder 瀛楁
- temporal 鍦?no-pose 涓嬭緭鍑?bbox-only features
- result publisher 鍦?no-pose 涓嬩繚鎸佹帴鍙ｅ吋瀹?- integration / status / end-to-end 淇濇寔 placeholder payload
- detector-only / incident dedup / reporter guard 鐩稿叧鍥炲綊涓嶈鐮村潖

## 6. Smoke 楠岃瘉缁撴灉

### 6.1 涓存椂 8011 no-pose smoke

浣跨敤涓存椂瀹炰緥楠岃瘉:

- `/healthz` OK
- `/status` OK
- `/integration/results/camera_01/latest` OK
- `/integration/fall-alerts/camera_01/poll` OK
- `/stream/latest-frame.jpg` OK

骞剁‘璁?

- `pose_enabled=false`
- `pose_provider=disabled_placeholder`
- `pose_pipeline_removed=true`

### 6.2 褰撳墠 8000 live 瀹炰緥

宸插皢褰撳墠 `8000` 瀹炰緥閲嶅惎鍒?no-pose 妯″紡锛屽苟鎭㈠鍘?RTSP 涓绘満:

- `192.168.8.252`

褰撳墠瀹炴祴:

- `/healthz` OK
- `/status` OK
- `/stream/latest-frame.jpg` 杩斿洖 `200`
- `pose_enabled=false`
- `pose_provider=disabled_placeholder`
- `main_stream.source_url_masked=rtsp://admin:***@192.168.8.252:10554/tcp/av0_1`

## 7. 褰撳墠 live 鐘舵€佹憳瑕?
鍩轰簬鏈疆鏈€鏂?`/status`:

- runtime_profile: `current_camera_live`
- stream_state: `connected`
- capture_fps: `6.03`
- latest_raw_person_count: `1`
- tracked_objects_count: `1`
- pose_enabled: `false`
- pose_provider: `disabled_placeholder`
- temporal_enabled: `true`

鍚屾椂鍙互鐪嬪埌:

- `latest_result.pose_available=false`
- `latest_result.pose_debug.pose_disabled=true`
- `latest_result.pose_debug.placeholder=true`

杩欒鏄庡綋鍓?live 閾捐矾宸茬粡鍒囨崲鍒?no-pose formal runtime銆?
## 8. 褰撳墠宸茬煡鐜拌薄

褰撳墠 no-pose 妯″紡涓嬶紝濮挎€侀鏋舵紓绉婚棶棰樺凡缁忎笉鍐嶆槸绯荤粺杈撳嚭鐨勪竴閮ㄥ垎锛屽洜涓?

- 鍚庣涓嶅啀鎻愪緵鐪熷疄 keypoints
- 鍓嶇涓嶅啀缁樺埗鐪熷疄 skeleton

浣嗚穼鍊掓娴嬩富閾捐矾浠嶇劧缁х画宸ヤ綔锛屽洜姝ょ幇鍦轰粛鍙兘鍑虹幇浠ヤ笅鐙珛闂锛岄渶瑕佷笌 Pose 鑴遍挬鐪嬪緟:

- detector-only 鍊欓€?- temporal bbox-only 璺屽€掑€欓€?- field rule 鎷掔粷鎴栨檵鍗?- standing / sitting / low-posture 鍦烘櫙鐨勮鍒ゆ垨婕忓垽

杩欎簺闂鐜板湪閮藉簲瑙嗕负鈥滄棤楠ㄦ灦妯″紡涓嬬殑璺屽€掗摼璺棶棰樷€濓紝鑰屼笉鏄?Pose 闂銆?
## 9. 椋庨櫓涓庨檺鍒?
### 9.1 宸茶閬跨殑椋庨櫓

- 涓嶅啀鍥犱负楠ㄦ灦婕傜Щ褰卞搷鍓嶇鏄剧ず
- 涓嶅啀鍥犱负浣庣疆淇?keypoints 姹℃煋 bounds
- 涓嶅啀鍥犱负 pose provider 鍒囨崲瀵艰嚧鐜板満涓嶇ǔ瀹?
### 9.2 褰撳墠淇濈暀鐨勯檺鍒?
- `app/temporal/fall_state_machine.py` 閲屼粛淇濈暀 pose 鐩稿叧瀛楁缁撴瀯锛屼絾鍦ㄥ綋鍓?no-pose 妯″紡涓嬭繖浜涘€兼亽涓虹┖鎴?false
- 鍘嗗彶 pose estimator 鏂囦欢鍜岀浉鍏?provider 浠ｇ爜鏈垹闄わ紝鍙槸閫€鍑烘寮?runtime
- 濡傛灉鍚庣画閲嶆柊鎺?Pose锛岄渶瑕佸湪鐜版湁 placeholder 鎺ュ彛浣嶇疆鎭㈠锛岃€屼笉鏄洿鎺ュ洖婊氬埌鏃?live 鏂规

## 10. 鏈畬鎴愰」

鏈疆娌℃湁瀹屾垚 git 鎻愪氦锛屽師鍥犳槸褰撳墠宸ヤ綔鍖哄寘鍚ぇ閲忓巻鍙叉湭鎻愪氦鏀瑰姩锛屼笖閮ㄥ垎鏂囦欢涓庢湰杞洰鏍囨枃浠堕噸鍙?

- 鐩存帴鎻愪氦浼氭妸闈炴湰杞彉鏇翠竴璧峰甫鍏?- 闇€瑕佷笅涓€姝ュ崟鐙仛涓€娆♀€渘o-pose 鏀瑰姩鍒嗙涓庢彁浜も€?
寤鸿鎻愪氦淇℃伅:

```text
refactor: disable pose pipeline and use skeleton placeholders
```

## 11. 鎺ㄨ崘涓嬩竴姝?
寤鸿椤哄簭:

1. 鍦ㄥ綋鍓?no-pose live 瀹炰緥涓婂仛涓€杞柊鐨勭湡瀹炲姩浣滃楠?2. 楠岃瘉鏃犻鏋舵ā寮忎笅鐨?
   - no-person safety
   - standing safety
   - sitting safety
   - real fall confirm
3. 灏嗛棶棰樺垎绫讳负:
   - Detection
   - Tracking
   - FieldRule
   - FallStateMachine
   - ResultLayer
4. 鍗曠嫭鏁寸悊骞舵彁浜ゆ湰杞?no-pose 鏀瑰姩
5. 鍚庣画濡傝閲嶆柊鎺ュ洖濮挎€佹ā鍧楋紝搴斾互 placeholder 鎺ュ彛涓轰繚鐣欎綅閲嶆柊璁捐锛屼笉鍐嶅鐢ㄦ棫婕傜Щ楠ㄦ灦閾捐矾

## 12. 缁撹

鏈疆鐩爣宸茬粡杈炬垚:

- Pose 宸蹭粠姝ｅ紡 runtime 鎾や笅
- 鍚庣宸茬粺涓€杈撳嚭 placeholder pose payload
- 鍓嶇宸插仠姝㈢湡瀹為鏋剁粯鍒?- Temporal 宸插彲鍦?bbox-only 妯″紡缁х画宸ヤ綔
- Integration / Status / WebSocket 鎺ュ彛鍏煎淇濇寔浣?- 褰撳墠 live `8000` 宸茶繍琛屽湪 `disabled_placeholder` 妯″紡

褰撳墠绯荤粺鐘舵€佸彲浠ユ弿杩颁负:

> 楠ㄦ灦閾捐矾宸叉寮忎笅绾匡紝鍗犱綅鎺ュ彛宸蹭繚鐣欙紝绯荤粺杩涘叆鏃犻鏋惰穼鍊掓娴嬭繍琛岄樁娈点€?
