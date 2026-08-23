# Event Archive Security Runbook

## Scope and default posture

The event archive is an optional, asynchronous evidence path. It is not part of
the WebRTC, WebSocket, REST realtime-result, detection, tracking, or fusion
path. Archived evidence is private by default:

```dotenv
EVENT_PIPELINE_ENABLED=false
EVENT_ARCHIVE_ENABLED=false
EVENT_KEYFRAME_SERVING_ENABLED=false
```

`GET /events/status`, `/events/latest`, and `/events/{incident_id}` may still
return event metadata when the pipeline is enabled. With
`EVENT_KEYFRAME_SERVING_ENABLED=false`, they return no image URL or image path,
and every keyframe image request returns `404 KEYFRAME_SERVING_DISABLED`.

Do not mount `EVENT_ARCHIVE_DIR` as a static web directory. The event API only
serves a known keyframe selected from the event record after containment checks;
it never returns the local archive root or a Windows/Linux absolute path.

## Trusted internal demonstration access

Enable keyframe image serving only after the archive host and API are restricted
to the trusted internal demonstration network:

```dotenv
EVENT_PIPELINE_ENABLED=true
EVENT_RING_BUFFER_ENABLED=true
EVENT_WORKER_ENABLED=true
EVENT_SEMANTIC_ENABLED=true
EVENT_ARCHIVE_ENABLED=true
EVENT_KEYFRAME_SERVING_ENABLED=true

EVENT_DELIVERY_ENABLED=false
EVENT_VLM_ENABLED=false
MAIN_SYSTEM_ALERT_ENABLED=false
```

Restart the service after changing environment configuration. Roll back image
access immediately by setting `EVENT_KEYFRAME_SERVING_ENABLED=false` and
restarting. Existing archived files remain on disk but are no longer readable
through the API.

The accepted event ID format is `[A-Za-z0-9_-]` with a maximum of 160
characters. Invalid IDs, traversal attempts, missing events, missing keyframes,
and disabled image serving are rejected with `404`; no filesystem path is
included in the response.

## Archive capacity and retention

Configure the archive root and its per-camera bounds explicitly:

```dotenv
EVENT_ARCHIVE_DIR=logs/event_archive
EVENT_ARCHIVE_MAX_EVENTS_PER_CAMERA=200
EVENT_ARCHIVE_RETENTION_DAYS=30
```

After each successful archive write, cleanup examines only direct, non-symlink
incident directories below `<EVENT_ARCHIVE_DIR>/<safe-camera-id>/`. It removes
expired incident directories first, then oldest incident directories beyond the
per-camera limit. Files at the archive root and directly in a camera directory
are not cleanup candidates. Resolved deletion targets must remain below the
configured archive root and camera directory.

Operational logs use these event names:

- `event_archive_cleanup_deleted`
- `event_archive_cleanup_failed`
- `event_archive_cleanup_skipped_unsafe`
- `event_archive_cleanup_list_failed`
- `event_archive_cleanup_stat_failed`

Cleanup is best effort. Listing, stat, permission, and deletion failures are
logged and never fail event processing or the realtime main chain.

## Verification

Run the focused security and archive regression suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_event_keyframe_api.py tests\test_event_archive.py tests\test_event_api.py tests\test_event_pipeline_e2e_smoke.py -q
```

The suite verifies invalid IDs and encoded traversal rejection, relative-only
keyframe resolution, keyframe-serving-off behavior, absolute-path redaction,
per-camera retention, cleanup scoping, and cleanup failure isolation.

Then run the broader event plus realtime-publisher regression:

```powershell
$eventTests = Get-ChildItem tests -Filter 'test_event_*.py' | ForEach-Object { $_.FullName }
.\.venv\Scripts\python.exe -m pytest $eventTests tests\test_fused_result_fallback.py tests\test_result_publisher_service.py tests\test_end_to_end_pipeline.py tests\test_fall_alert_polling_api.py -q
```

For production investigation, review API responses and logs only. Do not expose
or paste filesystem paths from archive hosts into client-side configuration.
