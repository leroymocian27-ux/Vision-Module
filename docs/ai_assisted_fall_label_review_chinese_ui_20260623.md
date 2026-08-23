# AI-assisted Fall Label Review Chinese UI - 2026-06-23

## Scope

本阶段只中文化本地审核工具前端显示文案和必要样式。未训练模型，未覆盖 baseline，未修改 `.env`，未修改生产代码，未执行 git add/commit。

工具路径：

- `artifacts/ai_assisted_fall_label_review/review_app/`

页面地址保持：

- `http://127.0.0.1:8765`

## Modified Files

- `artifacts/ai_assisted_fall_label_review/review_app/index.html`
- `artifacts/ai_assisted_fall_label_review/review_app/app.js`
- `artifacts/ai_assisted_fall_label_review/review_app/styles.css`

`server.py` 未修改。审核输出字段结构未修改。

## Chinese UI Changes

已中文化：

- 页面标题：`跌倒样本人工审核`
- 顶部统计：`已审核 N / Total，待审核 M`
- 筛选器：待审核、不确定、已拒绝、已忽略、全部、全部视频、全部类别
- 元数据字段：样本编号、视频路径、图片路径、时间点、候选阶段、候选类别、候选框、来源、候选划分、审核状态
- 阶段显示：跌倒前、下落/跌倒中、倒地保持、恢复/起身、不适用
- 类别显示：跌倒中、已倒地、躺卧、忽略、不适用、无跌倒框
- 操作按钮：通过：人工确认、拒绝：不是跌倒、不确定、忽略、批量忽略当前视频待审核项
- 快捷键提示：`快捷键：A 通过，R 拒绝，F 跌倒中，D 已倒地，L 躺卧，I 忽略，U 不确定，方向键切换，S 保存。`
- frozen / FP 提示：`该样本属于冻结测试集或误报回归集，禁止加入训练。`

## Internal Values Kept In English

以下内部值保持英文不变，避免后续脚本解析失败：

- `review_decision=accept / reject / uncertain / ignore / change_class`
- `label_status=human_verified / rejected / manual_review_required / ignored`
- `corrected_class=fall / fallen / lying / ignore`
- `status=pending / uncertain / rejected / ignored`
- `review_decisions.csv` 字段名
- `review_decisions.jsonl` 字段名

## How To Start

```powershell
cd D:\Program\vision_service
python artifacts\ai_assisted_fall_label_review\review_app\server.py
```

Open:

```text
http://127.0.0.1:8765
```

## How To Review

- 点击 `标为跌倒中` / `标为已倒地` / `标为躺卧` 只会修改 `corrected_class`，不会自动通过。
- 只有点击 `通过：人工确认` 才会写入 `review_decision=accept` 和 `label_status=human_verified`。
- 点击 `拒绝：不是跌倒` 写入 `review_decision=reject` 和 `label_status=rejected`。
- 点击 `不确定` 写入 `review_decision=uncertain` 和 `label_status=manual_review_required`。
- 点击 `忽略` 写入 `review_decision=ignore` 和 `label_status=ignored`。

快捷键保持不变：

- A：通过
- R：拒绝
- F：标为 fall
- D：标为 fallen
- L：标为 lying
- I：忽略
- U：不确定
- 左/右方向键：上一张/下一张
- S：保存进度

## Verification

已验证：

- 页面重新加载后显示中文标题、统计栏、筛选器、元数据字段、按钮和快捷键说明。
- 图片与 bbox 叠加逻辑未破坏。
- 保存进度仍可用。
- 前端显示中文，但内部字段和枚举仍保持英文。

未执行：

- 未点击真实审核决策按钮替用户生成审核结论。
- 未训练模型。
- 未修改 baseline 权重。
- 未修改 `.env` 或生产代码。
