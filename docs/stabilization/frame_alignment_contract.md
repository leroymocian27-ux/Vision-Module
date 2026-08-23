# Frame Alignment Contract

Date: 2026-07-20
Scope: S4 AI pipeline evidence alignment

## Frame Identity

Every AI output fused into a realtime result must be tied to a source frame:

```text
camera_id
frame_seq
frame_width
frame_height
timestamp
monotonic_at
objects
```

`DetectionSnapshot` additionally carries the image frame and detector metadata. `ObjectSnapshot` carries enriched objects for tracking, pose, behavior, and temporal stages.

## Freshness States

`RealtimeResultStore.latest_with_freshness()` returns:

```text
fresh
missing
stale
frame_misaligned
disabled
```

The returned payload also includes:

```text
age_ms
frame_seq
frame_delta
stale_reason
```

## Fusion Rules

- Base result frame is `latest_tracking` when present, otherwise `latest_detection`.
- If the base frame is older than `STREAM_STALE_THRESHOLD_MS`, no realtime result snapshot is built.
- Pose evidence is merged only when fresh and within `POSE_PUBLISH_MAX_FRAME_DELTA`.
- Temporal worker evidence is merged only when fresh and within `TEMPORAL_MAX_FRAME_DELTA`.
- Detection and tracking are core evidence. If either is missing, stale, or frame-misaligned, confirmed fall output must be blocked or downgraded.
- Fall-hint evidence is optional/degrading evidence. If stale or frame-misaligned, it is skipped and marked as `fall_detector_skipped.reason=stale_or_frame_misaligned`.
- Debug output includes `evidence_freshness`, `evidence_age_ms`, `evidence_frame_seq`, `evidence_frame_delta`, `missing_conditions`, and `confirm_blocked_by` when evidence debug is enabled.

## Wrong-Frame Rule

Obvious wrong-frame evidence must not be fused silently. It must be one of:

```text
skipped
marked frame_misaligned
included only with confirm_blocked_by
```

S4 tests verify that a detection from frame 20 cannot silently confirm a tracking-base result for frame 10 when the configured max delta is 1.

## Acceptance

```text
S4_FRAME_ALIGNMENT_CONTRACT: PASS
```
