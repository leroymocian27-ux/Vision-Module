# AI-assisted Fall Label Review UI Refine 20260623

## Scope

This pass refined only the local review tool UI and its review-output compatibility layer:

- `artifacts/ai_assisted_fall_label_review/review_app/index.html`
- `artifacts/ai_assisted_fall_label_review/review_app/app.js`
- `artifacts/ai_assisted_fall_label_review/review_app/styles.css`
- `artifacts/ai_assisted_fall_label_review/review_app/server.py`

No model training was started. The baseline weight `models/yolo_fall_detector_phase9_selected.pt` was not modified. `.env`, production service code, training manifests, `data.yaml`, git staging, and commits were not touched.

## UI Changes

Added a visible warning for likely pre-fall or normal-pose frames:

`该帧看起来像跌倒前或正常姿态，请勿通过为 fall 正样本。`

Added a quick reference section:

- 正常站立、正常行走、准备动作：拒绝
- 明显失衡、正在下落：标为跌倒中 + 通过
- 已倒地保持：标为已倒地/躺卧 + 通过
- 正常坐下、蹲下、主动躺下：拒绝
- 看不清或框错：不确定或拒绝

Added one-click reason buttons:

- 拒绝：正常站立
- 拒绝：正常行走
- 拒绝：跌倒前准备动作
- 拒绝：正常坐下/蹲下
- 拒绝：主动躺下
- 拒绝：框错人/框错误
- 不确定：看不清
- 不确定：类别难判断

The new buttons auto-save and move to the next item, matching the existing reject/uncertain review flow.

## Output Field Compatibility

Added optional `reject_reason` to `review_decisions.csv` and `review_decisions.jsonl`.

The existing internal enums remain unchanged:

- `review_decision=accept / reject / uncertain / ignore / change_class`
- `label_status=human_verified / rejected / manual_review_required / ignored`
- `corrected_class=fall / fallen / lying / ignore`
- `status=pending / uncertain / rejected / ignored`

Existing decision CSV files are migrated on server startup by adding the `reject_reason` column while preserving previous rows.

## Button Mapping

| Button | review_decision | label_status | reject_reason |
| --- | --- | --- | --- |
| 拒绝：正常站立 | `reject` | `rejected` | `pre_fall_standing` |
| 拒绝：正常行走 | `reject` | `rejected` | `pre_fall_walking` |
| 拒绝：跌倒前准备动作 | `reject` | `rejected` | `pre_fall_preparation` |
| 拒绝：正常坐下/蹲下 | `reject` | `rejected` | `normal_sit_or_squat` |
| 拒绝：主动躺下 | `reject` | `rejected` | `active_lie_down_non_fall` |
| 拒绝：框错人/框错误 | `reject` | `rejected` | `wrong_bbox` |
| 不确定：看不清 | `uncertain` | `manual_review_required` | `unclear_image` |
| 不确定：类别难判断 | `uncertain` | `manual_review_required` | `ambiguous_class` |

Class buttons still only change `corrected_class` through `review_decision=change_class`. They do not write `label_status=human_verified`. Only `通过：人工确认` can write `label_status=human_verified`.

## Launch

```powershell
cd D:\Program\vision_service
python artifacts\ai_assisted_fall_label_review\review_app\server.py
```

Open:

```text
http://127.0.0.1:8765
```

## Verification

Planned verification items:

- Page shows the new Chinese reason buttons.
- New warning and quick rules are visible.
- New reason button writes `review_decision`, `label_status`, and `reject_reason`.
- Existing shortcuts remain unchanged: A, R, F, D, L, I, U, arrow keys, S.
- Frozen test / FP regression Accept blocking remains in place.

