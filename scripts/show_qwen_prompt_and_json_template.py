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


# ==================== 千问中文提示词集中展示区 ====================

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
请结合人物前后状态变化，判断当前事件属于：

1. fall
   人物发生明显失衡、倒地或由站立/行走状态快速转为倒地状态。

2. normal_low_posture
   人物主动坐下、躺卧、弯腰、蹲下、取物等正常低姿态行为。

3. uncertain
   画面遮挡、人物不完整、关键帧不足或证据不足，无法可靠判断。

# Decision Rules

## Rule 1：优先分析动作过程
不要只根据最后一帧姿态判断。
重点观察人物从 pre_frame 到 event_frame 再到 post_frame 的状态变化。

## Rule 2：识别真实跌倒证据
重点关注：
- 是否存在突然失衡；
- 是否发生快速高度下降；
- 是否出现非主动倒地；
- 倒地后是否持续保持异常姿态。

## Rule 3：识别正常低姿态行为
如果人物动作具有明显主动性，
例如缓慢坐下、正常躺卧、弯腰取物，
且动作完成后状态稳定，应判断为 normal_low_posture。

## Rule 4：证据不足时禁止强行判断
如果关键人物被遮挡、画面模糊、
前后帧不足或无法确认动作过程，
必须输出 uncertain。

## Rule 5：安全优先
uncertain 不等于 normal。
对于无法可靠确认的事件，
必须设置 needs_manual_review = true。

# Output Requirements
只能输出符合指定 JSON Schema 的 JSON 对象。

禁止：
- 输出 Markdown；
- 输出额外解释文字；
- 输出医疗诊断；
- 输出 Schema 中不存在的字段。

confidence 范围必须为 0.0 ~ 1.0。
evidence 最多保留 3 条最关键视觉依据。
"""
QWEN_USER_PROMPT = _build_compact_post_fall_task(countercheck=False)
QWEN_OUTPUT_FIELD_RULES = _compact_post_fall_constraints()


# ==================== 千问 JSON 输出格式展示区 ====================

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


# ==================== 系统业务决策 JSON 展示区 ====================

output_structure = {
    "frame_desc": "",
    "fall_flag": None,
    "activity": "",
    "confidence": 0.0,
    "source": "qwen3.5-4b",
    "fail_reason": None,
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
