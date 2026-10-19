# Post-Fall V2 Real Fall Test Record - 2026-09-06 15:02

## Summary

- Test type: real fall rehearsal after `competition_v1` prompt update.
- Camera: `go2_front_camera`
- Qwen model: `qwen3.5:4b`
- Prompt/schema: `competition_v1` / `compact_v1`
- Keyframes sent to Qwen: `T-800ms / T0 / T+400ms`
- Evidence export:
  - Binary: `C:\Users\YANG\Desktop\ce\xiao`
  - Qwen: `C:\Users\YANG\Desktop\ce\da`
- Formal presentation session: `E:\HealthProtection\event\test_sessions\test_20260906_070337`

This run produced four binary fall candidates. Qwen confirmed the first one as a fall, marked the second uncertain, and marked the later two as non-fall.

## Event Results

| Time CST | Incident | Binary max | Binary evidence | Qwen e | Qwen f | Qwen c | Qwen latency |
| --- | --- | ---: | --- | --- | --- | ---: | ---: |
| 15:02:00.853 | `pfv2-go2_front_camera-5db95c18f36c` | 0.983782 | 4/8 positive, 4 consecutive | `fall` | true | 0.95 | 1748 ms |
| 15:02:53.157 | `pfv2-go2_front_camera-d74cb078d625` | 0.916652 | 3/8 positive, 3 consecutive | `uncertain` | false | 0.65 | 1704 ms |
| 15:03:17.705 | `pfv2-go2_front_camera-c113dd16e3d7` | 0.924217 | 4/8 positive, 3 consecutive | `non_fall` | false | 0.95 | 1978 ms |
| 15:03:42.742 | `pfv2-go2_front_camera-733770eeecca` | 0.971770 | 3/8 positive, 3 consecutive | `non_fall` | false | 0.95 | 2040 ms |

Average Qwen latency over the four reviews: about 1.87 seconds.

## Key Observations

### `pfv2-go2_front_camera-5db95c18f36c`

Qwen output:

```json
{"e":"fall","s":"ground","d":"yes","f":true,"c":0.95,"t":"人物躺在蓝色垫子上，双腿弯曲抬起。"}
```

Visual review: this sample contains useful temporal evidence. The first frame shows the person near standing at the edge of the frame, T0 shows a clear sudden supine ground state with a raised leg, and T+400ms shows continued supine low posture. Qwen confirmed this correctly.

Qwen evidence directory:

`C:\Users\YANG\Desktop\ce\da\pfv2-go2_front_camera-5db95c18f36c`

### `pfv2-go2_front_camera-d74cb078d625`

Qwen output:

```json
{"e":"uncertain","s":"ground","d":"no","f":false,"c":0.65,"t":"人物平躺在蓝色垫子上，身体姿态稳定。"}
```

Visual review from model text: Qwen saw stable lying on the mat but did not see enough transition evidence, so it chose `uncertain`. This is acceptable under the stricter boundary if the three frames are already after the main fall motion.

Qwen evidence directory:

`C:\Users\YANG\Desktop\ce\da\pfv2-go2_front_camera-d74cb078d625`

### `pfv2-go2_front_camera-c113dd16e3d7`

Qwen output:

```json
{"e":"non_fall","s":"ground","d":"no","f":false,"c":0.95,"t":"人物坐在蓝色垫子上，身体后仰靠在背部。"}
```

Visual review from model text: this is likely a false deny for a real-fall rehearsal. The keyframes appear to arrive after the most fall-like transition, leaving Qwen with a seated/leaning low posture and no visible distress. The prompt still lets "stable low posture" plus apparent control pull it into `non_fall`.

Qwen evidence directory:

`C:\Users\YANG\Desktop\ce\da\pfv2-go2_front_camera-c113dd16e3d7`

### `pfv2-go2_front_camera-733770eeecca`

Qwen output:

```json
{"e":"non_fall","s":"ground","d":"no","f":false,"c":0.95,"t":"人物蹲在蓝色垫子上，手持白色物体（疑似手机或平板），正在低头查看。"}
```

Visual review: this is the clearest false-deny example. The T-800 frame shows a close lower-body standing/bending view with a white object in hand; T0 and T+400 show crouched or seated low posture, still holding the white object. Qwen latched onto the object and low-head posture as active behavior evidence.

Qwen evidence directory:

`C:\Users\YANG\Desktop\ce\da\pfv2-go2_front_camera-733770eeecca`

## Conclusion

The new evidence export worked: every Qwen outcome now has the exact three images, compact JSON, and latency. The first sample proves the new prompt can confirm a fall when the transition signal is visible. The later false denies show that the current keyframe timing can still be too late or too close-cropped, causing Qwen to see "already low posture with an object" instead of the fall.

Recommended next adjustment: keep three images, but shift the pre-event sampling earlier or include the strongest binary-rise frame before candidate confirmation, so Qwen receives a frame closer to the actual posture change rather than only post-transition low posture.
