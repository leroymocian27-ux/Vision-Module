# Phase 07 Gate Report

```text
gate_name: QWEN_ADVISORY_READY
gate_status: REVISE
execution_date: 2026-07-19
evidence_type: CODE_ONLY + automated privacy/fallback tests
```

## 已验证代码边界

- Ollama adapter 只接受 localhost endpoint、`stream=false`、JSON 输出和文本输入。
- 图片、关键帧、timeline、URL、路径、`incident_id`、`track_id`、`camera_id` 等稳定标识均被排除。
- Qwen 输出不能改写 `FallFusionService` 的 `fallen_confirmed`、风险等级或 Delivery 状态。
- 失败和非法 JSON 回退 RuleAnalyzer；不阻塞实时链路。
- Qwen 没有 RobotAssistTask 创建、审批或 Go2 控制入口。

## 验证

```text
pytest tests/test_qwen_ollama_advisory_privacy.py \
  tests/test_intelligent_analysis_engine_ollama_advisory_only.py \
  tests/test_intelligent_analysis_engine_vlm_fallback.py \
  tests/test_ollama_vlm_text_only_payload.py -q
13 passed
```

## REVISE 原因

真实本机 smoke 仍为 REVISE：一个模型超时，另一个模型返回非法 JSON。代码测试不构成模型运行时准入。

## 允许下一步

只可在独立会话、`127.0.0.1`、合成脱敏 JSON 下重新评估模型延迟与 JSON 合法率。`EVENT_VLM_ENABLED` 保持默认关闭，媒体输入继续禁止。
