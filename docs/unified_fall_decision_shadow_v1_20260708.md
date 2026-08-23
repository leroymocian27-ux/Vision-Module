# Unified Fall Decision V1

## Summary

`UnifiedFallDecisionEngine` combines Fall Hint, Temporal, motion, pose, track quality, ADL suppression, and evidence freshness into one explainable fall score.

It has two modes:

- Shadow mode: emits debug only and does not affect alerts.
- Primary mode: writes the unified decision back to `fall_decision` and `alarm_preview`.

## Shadow Mode

```env
UNIFIED_DECISION_ENABLED=true
UNIFIED_DECISION_SHADOW=true
UNIFIED_DECISION_PRIMARY_ENABLED=false
```

Each person object may include:

- `fusion_debug.unified_shadow_decision.decision`
- `fusion_debug.unified_shadow_decision.confidence_breakdown`
- `fusion_debug.unified_shadow_decision.evidence_summary`
- `fusion_debug.unified_shadow_decision.decision_trace`

Shadow `fallen_confirmed` is diagnostic only. Reporter continues to use the existing official fields.

## Primary Gray Switch

```env
UNIFIED_DECISION_ENABLED=true
UNIFIED_DECISION_SHADOW=true
UNIFIED_DECISION_PRIMARY_ENABLED=true
```

Primary mode writes:

- `fall_decision.source=unified_fall_score_v1`
- `alarm_preview.source=unified_fall_score_v1`
- `fall_decision.unified_decision`
- `alarm_preview.unified_decision`
- `fusion_debug.unified_primary_decision`

## Safety Boundaries

- A single Fall Hint score cannot directly become official confirmed fall.
- Strong ADL suppression produces `suppressed`.
- Stale or frame-misaligned detection/tracking downgrades to `fallen_candidate`.
- Reporter still reads `fall_decision` and `alarm_preview`, so main-system payload compatibility is preserved.

## Rollback

```env
UNIFIED_DECISION_PRIMARY_ENABLED=false
UNIFIED_DECISION_ENABLED=false
```

Turning off primary restores the previous official decision path. Turning off unified decision also removes the shadow debug payload.
