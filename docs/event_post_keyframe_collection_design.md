# Post-Event Keyframe Collection

P9 uses a default-disabled two-stage strategy. The event worker immediately
archives currently available evidence. When enabled, a daemon timer waits
`EVENT_POST_KEYFRAME_WINDOW_SECONDS` and then reselects evidence from the ring
buffer, updates the same archive and event record, and never sleeps in the
event worker or realtime publisher.

`archive_summary.evidence_status` is `collecting` before the timer finalizes,
`complete` when all requested frames are available, and `degraded` when one or
more are still missing. Missing frames retain `no_frame_near_target`; no frame
is fabricated. The feature defaults to off through
`EVENT_POST_KEYFRAME_COLLECTION_ENABLED=false`.
