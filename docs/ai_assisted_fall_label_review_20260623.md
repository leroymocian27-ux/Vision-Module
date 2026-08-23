# AI-assisted Fall Label Review Tool - 2026-06-23

## Scope

本阶段交付本地 fall positive QA 审核工具，只用于人工点击审核，不训练模型，不覆盖 baseline，不修改 `.env`，不修改生产代码，不执行真实 POST，不执行 git add/commit。

工具目录：

- `artifacts/ai_assisted_fall_label_review/review_app/`

数据底稿：

- `artifacts/ai_assisted_fall_label_review/review_items.csv`
- `artifacts/ai_assisted_fall_label_review/review_progress.json`
- `artifacts/ai_assisted_fall_label_review/review_decisions.csv`
- `artifacts/ai_assisted_fall_label_review/review_decisions.jsonl`
- `artifacts/ai_assisted_fall_label_review/contact_sheets/`

## How To Start

```powershell
cd D:\Program\vision_service
python artifacts\ai_assisted_fall_label_review\review_app\server.py
```

Open:

```text
http://127.0.0.1:8765
```

The service uses only Python standard library for the web server. Images and CSVs stay local.

## Review Workflow

The page shows one item at a time:

- candidate image
- YOLO pseudo bbox overlay
- video path
- image path
- timestamp
- suggested phase
- suggested class
- suggested bbox
- source
- split candidate

Decision buttons:

| Button | CSV values |
| --- | --- |
| Accept as human_verified | `review_decision=accept`, `label_status=human_verified` |
| Reject / not fall | `review_decision=reject`, `label_status=rejected` |
| Uncertain | `review_decision=uncertain`, `label_status=manual_review_required` |
| Ignore | `review_decision=ignore`, `label_status=ignored` |
| Fall / Fallen / Lying / Ignore class buttons | writes `review_decision=change_class`, updates `corrected_class`; still requires Accept before `human_verified` |

Shortcuts:

| Key | Action |
| --- | --- |
| A | Accept |
| R | Reject |
| F | corrected_class=fall |
| D | corrected_class=fallen |
| L | corrected_class=lying |
| I | Ignore |
| U | Uncertain |
| Left Arrow | Previous |
| Right Arrow | Next |
| S | Save progress |

## Filters

Supported filters:

- pending
- uncertain
- rejected
- ignored
- all
- video_id
- suggested_class

The tool resumes from `review_progress.json`. Each decision appends immediately to both:

- `review_decisions.csv`
- `review_decisions.jsonl`

## Leakage Protection

`review_items.csv` is generated from `image_level_manifest_final_qa.csv` and checks frozen sources:

- `artifacts/hardneg_v1_data_preparation/test_manifest_frozen.csv`
- `artifacts/hardneg_v1_data_preparation/fp_regression_set.csv`

Current generated review set has zero frozen/FP items. If a frozen/FP item is ever present, the app marks it blocked and disables Accept.

## Batch Skip

The app supports batch ignore for pending items in the current video. This is only for obvious pre-fall wrong frames or other non-usable runs. Batch human verification is intentionally not supported.

## Review Rules

- Normal standing, normal walking, or preparation before loss of balance: reject or ignore.
- Clear loss of balance / falling motion: class can be `fall`.
- Stable low posture after falling: class can be `fallen` or `lying`.
- Recovery / getting up: usually ignore.
- Normal sitting, squatting, or active lying down: reject or ignore unless clearly uncontrolled fall.
- No-person sample: must not contain fall boxes.
- Wrong target, wrong person, or uncertain class: reject or uncertain.

## Current Status

Generated items:

- review items: 298
- blocked frozen/FP items: 0
- contact sheets: 22

The tool can show images, overlay bbox, display metadata, save progress, and append decisions when you click review buttons. No fall sample is automatically upgraded to `human_verified`.

## Training Readiness

This stage does not make the dataset trainable by itself. Training remains blocked until enough fall items are accepted as `human_verified` and final manifests are regenerated from `review_decisions.csv/jsonl`.

Current answer:

- Human can perform fall positive QA through buttons/shortcuts: yes.
- Current dataset already satisfies training conditions: no.
