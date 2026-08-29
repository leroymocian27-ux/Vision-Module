# 轻量化事件 JSON 格式

从本次更新起，新生成的 `xiao` 和 `da` 事件 JSON 使用 `post_fall_local_evidence.v2`。目标是让结论和简短中文描述位于文件开头，同时删除重复的完整事件对象、模型运行参数和长篇诊断字段。

旧事件文件不覆盖，仍可用于历史追溯；回填脚本同时兼容旧版 `v1` 和新版 `v2` 二分类文件。

## 二分类输出：`xiao/<事件ID>/binary_result.json`

```json
{
  "schema_version": "post_fall_local_evidence.v2",
  "stage": "binary_confirmed",
  "decision": "FALL",
  "decision_description": "二分类确认跌倒候选，等待千问复核。",
  "incident_id": "pfv2-go2_front_camera-<事件ID>",
  "camera_id": "go2_front_camera",
  "confirmed_at": "<时间>",
  "fall_probability": {
    "max": 0.93,
    "mean": 0.66,
    "threshold": 0.3979087471961975
  },
  "evidence": {
    "positive_frames": "4/8",
    "consecutive_positive_frames": 3,
    "candidate_duration_ms": 1000
  },
  "keyframes": {
    "status": "ready",
    "missing_offsets_ms": [],
    "frames": [
      {"role": "pre_fall", "offset_ms": -1000, "file": "01_-1000ms_pre_fall.jpg"},
      {"role": "trigger", "offset_ms": 0, "file": "02_+0000ms_trigger.jpg"},
      {"role": "post_fall", "offset_ms": 3000, "file": "03_+3000ms_post_fall.jpg"}
    ]
  }
}
```

首先查看 `decision`：当前该文件只在二分类确认跌倒候选后生成，值为 `FALL`。`fall_probability` 和 `evidence` 只保留触发事件所需的核心数字。

## 千问输出：`da/<事件ID>/qwen_confirmation.json`

```json
{
  "schema_version": "post_fall_local_evidence.v2",
  "stage": "qwen_confirmed",
  "decision": "确认跌倒",
  "event_description": "人员由站立失衡后倒地。",
  "confidence": 0.91,
  "incident_id": "pfv2-go2_front_camera-<事件ID>",
  "camera_id": "go2_front_camera",
  "confirmed_at": "<时间>",
  "fall_verdict": "confirmed_fall",
  "keyframes": [
    "01_-1000ms_pre_fall.jpg",
    "02_+0000ms_trigger.jpg",
    "03_+3000ms_post_fall.jpg"
  ]
}
```

首先查看：

- `decision`：面向阅读的中文结论。
- `event_description`：千问生成的简短中文事件描述，归档时最多 80 个字符。
- `confidence`：千问置信度。
- `fall_verdict`：程序使用的枚举结论；`confirmed_fall` 才会写入 `da`。

## 千问实际生成的核心 JSON

为减少模型输出长度和等待时间，千问现在只被要求返回以下 5 个字段：

```json
{
  "schema_version": "pfv2_post_fall_detail.v1",
  "fall_verdict": "confirmed_fall",
  "posture": "人员失衡后倒地。",
  "summary": "人员由站立失衡后倒地。",
  "confidence": 0.91
}
```

其中 `posture` 最大 80 个字符，`summary` 最大 160 个字符；提示词进一步要求 `posture` 不超过 40 个汉字、`summary` 不超过 80 个汉字。程序写入 `da` 时会再次截短 `event_description`，使文件首屏更易查看。

## 性能说明

此次调整减少了千问返回字段、JSON 序列化内容和磁盘写入字节数。事件总耗时主要仍由关键帧 JPEG 写入与千问视觉推理决定，因此它会改善响应和文件读取体验，但不会替代视频采集、图像压缩或大模型推理层面的性能优化。
