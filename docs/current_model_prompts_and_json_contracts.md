# 当前二分类与千问模型的提示词和 JSON 输出规范

> **2026-08-28 更新**：Post-Fall V2 当前权威的职责边界、必填证据字段和告警规则见
> [Post-Fall V2 双路径安全决策](post_fall_v2_dual_path_safety_decision.md)。
> `confirmed_fall` 现在只表示真实可见的跌倒转场；只看到持续低位必须输出
> `unclear` 并填写结构化低位证据，由 Runtime 计算 10 秒持续时间。
> 本文后续较早的长提示词和 JSON 示例仅用于历史格式说明，不能覆盖上述规则。

本文记录当前 Post-Fall V2 运行链路实际使用的模型输入、提示词、JSON 输出结构和落盘规则。事件落盘格式现已升级为轻量化 `v2`；首屏字段和 JSON 示例请优先阅读 [轻量化事件 JSON 格式](compact_event_json_format.md)。

- 二分类证据文件：`C:\Users\YANG\Desktop\ce\xiao\<事件ID>\binary_result.json`
- 千问确认文件：`C:\Users\YANG\Desktop\ce\da\<事件ID>\qwen_confirmation.json`

## 1. 二分类模型：没有自然语言系统提示词

当前二分类模型是本地 ONNX 图像分类模型 `efficientnet_b0_post_fall`，不是大语言模型，因此**不存在 system prompt、user prompt 或 JSON 提示词**。它的处理规则由程序和模型权重固定决定：

```text
实时 BGR 图像
  -> BGR 转 RGB
  -> 按最长边等比缩放到 224
  -> 反射填充为 224 x 224
  -> 像素缩放到 [0, 1]
  -> ImageNet 标准化
     mean = [0.485, 0.456, 0.406]
     std  = [0.229, 0.224, 0.225]
  -> ONNX 输入 input: [1, 3, 224, 224]
  -> ONNX 输出 logits: [1, 2]
  -> softmax
  -> noFall 概率 = probs[0]，Fall 概率 = probs[1]
```

当前模型参数：

```text
模型文件: models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx
模型标签: 0 = noFall，1 = Fall
运行提供方: CPUExecutionProvider
输入策略: FULL_FRAME_TRAIN_MATCHED（整帧，不裁剪人物）
抽帧频率: 5 FPS
单帧阳性阈值: Fall 概率 >= 0.3979087471961975
```

### 二分类创建事件的程序规则

二分类单帧输出为 `FALL` 不会立刻创建事件。当前状态机要求：

```text
最近最多 8 帧中，至少 4 帧 Fall 概率 >= 0.3979087471961975
且最新连续阳性帧至少 3 帧
且候选持续时间至少 800 ms
```

满足后创建一个 `fall_confirmed` 事件，并开始收集关键帧。二分类模型判断的是当前图像是否具有“跌倒类外观”，它**没有“必须亲眼看到站立到倒地过程”的硬规则**；这也是已躺卧人员可能触发二分类事件的原因。

## 2. `binary_result.json` 的生成标准与模板

`binary_result.json` 不是 ONNX 模型逐帧直接输出的原文。它由系统在二分类事件建立、关键帧采集完成后写出，保存的是事件级聚合证据和关键帧索引。

当前文件结构如下，省略了实际事件 ID、时间和帧号：

```json
{
  "schema_version": "post_fall_local_evidence.v1",
  "stage": "binary_confirmed",
  "exported_at": "<UTC ISO 时间>",
  "event": {
    "incident_id": "pfv2-<camera_id>-<随机12位ID>",
    "camera_id": "go2_front_camera",
    "state": "fall_confirmed",
    "started_at": "<UTC ISO 时间>",
    "confirmed_at": "<UTC ISO 时间>",
    "binary_evidence": {
      "window_size": 8,
      "positive_count": 4,
      "consecutive_positive_count": 3,
      "mean_fall_probability": 0.0,
      "max_fall_probability": 0.0,
      "candidate_duration_ms": 800,
      "threshold": 0.3979087471961975
    },
    "keyframes": "<与根级 keyframes 相同的关键帧包>",
    "vlm_status": "collecting_keyframes",
    "vlm_analysis": null,
    "created_at": "<UTC ISO 时间>",
    "updated_at": "<UTC ISO 时间>"
  },
  "keyframes": {
    "incident_id": "pfv2-<camera_id>-<随机12位ID>",
    "camera_id": "go2_front_camera",
    "confirmed_at": "<UTC ISO 时间>",
    "source_width": 960,
    "source_height": 540,
    "frames": [
      {
        "role": "pre_context",
        "offset_ms": -3000,
        "frame_id": "<帧ID或null>",
        "frame_seq": 0,
        "timestamp": "<UTC ISO 时间或null>",
        "image_path": null,
        "missing_reason": null,
        "actual_offset_ms": -3000,
        "timing_error_ms": 0
      }
    ],
    "fall_probability_summary": {
      "window_size": 8,
      "positive_count": 4,
      "consecutive_positive_count": 3,
      "mean_fall_probability": 0.0,
      "max_fall_probability": 0.0,
      "candidate_duration_ms": 800,
      "threshold": 0.3979087471961975
    },
    "status": "ready",
    "requested_offsets_ms": [-3000, -1000, 0, 1000, 3000, 5000],
    "resolved_offsets_ms": [-3000, -1000, 0, 1000, 3000, 5000],
    "missing_offsets_ms": [],
    "max_offset_error_ms": 750
  },
  "saved_keyframes": [
    "01_-3000ms_pre_context.jpg",
    "02_-1000ms_pre_fall.jpg",
    "03_+0000ms_trigger.jpg",
    "04_+1000ms_post_fall.jpg",
    "05_+3000ms_post_fall.jpg",
    "06_+5000ms_post_check.jpg"
  ]
}
```

字段解释：

- `positive_count`：最近滑动窗口中达到单帧阈值的帧数。
- `consecutive_positive_count`：窗口末尾连续达到单帧阈值的帧数。
- `mean_fall_probability`、`max_fall_probability`：窗口内有效帧的跌倒概率统计值。
- `candidate_duration_ms`：从第一张连续阳性候选帧到事件创建帧的持续时间。
- `status = ready`：六个目标时间点均已解析；`degraded` 表示有关键帧缺失但仍可能继续调用千问。
- `saved_keyframes`：实际写入 `xiao` 目录的 JPEG 文件名。

## 3. 千问模型的当前系统提示词

当前使用本地 Ollama 模型 `qwen3.5:4b`，接口为本机 `http://127.0.0.1:11434/api/chat`，超时 `90` 秒。每个二分类事件最多传入 3 张 JPEG 核心关键帧：跌倒前、触发时和倒地后。

发送给千问的 system message 原文如下：

```text
你是本机跌倒候选事件的关键帧复核模型。先判断是否为非自愿跌倒，并明确排除自主躺卧、阅读、休息和锻炼。只返回请求的 JSON 对象。
```

## 4. 千问的任务文本和约束

千问 user message 是一个 JSON 文本，其中 `keyframes` 会替换为本次事件真实的偏移量和角色，随后附带 3 张图像。其当前任务文本原文为：

```text
前级视觉二分类系统产生的是候选事件，不是跌倒结论。请依据事件前后多张关键帧，独立判断是否有非自愿失稳跌倒。先输出 fall_verdict：confirmed_fall 仅用于可见失衡、失去支撑、突然倒向地面等非自愿跌倒证据；intentional_low_posture 用于主动坐下、躺下休息、躺下看书或看手机、锻炼拉伸等稳定且自主的低姿态；unclear 用于有人但无法从关键帧确认是否跌倒；insufficient_visual_evidence 用于无人、空场景或画面不足。人物躺卧本身不是跌倒证据，不得因为前级候选结果或持续低位而把主动躺卧判为 confirmed_fall。时间序列优先于单帧姿态：若前帧中人物站立、坐起或正在失去平衡，随后出现明显下落、伸手撑地或撞向地面的动作，再在后帧倒地，应判为 confirmed_fall。intentional_low_posture 仅适用于从最早关键帧起已稳定处于低位，或画面直接显示缓慢、受控地坐下/躺下，且没有失衡、急速下落或撑地动作的情形。
```

当前 `constraints` 原文如下：

```text
1. 只返回符合给定结构的 JSON 对象，不要输出解释、Markdown 或额外文字。
2. 所有自然语言描述必须使用简体中文，不得出现英文单词。
3. fall_verdict 是唯一允许使用英文枚举值的字段；posture、summary、scene_risks 和 review_points 不得写入英文枚举词。
4. 比较提供的跌倒前、触发时与倒地后三张关键帧的姿态变化和动作连续性，不能只看单帧躺卧姿态。
5. 仅当人物从最早帧起稳定低位，或直接看见全程受控地坐下/躺下，并且没有失衡、急速下落或撑地动作时，才判 intentional_low_posture。阅读物、手机、垫子或地面本身不能作为该结论的充分证据。
6. 若相邻帧显示站立或较高姿态后出现明显失衡、急速下落、伸手撑地或撞向地面的动作，随后倒地，即使场景中有垫子，也必须判 confirmed_fall。
7. 空场景、无人或画面不足时使用 unknown 或 insufficient_visual_evidence，不得猜测有人或跌倒。
8. 不得诊断骨折、脑出血、昏迷、死亡或任何具体疾病。
9. 不得推断身份、姓名、年龄、诊断、位置或房间。
10. 不得把二分类候选结果当作视觉事实；不得仅凭持续低位、未起身、垫子或可见性来确认跌倒，也不得忽略跨帧可见的失衡过程。
11. 不得输出路径、URL、RTSP 地址、凭据或任何标识符。
```

千问实际接收的 user JSON 结构如下：

```json
{
  "schema_version": "pfv2_post_fall_input.v1",
  "task": "<上述任务文本>",
  "keyframes": [
    {"offset_ms": -1000, "role": "pre_fall"},
    {"offset_ms": 0, "role": "trigger"},
    {"offset_ms": 3000, "role": "post_fall"}
  ],
  "keyframe_status": "ready",
  "missing_offsets_ms": [],
  "review_mode": "首次复核",
  "constraints": ["<上述 11 条约束>"]
}
```

图像以 Base64 JPEG 数组随 user message 一并传递，图像内容不写入上述 JSON 文本。

## 5. 千问必须输出的 JSON Schema

Ollama 请求使用严格 JSON Schema，额外字段不允许出现。当前期望结构等价于：

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "fall_verdict",
    "posture",
    "movement_level",
    "attempt_to_stand",
    "persistent_ground_state",
    "possible_help_gesture",
    "visibility",
    "occlusion",
    "scene_risks",
    "summary",
    "review_points",
    "confidence"
  ],
  "properties": {
    "schema_version": {"const": "pfv2_post_fall_detail.v1"},
    "fall_verdict": {
      "enum": [
        "confirmed_fall",
        "intentional_low_posture",
        "unclear",
        "insufficient_visual_evidence"
      ]
    },
    "posture": {"type": "string", "minLength": 1, "maxLength": 600},
    "movement_level": {
      "enum": ["none_observed", "slight", "active", "unknown", "insufficient_visual_evidence"]
    },
    "attempt_to_stand": {
      "enum": ["observed", "not_observed", "unknown", "insufficient_visual_evidence"]
    },
    "persistent_ground_state": {
      "enum": ["observed", "not_observed", "unknown", "insufficient_visual_evidence"]
    },
    "possible_help_gesture": {
      "enum": ["observed", "not_observed", "unknown", "insufficient_visual_evidence"]
    },
    "visibility": {
      "enum": ["good", "limited", "unknown", "insufficient_visual_evidence"]
    },
    "occlusion": {
      "enum": ["none", "partial", "severe", "unknown", "insufficient_visual_evidence"]
    },
    "scene_risks": {
      "type": "array",
      "items": {"type": "string", "minLength": 1, "maxLength": 600},
      "maxItems": 8
    },
    "summary": {"type": "string", "minLength": 1, "maxLength": 600},
    "review_points": {
      "type": "array",
      "items": {"type": "string", "minLength": 1, "maxLength": 600},
      "minItems": 1,
      "maxItems": 8
    },
    "confidence": {
      "anyOf": [
        {"type": "number", "minimum": 0.0, "maximum": 1.0},
        {"type": "null"}
      ]
    }
  }
}
```

千问返回的自然语言字段会被程序再次校验和清洗：禁止路径、URL、身份信息和医疗诊断；非中文描述会被拒绝；缺失或无法识别的 `fall_verdict` 会按 `unclear` 处理。

一个符合当前格式的返回示例为：

```json
{
  "schema_version": "pfv2_post_fall_detail.v1",
  "fall_verdict": "confirmed_fall",
  "posture": "人员从站立姿态失衡后倒向地面。",
  "movement_level": "none_observed",
  "attempt_to_stand": "not_observed",
  "persistent_ground_state": "observed",
  "possible_help_gesture": "not_observed",
  "visibility": "good",
  "occlusion": "none",
  "scene_risks": ["地面附近存在电线。"],
  "summary": "关键帧显示人员失去平衡后急速下落并倒地。",
  "review_points": ["前后帧可见由较高姿态到倒地的连续变化。"],
  "confidence": 0.92
}
```

## 6. `qwen_confirmation.json` 的生成标准与模板

`qwen_confirmation.json` 不是千问的裸响应，而是程序在千问返回后进行归档校验后生成。当前校验要求：

```text
analysis_status 必须为 completed
fall_verdict 必须为 confirmed_fall
posture 不能是空值、unknown、insufficient_visual_evidence、未知、画面不足或无法判断
posture 或 summary 必须包含倒地语义
posture 或 summary 必须能表明存在人；若 posture 已明确包含倒地姿态，也可满足
posture 或 summary 不能含“无人、空场景、仅有机器狗、无明确人体、无法确认有人”等否定人体表述
```

归档文件模板如下：

```json
{
  "schema_version": "post_fall_local_evidence.v1",
  "stage": "qwen_confirmed",
  "exported_at": "<UTC ISO 时间>",
  "confirmation_policy": {
    "analysis_status": "completed",
    "fall_verdict": "confirmed_fall",
    "required_visual_evidence": [
      "关键帧中明确看见人或人体",
      "姿态或摘要明确描述倒地、摔倒或等价倒地姿态"
    ],
    "not_required": [
      "persistent_ground_state",
      "attempt_to_stand",
      "visibility",
      "occlusion"
    ]
  },
  "event": "<包含二分类证据、关键帧和 vlm_analysis 的完整事件对象>",
  "qwen_analysis": "<第 5 节的千问结果对象>",
  "saved_keyframes": ["<6 张关键帧文件名>"]
}
```

注意：你提供的 `ed0de6690a1c/qwen_confirmation.json` 是旧版本运行时留下的历史文件，里面缺少当前新增的 `fall_verdict` 和 `confirmation_policy.fall_verdict`。当前代码的标准已包含这两个字段；新事件会按本文的最新模板写入。

## 7. 文件、模型与代码的对应关系

| 内容 | 当前实现位置 |
| --- | --- |
| ONNX 预处理、logits 和 softmax | `app/post_fall_v2/fall_binary_classifier_service.py` |
| 二分类事件状态机 | `app/post_fall_v2/binary_decision_aggregator.py` |
| 关键帧采集、二分类和千问调度 | `app/post_fall_v2/post_fall_runtime_service.py` |
| 千问 system message、任务文本、Schema、结果清洗 | `app/events/qwen_keyframe.py` |
| 千问结果适配、超时和失败处理 | `app/post_fall_v2/qwen_fall_analyzer.py` |
| `xiao`、`da` 文件写入及最终归档校验 | `app/post_fall_v2/evidence_exporter.py` |
| 当前阈值和模型配置 | `.env` 的 `POST_FALL_V2_*` 配置项 |
