"""Keep unit-test defaults explicit while the checked-in demo profile is PFV2."""

import os


# Existing tests that instantiate Settings() exercise the legacy contracts unless
# they explicitly replace pipeline_mode. Product processes still read .env.
os.environ.setdefault("PIPELINE_MODE", "legacy")
os.environ.setdefault("DEFAULT_CAMERA_ID", "camera_01")
os.environ.setdefault("DETECTION_ENABLED", "true")
os.environ.setdefault("FALL_DETECTOR_ENABLED", "true")
os.environ.setdefault("FALL_HINT_IN_DETECTION_SERVICE", "true")
os.environ.setdefault("FALL_HINT_WORKER_ENABLED", "false")
os.environ.setdefault("POST_FALL_V2_ENABLED", "false")
os.environ.setdefault("POST_FALL_V2_VLM_ENABLED", "false")
os.environ.setdefault("POST_FALL_V2_QWEN_ENABLED", "false")
os.environ.setdefault("POST_FALL_V2_QWEN_PROVIDER", "dummy")
os.environ.setdefault("POST_FALL_V2_KEYFRAME_POST_COLLECTION_ENABLED", "false")
os.environ.setdefault("QWEN_MEDIA_INPUT_ENABLED", "false")
os.environ.setdefault("QWEN_MEDIA_PRIVACY_APPROVED", "false")
