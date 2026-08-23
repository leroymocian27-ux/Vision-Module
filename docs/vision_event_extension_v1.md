# Vision 事件扩展 V1

`build_main_system_payload()` 保持旧顶层字段兼容，并在 `metadata` 添加：

```json
{
  "extension_schema": "eldercare.vision-event-extension.v1",
  "evidence": {
    "evidence_status": "complete|degraded",
    "keyframe_count": 0,
    "keyframe_urls": [],
    "missing_reasons": []
  },
  "semantic_analysis": {
    "support_fall_alarm": true,
    "final_event_type": "fall_confirmed",
    "final_risk_level": "high",
    "explanation": "rule result",
    "uncertainty": []
  },
  "robot_advisory": {
    "robot_assist_recommended": false,
    "advisory_only": true
  }
}
```

关键帧 URL 目前固定为空，避免把 archive 路径、临时关键帧 URL 或跨系统媒体访问合同提前暴露。`robot_assist_recommended=false` 不是业务否决，而是明确禁止 Vision 自动派遣；主系统人工审批是唯一任务入口。

验证：`tests/test_integration_contract_v1.py`、`tests/test_event_delivery_payload_compat.py`、`tests/test_event_delivery_security_payload.py`，12 passed。
