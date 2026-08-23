# Current Stabilization Baseline

Date: 2026-07-20
Target version: `fall-monitor-stable-v1.0-rc`

## Scope

This baseline freezes the project for stabilization work. The goal is not to add new business capabilities. The goal is to make the current fall-monitoring chain startable, observable, repeatable, and packageable.

Stable main chain:

```text
Camera / Mock source
-> Capture worker
-> FrameBuffer
-> YOLO person detection
-> ByteTrack tracking
-> optional pose
-> optional temporal analysis
-> fall fusion
-> latest result store
-> Demo / WebSocket / integration API / local event evidence
```

## Current Code State

Repository root:

```text
D:\Program\camera-service\camera_79
```

Important modules:

```text
app/main.py
app/core/config.py
app/api/
app/camera/
app/detection/
app/tracking/
app/pose/
app/temporal/
app/fall/
app/events/
app/services/
frontend_demo/
identity_service/
robot_assist_service/
```

Current git tree is already dirty and contains many existing modified and untracked files. Stabilization work must avoid reverting unrelated user work.

## Runtime Profiles

Profiles introduced for stabilization:

```text
configs/safe_demo.env
configs/dev_experiment.env
configs/production_candidate.env
```

The real `.env` is not the stabilization contract. Profiles should be loaded by startup scripts or by `VISION_SERVICE_ENV_FILE`.

## Stable Boundary

Included in the stabilization acceptance scope:

- HTTP service startup and shutdown
- `/healthz`
- `/status`
- mock camera startup
- RTSP configuration readiness
- latest frame output
- person detection
- fall hint detection
- tracking
- pose disabled or enabled status
- temporal disabled, warmup, or enabled status
- fall fusion status
- WebSocket result stream
- latest integration result
- local event evidence and dry-run behavior
- Demo page showing only trusted stable capabilities

Kept in code but excluded from stable acceptance by default:

- Robot Assist
- Go2 control
- Qwen/Ollama VLM advisory
- real event delivery
- real main-system POST
- unverified identity auto-binding
- training and online tuning entry points

## Gate Vocabulary

Use only these status labels in stabilization reports:

```text
PASS
REVISE
BLOCKED
NOT_RUN
NOT_IN_SCOPE
```

Do not replace evidence with vague phrases such as "basically works" or "should be fine".

## First Gate

S0/S1 can pass only when:

- runtime profiles exist
- unsafe extensions are disabled by default
- config validation can run from one command
- the stable smoke command exists and reports NOT_RUN items honestly
- baseline docs are committed or otherwise preserved

Current S0/S1 gate result:

```text
PASS
```

Evidence:

```text
artifacts/stabilization/validate_safe_demo.json
artifacts/stabilization/validate_dev_experiment.json
artifacts/stabilization/validate_production_candidate.json
artifacts/stable_smoke/20260720T021030Z/summary.json
```

Known limitations:

- Real RTSP validation is `NOT_RUN`; `production_candidate` still needs a secure `DEFAULT_RTSP_URL`.
- Synthetic fall events, event evidence packages, WebSocket traffic, browser visual checks, and process cleanup deep scan are `NOT_RUN`.
- Robot Assist, Go2 control, Qwen/Ollama VLM advisory, and real event delivery remain `NOT_IN_SCOPE` for this stable gate.
