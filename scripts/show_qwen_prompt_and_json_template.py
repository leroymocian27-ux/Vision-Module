"""展示千问提示词与 JSON 输出格式。

这个脚本只用于课堂演示或答辩讲解，不会调用千问模型，也不会修改系统运行结果。
"""

import json
import sys
from textwrap import dedent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ==================== 千问中文提示词集中展示区 ====================

QWEN_SYSTEM_PROMPT = dedent(
    """
    你负责复核养老场景中的跌倒候选事件。

    Binary FALL 只是候选，不是视觉事实。

    根据三张按时间排序的图片判断人物是真实跌倒、异常风险、玩手机、阅读、正常活动还是无法确认。

    真实跌倒包括明显非自主失衡、失控下落或异常倒地。
    稳定玩手机、稳定阅读以及明确正常活动属于非真实跌倒。

    只依据图片中可见事实判断，不推测疾病或身份。
    只返回符合 Schema 的 JSON。
    """
).strip()


QWEN_USER_PROMPT = dedent(
    """
    养老跌倒复核。

    三张图片按时间顺序排列，第三张是最后画面。

    e 只能选择：
    fall / risk / phone / reading / normal / uncertain。

    fall：
    看到明显非自主失衡、失控下落或异常倒地。

    risk：
    人物处于明显异常低位、异常倒地，或可见痛苦、挣扎、求助等风险状态，但不足以完整确认跌倒过程。

    phone：
    多帧明确显示人物稳定使用手机。

    reading：
    多帧明确显示人物稳定阅读书本、资料或纸张。

    normal：
    明确为正常站立、行走、坐下、弯腰、休息或其他受控正常活动。

    uncertain：
    关键人物、物体或状态确实无法看清。

    第三张图片是最终需要描述的画面。
    t 使用一句不超过 40 个汉字的简体中文描述第三张图片。

    只输出 Schema JSON，不要输出解释、Markdown 或额外文字。
    """
).strip()


QWEN_OUTPUT_FIELD_RULES = [
    "只返回字段 e、s、d、f、c、t。",
    "e = semantic_event，事件类型。",
    "s = posture_state，只能是 ground / upright / unclear。",
    "d = visible_distress，只能是 yes / no / unclear。",
    "f = VLM 直接判断是否为真实跌倒或风险，取值 true / false。",
    "c = confidence，置信度范围 0 到 1。",
    "t = last_frame_description，不超过 40 个汉字。",
    "不得输出路径、URL、RTSP 地址、凭据或任何标识符。",
]


# ==================== 千问 JSON 输出格式展示区 ====================

qwen_raw_output = {
    "e": "fall / risk / phone / reading / normal / uncertain",
    "s": "ground / upright / unclear",
    "d": "yes / no / unclear",
    "f": "true / false",
    "c": "0 到 1",
    "t": "最后一张图片的中文描述",
}


qwen_field_mapping = {
    "e": "semantic_event，可选 fall/risk/phone/reading/normal/uncertain",
    "s": "posture_state，可选 ground/upright/unclear",
    "d": "visible_distress，可选 yes/no/unclear",
    "f": "vlm_is_true_fall，是否判断为真实跌倒或风险",
    "c": "confidence，模型置信度",
    "t": "last_frame_description，最后一张图的中文描述",
}


# ==================== 系统业务决策 JSON 展示区 ====================

decision_fields = {
    #
    "frame_desc",
    "fall_flag",
    "activity",
    "conf",
    "source",
    "fail_reason",
}


alert = {
    "level": "告警等级",
    "reason": "告警原因",
}


display_payload = {
    "decision": sorted(decision_fields),
    "alert": alert,
}


def print_section(title, content):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    print(content)


def to_pretty_json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main():
    print_section("一、千问 system 中文提示词", QWEN_SYSTEM_PROMPT)
    print_section("二、千问 user 中文提示词", QWEN_USER_PROMPT)
    print_section("三、千问 JSON 字段约束", "\n".join(f"- {rule}" for rule in QWEN_OUTPUT_FIELD_RULES))
    print_section("四、千问原始 JSON 输出模板", to_pretty_json(qwen_raw_output))
    print_section("五、字段含义映射", to_pretty_json(qwen_field_mapping))
    print_section("六、系统最终展示 JSON 模板", to_pretty_json(display_payload))


if __name__ == "__main__":
    main()
