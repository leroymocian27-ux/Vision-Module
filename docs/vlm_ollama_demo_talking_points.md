# VLM Ollama Demo Talking Points

Audience: demo presenters and reviewers.

## Correct Statements

- The current system defaults to rule review.
- Local Ollama/Qwen has been reserved as an event-level auxiliary explanation
  capability.
- Local small-sample evaluation timed out under the 15 second budget, so Ollama
  remains disabled by default.
- The large model is not part of realtime first decision.
- The large model does not rewrite fall confirmation, risk level, or delivery
  status.
- The current demo can explain that the VLM layer is engineered to fail open to
  rules.

## Prohibited Statements

- Do not say the large model is online judging falls.
- Do not say local Qwen is stably enabled.
- Do not say the system depends on the large model to confirm falls.
- Do not describe model output as medical diagnosis.
- Do not say the system sends images to the model.
- Do not say the system is connected to external Qwen or DashScope.

## If Asked "Where Is The Large Model?"

Recommended answer:

> We place the large model at the event-level review layer, not in the realtime
> detection layer. The competition demo currently defaults to rule review, while
> Ollama/Qwen is retained as an optional auxiliary explanation capability. In
> our local test it exceeded the 15 second budget, so we keep it disabled by
> default to avoid affecting realtime behavior.

## If Asked "Why Not Enable It?"

Recommended answer:

> The model path is implemented and guarded, but two local Qwen candidates timed
> out in small-sample text-only smoke. We chose the safer engineering posture:
> keep rules authoritative, fail open, and only re-evaluate the model after it
> meets parse, latency, privacy, and advisory-only gates.
