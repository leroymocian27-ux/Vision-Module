# Event Demo Seed Usage

`scripts/seed_event_pipeline_demo.py` is dev/demo only. It creates a synthetic event for validating `/demo/`, event APIs, archive JSON, and keyframe timeline UI when no real fall event is available.

It does not run automatically, does not call main-system POST endpoints, and does not represent a real detection result.

## Example

Run the service with a SQLite outbox path:

```powershell
$env:EVENT_PIPELINE_ENABLED="true"
$env:EVENT_OUTBOX_BACKEND="sqlite"
$env:EVENT_OUTBOX_SQLITE_PATH="data/event_outbox.sqlite3"
$env:EVENT_ARCHIVE_ENABLED="true"
$env:EVENT_ARCHIVE_DIR="logs/event_archive"
```

Seed one demo event:

```powershell
python scripts/seed_event_pipeline_demo.py `
  --db data/event_outbox.sqlite3 `
  --archive-dir logs/event_archive `
  --camera-id camera_01 `
  --scenario fall_candidate_support
```

Then open:

```text
/events/latest?camera_id=camera_01
/demo/
```

## Options

- `--event-type fall_candidate|fallen_confirmed`
- `--scenario fall_candidate_support|fallen_confirmed_high|adl_suppressed_review|missing_keyframes|vlm_timeout_fallback|vlm_invalid_json_fallback`
- `--incident-id <id>`
- `--camera-id <id>`
- `--no-keyframes` for JSON-only missing-keyframe validation
- `--dry-run` to print the planned event without writing DB/archive.
- `--clear-demo` to remove only `demo-*` outbox records and archive folders before seeding.
- `--seed-delivery-dry-run --delivery-db <path>` to also create a dev/demo `DeliveryOutbox` dry-run record for service-level acceptance. This remains dry-run and does not POST.

## Scenarios

```powershell
python scripts/seed_event_pipeline_demo.py --scenario fall_candidate_support --db data/event_outbox.sqlite3 --archive-dir logs/event_archive
python scripts/seed_event_pipeline_demo.py --scenario fallen_confirmed_high --db data/event_outbox.sqlite3 --archive-dir logs/event_archive
python scripts/seed_event_pipeline_demo.py --scenario adl_suppressed_review --db data/event_outbox.sqlite3 --archive-dir logs/event_archive
python scripts/seed_event_pipeline_demo.py --scenario missing_keyframes --db data/event_outbox.sqlite3 --archive-dir logs/event_archive
python scripts/seed_event_pipeline_demo.py --scenario vlm_timeout_fallback --db data/event_outbox.sqlite3 --archive-dir logs/event_archive
python scripts/seed_event_pipeline_demo.py --scenario vlm_invalid_json_fallback --db data/event_outbox.sqlite3 --archive-dir logs/event_archive
```

Each scenario creates:

- SQLite outbox record.
- Evidence package.
- Event semantics.
- Trusted result.
- Archive JSON files.
- Keyframe images unless missing-keyframe mode is selected.
- Timeline image at `timeline/timeline.jpg` when archive keyframes are enabled.
- Optional DeliveryOutbox dry-run record only when `--seed-delivery-dry-run` is passed.

## C-Line Scenario Acceptance

For C-line VLM/Qwen review acceptance, run each scenario against a temporary
SQLite DB and archive directory. Keep `EVENT_VLM_ENABLED=false` unless a test is
explicitly using dummy/mock adapters in Python.

```powershell
python scripts/seed_event_pipeline_demo.py --scenario fall_candidate_support --db <tmp>\event_outbox.sqlite3 --archive-dir <tmp>\archive
python scripts/seed_event_pipeline_demo.py --scenario fallen_confirmed_high --db <tmp>\event_outbox.sqlite3 --archive-dir <tmp>\archive
python scripts/seed_event_pipeline_demo.py --scenario adl_suppressed_review --db <tmp>\event_outbox.sqlite3 --archive-dir <tmp>\archive
python scripts/seed_event_pipeline_demo.py --scenario missing_keyframes --db <tmp>\event_outbox.sqlite3 --archive-dir <tmp>\archive
python scripts/seed_event_pipeline_demo.py --scenario vlm_timeout_fallback --db <tmp>\event_outbox.sqlite3 --archive-dir <tmp>\archive
python scripts/seed_event_pipeline_demo.py --scenario vlm_invalid_json_fallback --db <tmp>\event_outbox.sqlite3 --archive-dir <tmp>\archive
```

Expected checks:

- `fall_candidate_support`: reaches `delivery_pending` with rule support.
- `fallen_confirmed_high`: confirmed/high-critical is not downgraded.
- `adl_suppressed_review`: high ADL suppression is review/unsupported.
- `missing_keyframes`: missing evidence is recorded and placeholders are safe.
- `vlm_timeout_fallback`: `vlm_timeout` is present.
- `vlm_invalid_json_fallback`: `vlm_invalid_json` is present.

These checks do not request a real VLM endpoint and do not trigger a production
main-system alert.

## Frontend Check

After seeding, open:

```text
/events/latest?camera_id=camera_01
/events/{incident_id}
/events/{incident_id}/keyframes/t0
/demo/
```

The `/demo/` Event Semantic Review panel should show the incident fields,
degradation/uncertainty, and keyframe timeline. Missing keyframes should show
their missing reason instead of a broken image.

For a Qwen/VLM review check, use the same seeded event and open:

```text
/demo/?v=qwen-vlm-review-check
```

Expected default behavior is rule-only or VLM-not-enabled display because
`EVENT_VLM_ENABLED=false` by default.

## Production Alarm Check

To confirm the seed did not create a production alert:

- The command output includes `dev/demo only: no main-system POST was sent`.
- `delivery_mode` is `dry_run` for demo delivery records.
- `FallEventReporterService` is not called by the seed script.
- Incident ids should use the `demo-` prefix unless a test explicitly overrides
  them.
- `--clear-demo` removes only `demo-*` records and archive folders.

## Safety

- No real main-system delivery is invoked.
- No `FallEventReporterService` path is touched.
- No VLM model is downloaded or called.
- Generated keyframes are local demo images under the configured archive directory.
- `--clear-demo` only removes records and archive folders whose incident id starts with `demo-`.
