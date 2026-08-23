# Configuration Reference

Date: 2026-07-20

## Profile Loading

Do not repeatedly edit the real `.env` during stabilization. Use a profile file:

```powershell
$env:VISION_SERVICE_ENV_FILE="D:\Program\camera-service\camera_79\configs\safe_demo.env"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Or use the helper scripts:

```powershell
.\scripts\start_safe_demo.ps1
.\scripts\start_production_candidate.ps1
```

## Profiles

### `configs/safe_demo.env`

Purpose:

- Stable local demo
- Repeatable smoke checks
- No real external delivery
- No Robot, Go2, or VLM

### `configs/dev_experiment.env`

Purpose:

- Local experiments
- Provider checks
- Model comparisons

Do not use this profile as acceptance evidence for stable release.

### `configs/production_candidate.env`

Purpose:

- Controlled RTSP preparation
- Real camera diagnosis

This profile still keeps real delivery, VLM, Robot Assist, and Go2 disabled.

## Safety Defaults

These must remain false in stable profiles unless a separate gate explicitly approves them:

```text
MAIN_SYSTEM_ALERT_ENABLED
EVENT_DELIVERY_ENABLED
EVENT_VLM_ENABLED
EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED
QWEN_MEDIA_INPUT_ENABLED
ROBOT_ASSIST_SERVICE_ENABLED
ROBOT_ASSIST_ENABLED
ROBOT_AUTO_DISPATCH_ENABLED
GO2_READ_ONLY_ENABLED
GO2_CONTROL_ENABLED
GO2_LOW_LEVEL_CONTROL_ENABLED
```

## Validation

Run:

```powershell
python scripts/validate_config.py --profile safe_demo
python scripts/validate_config.py --profile dev_experiment
python scripts/validate_config.py --profile production_candidate
```

The validator checks:

- unsafe enabled combinations
- missing model files
- suspicious model files
- credentials committed in profiles
- profile-specific boundary rules

