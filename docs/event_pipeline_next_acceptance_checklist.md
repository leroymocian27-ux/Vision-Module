# Event Pipeline Acceptance Checklist

- [x] Fusion result safely falls back to snapshots when the fusion slot is empty or stale.
- [x] Event status, list, detail, and latest APIs are observable while the pipeline is disabled.
- [x] Memory and SQLite EventOutbox implementations have lease/CAS coverage.
- [x] Evidence JSON and bounded optional keyframe archives are implemented.
- [x] The demo has an event review panel and timeline placeholders.
- [x] Feature-flagged dry-run DeliveryOutbox produces main-system-compatible payloads.
- [x] No Kafka, Redis, or real VLM model is required.
- [ ] Validate an enabled pipeline against a real camera before production rollout.
- [ ] Define target retention limits from available disk capacity.
- [ ] Add an authenticated archive-image serving policy before exposing images outside the host.

For demonstration: describe this as event-level semantic modeling. The realtime detector produces the trigger; evidence, timeline, rule interpretation, degradation reporting, and reviewable delivery records create the event-level explanation. It is not an externally attached large-model decision path.
