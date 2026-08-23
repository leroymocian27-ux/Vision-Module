# Phase 6F Runtime Configuration

## Production Default

```text
ENABLE_TEMPORAL=true
TEMPORAL_TRACK_MODE=all_tracks
TEMPORAL_MODEL_PROVIDER=mock
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v3.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v3_features.json
TEMPORAL_FALLBACK_TO_MOCK=true
```

## Recommended Runtime Observation

```text
ENABLE_TEMPORAL=true
TEMPORAL_TRACK_MODE=all_tracks
TEMPORAL_MODEL_PROVIDER=shadow
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v3.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v3_features.json
TEMPORAL_FALLBACK_TO_MOCK=true
TEMPORAL_ONNX_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider
```

## Limited Active Trial Only

Use this only on a local demo or fixed test camera after confirming fallback behavior:

```text
ENABLE_TEMPORAL=true
TEMPORAL_TRACK_MODE=all_tracks
TEMPORAL_MODEL_PROVIDER=onnx_lstm
TEMPORAL_ONNX_MODEL_PATH=models/fall_lstm_v3.onnx
TEMPORAL_FEATURE_SCHEMA_PATH=models/fall_lstm_v3_features.json
TEMPORAL_FALLBACK_TO_MOCK=true
```

Do not make `onnx_lstm` the default production provider until candidate/confirmed recall is improved and long-run shadow observation remains clean.
