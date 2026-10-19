import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.events.qwen_keyframe import (
    _build_compact_post_fall_task,
    _compact_post_fall_constraints,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ==================== 千问中文提示词 ====================

VLM_SYSTEM_PROMPT = """
# Role
你是智慧养老移动陪护系统中的「跌倒事件视觉复核模型」。

你的任务不是重新检测画面中的所有目标，
而是对前级轻量模型提交的“疑似跌倒事件”进行二次语义复核。

# Input
你将收到同一事件前后的连续关键帧：

- pre_frame   : 事件发生前
- event_frame : 疑似跌倒时刻
- post_frame  : 事件发生后

同时可能收到前级小模型的检测置信度。

# Goal

结合事件前、中、后三帧的人物状态变化，将疑似事件判断为：

1. **fall**
   出现突然失衡、快速高度下降、非主动倒地等明显跌倒证据。

2. **normal_low_posture**
   出现主动坐下、躺卧、弯腰、蹲下等受控行为，且动作完成后状态稳定。

3. **uncertain**
   存在遮挡、画面不完整或动作过程证据不足，无法可靠判断。

# Decision Rules

## Rule 1：优先分析时序变化

不要只看最后一帧姿态，
重点分析 pre_frame → event_frame → post_frame 的状态变化。

## Rule 2：跌倒需要异常转场证据

重点关注突然失衡、快速下降、非主动倒地及倒地后的异常状态。

## Rule 3：正常行为需要主动证据

只有观察到屈膝、受控坐下、稳定躺卧等主动行为，
才能判断为 normal_low_posture。

# Output

结果统一输出为结构化 JSON：

* event_type：事件类型
* confidence：判断置信度
* evidence：最多 3 条关键视觉依据
* needs_manual_review：是否需要人工复核

"""
QWEN_USER_PROMPT = _build_compact_post_fall_task(countercheck=False)
QWEN_OUTPUT_FIELD_RULES = _compact_post_fall_constraints()


output_structure = {
    "frame_desc": "",
    "fall_flag": None,
    "activity": "",
    "confidence": 0.0,
    "source": "qwen3.5-4b",
    "fail_reason": None,
}


qwen_raw_output = {
    "e": "fall / reading / uncertain",
    "s": "ground / upright / unclear",
    "d": "yes / no / unclear",
    "f": "true / false",
    "c": "0 到 1",
    "t": "最后一张图片的中文描述",
}


qwen_field_mapping = {
    "e": "semantic_event，可选 fall/reading/uncertain",
    "s": "posture_state，可选 ground/upright/unclear",
    "d": "visible_distress，可选 yes/no/unclear",
    "f": "vlm_is_true_fall，是否判断为真实跌倒或风险",
    "c": "confidence，模型置信度",
    "t": "last_frame_description，最后一张图的中文描述",
}


def print_section(title, content):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    print(content)


def to_pretty_json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main():
    print_section("一、千问 system 中文提示词", VLM_SYSTEM_PROMPT)
    print_section("二、千问 user 中文提示词", QWEN_USER_PROMPT)
    print_section("三、千问 JSON 字段约束", "\n".join(f"- {rule}" for rule in QWEN_OUTPUT_FIELD_RULES))
    print_section("四、千问原始 JSON 输出模板", to_pretty_json(qwen_raw_output))
    print_section("五、字段含义映射", to_pretty_json(qwen_field_mapping))
    print_section("六、系统最终展示 JSON 模板", to_pretty_json(output_structure))


if __name__ == "__main__":
    main()
