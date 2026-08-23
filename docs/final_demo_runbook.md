# Final Demo Runbook

## 1. Before The Demo

- Start the service with session-scoped variables only.
- Open `/demo/`.
- Check that video is visible.
- Check that overlay is present.
- Check Raw Status.
- Check Diagnostics.
- Check the Event Semantic Review panel.
- Confirm the local `.env` file is not changed.
- Confirm no real main-system POST is configured.
- Confirm VLM/Ollama remains default-off unless a separate controlled advisory demo has been approved.

## 2. Recommended Demo Sequence

1. Show the realtime video path.
2. Explain how the main path detects fall candidates.
3. Trigger a demo seed or use an accepted replay event.
4. Show the event summary.
5. Show the six keyframes.
6. Show the intelligent review explanation.
7. Show Delivery dry-run status.
8. Explain that the formal main-system alert path is still retained.
9. Explain that VLM/Ollama is currently default-off and reserved as optional advisory review.

## 3. Recommended Script

"实时检测主链路先发现跌倒候选。"

"事件语义链路不会阻塞实时检测，而是在后台抽取关键帧形成证据包。"

"当前 DeliveryOutbox 是 dry-run，表示投递流程已验证，但没有向真实主系统发送告警。"

"本地 Ollama/Qwen 已预留为事件级辅助复核能力，但当前评估未满足延迟预算，因此默认关闭。"

"Our realtime detection path first finds fall candidates. The event semantic path does not block realtime detection; it runs behind the main path, extracts keyframes, builds an evidence package, and generates an explainable event result."

"Current DeliveryOutbox is controlled dry-run. That means the delivery flow has been verified, but no alert has been sent to the real main system."

"Local Ollama/Qwen has been reserved as event-level advisory review. Because the latest local evaluation did not meet the latency budget, it remains disabled by default. The system still runs through the stable rule review path."

"The existing formal main-system alert path is still FallEventReporterService. The new event path is for evidence, review, display, and controlled delivery validation."

## 4. Forbidden Statements

- Do not say a large model directly determines falls.
- Do not say dry-run is a formal alert.
- Do not say Kafka, Redis, or Celery are connected.
- Do not say the formal main-system alert path has been replaced.
- Do not say the system can medically diagnose injury.
- Do not say images have been sent to external Qwen.
- Do not expose target URLs, tokens, headers, raw payloads, lock tokens, or local paths.
- 不要说“大模型直接判断跌倒”。
- 不要说“dry-run 已正式报警”。
- 不要说“系统已经接入 Kafka/Redis/Celery”。
- 不要说“系统已经替换正式主系统告警链路”。
- 不要说“系统能医疗诊断老人受伤情况”。
- 不要说“已向外部千问发送图片”。

## 5. Common Questions

Why is VLM default-off?

Because RuleAnalyzer is the stable default, and the latest local Ollama/Qwen evaluation timed out at the 15 second budget. VLM remains advisory-only and must pass latency, privacy, and fallback gates before demo enablement.

What is dry-run?

Dry-run creates and displays a delivery record without sending a real HTTP POST.

Why is `target_url` not shown?

It is intentionally hidden to avoid exposing internal endpoints and deployment secrets.

Why might keyframes be missing?

The event path records missing-frame reasons when archive frames are unavailable, keyframe serving is disabled, or an image cannot be safely resolved.

Why does DeliveryOutbox not replace the original alert path?

It is a reliable-delivery side path for future compatibility validation. The formal current alert channel remains `FallEventReporterService`.

What if there is no event?

Use the demo seed script or an already accepted replay event, and explain that the event panel only shows archived event evidence after a fall candidate or confirmed event enters the event path.
