# Legacy 69 Service Checkout Record - 2026-06-21

## Scope

This record documents the isolated checkout used to audit the legacy Vision
Service candidate repository. It did not overwrite or modify the current
working repository at `D:\Program\vision_service`.

## Checkout

- requested_repo_url: `https://github.com/kangzhouyang/69-service-`
- requested_branch: `main`
- requested_commit: `fccce1d`
- resolved_commit: `fccce1dc612e21b0e3bced994a123413448a49ee`
- resolved_commit_subject: `Update main system bridge target`
- resolved_commit_date: `2026-06-09 21:37:54 +0800`
- isolated_checkout_path: `D:\Program\legacy_sources\69-service-good-candidate`
- checkout_status: `PASS`
- git_status: clean

Network access to the GitHub remote was not reliable during this audit. The
current repository already had `origin=https://github.com/kangzhouyang/69-service-.git`
and local git history containing `fccce1d`, so the legacy checkout was created
with an isolated local clone from the current repository object store:

```text
git clone --no-hardlinks D:\Program\vision_service D:\Program\legacy_sources\69-service-good-candidate
git checkout main
git checkout fccce1d
```

The isolated clone's `origin` is therefore `D:\Program\vision_service`; this is
an audit-source detail only and does not change the requested legacy repo URL.

## File Structure

Top-level directories found in the isolated checkout:

- `.pytest_cache`
- `app`
- `docs`
- `evaluations`
- `frontend_demo`
- `identity_service`
- `models`
- `scripts`
- `tests`

Important backend modules:

- `app/pose/yolo_pose_estimator.py`
- `app/pose/pose_estimator.py`
- `app/pose/schemas.py`
- `app/pose/mock_pose_estimator.py`
- `app/services/pose_service.py`
- `app/services/pose_worker_service.py`
- `app/services/result_publisher_service.py`
- `app/services/fall_event_reporter_service.py`
- `app/services/alert_simulator_service.py`
- `app/api/alerting_api.py`

Important frontend overlay modules:

- `frontend_demo/overlay.js`
- `frontend_demo/app.js`
- `frontend_demo/index.html`

## Runtime And Dependencies

Dependency manifest found:

- `requirements.txt`
- `requirements-identity.txt`
- `identity_service/requirements.txt`
- `identity_service/requirements-identity.txt`

Main `requirements.txt` includes:

- `fastapi`
- `uvicorn[standard]`
- `opencv-python`
- `numpy`
- `aiortc`
- `av`
- `ultralytics`
- `pydantic`
- `lap`
- `python-multipart`

Local import probe from the current Python environment:

- `cv2`: OK
- `numpy`: OK
- `ultralytics`: OK
- `fastapi`: OK
- `pydantic`: OK
- `requests`: OK

This only confirms local dependency availability. It does not mean the legacy
service was started.

## Model Files

The isolated legacy checkout contains no model binary files with these
extensions:

- `.pt`
- `.pth`
- `.onnx`
- `.engine`
- `.weights`

The legacy `.gitignore` excludes model binaries:

- `*.pt`
- `*.pth`
- `*.onnx`
- `*.engine`

The legacy pose config points to `YOLO_POSE_MODEL_PATH=yolov8n-pose.pt`, but the
file is not present in the isolated legacy checkout. Current-machine probe used
local current-repo weights only, documented separately:

- `D:\Program\vision_service\yolov8n.pt`
- `D:\Program\vision_service\yolov8n-pose.pt`

## Config Files

Legacy config files found:

- `.env.example`
- `app/core/config.py`
- `identity_service/.env.example`
- `identity_service/app/core/config.py`

Relevant legacy pose config:

- code default: `ENABLE_POSE=false`
- code default provider: `POSE_PROVIDER=mock`
- `.env.example`: `ENABLE_POSE=true`
- `.env.example`: `POSE_PROVIDER=yolo`
- `.env.example`: `YOLO_POSE_MODEL_PATH=yolov8n-pose.pt`

Relevant legacy bridge config:

- `.env.example`: `MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1`
- `.env.example`: `MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events`
- `.env.example`: auth header name is `X-Vision-Service-Token`
- `.env.example`: token value is empty

No token value from current local configuration is copied into this report.

## Safety Notes

- The old service was not started.
- No process was bound to port `8000` or `8012` for this audit.
- No alert was posted to the main system.
- No bridge config was changed.
- No current runtime config was changed.
- No training was run.
