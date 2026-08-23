from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "pose_optimization_production_handoff_20260705.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a staff-facing pose optimization handoff Markdown report.")
    parser.add_argument("--preflight", default="evaluations/pose_production_preflight_20260705.json")
    parser.add_argument("--model-quality", default="evaluations/pose_model_quality_20260705.json")
    parser.add_argument("--candidate-model-quality", default="evaluations/pose_model_quality_yolo11s_candidate_20260705.json")
    parser.add_argument("--production-pipeline", default="evaluations/pose_optimization_pipeline_20260705.json")
    parser.add_argument("--dev-readiness", default="evaluations/pose_optimization_readiness_dev_smoke_20260705.json")
    parser.add_argument("--dev-comparison", default="evaluations/pose_lstm_comparison_dev_smoke_20260705.json")
    parser.add_argument("--evidence-package", default="evaluations/pose_evidence_package_check_20260705.json")
    parser.add_argument("--deployment-guard", default="evaluations/pose_deployment_guard_20260705.json")
    parser.add_argument("--launch-safety", default="evaluations/pose_launch_safety_check_20260705.json")
    parser.add_argument("--promotion-gate", default="evaluations/pose_promotion_gate_20260705.json")
    parser.add_argument("--production-dry-run", default="evaluations/pose_optimization_pipeline_dry_run_20260705.json")
    parser.add_argument("--dev-smoke-dry-run", default="evaluations/pose_optimization_pipeline_dev_smoke_dry_run_20260705.json")
    parser.add_argument("--dev-live-dry-run", default="evaluations/pose_optimization_pipeline_dev_live_bcpu_dry_run_20260705.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    markdown = build_handoff_markdown(
        preflight_path=Path(args.preflight),
        production_pipeline_path=Path(args.production_pipeline),
        dev_readiness_path=Path(args.dev_readiness),
        dev_comparison_path=Path(args.dev_comparison),
        model_quality_path=Path(args.model_quality),
        candidate_model_quality_path=Path(args.candidate_model_quality),
        evidence_package_path=Path(args.evidence_package),
        deployment_guard_path=Path(args.deployment_guard),
        launch_safety_path=Path(args.launch_safety),
        promotion_gate_path=Path(args.promotion_gate),
        production_dry_run_path=Path(args.production_dry_run),
        dev_smoke_dry_run_path=Path(args.dev_smoke_dry_run),
        dev_live_dry_run_path=Path(args.dev_live_dry_run),
    )
    output = resolve_path(Path(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(str(output))
    return 0


def build_handoff_markdown(
    *,
    preflight_path: Path,
    production_pipeline_path: Path,
    dev_readiness_path: Path,
    dev_comparison_path: Path,
    model_quality_path: Path | None = None,
    candidate_model_quality_path: Path | None = None,
    evidence_package_path: Path | None = None,
    deployment_guard_path: Path | None = None,
    launch_safety_path: Path | None = None,
    promotion_gate_path: Path | None = None,
    production_dry_run_path: Path | None = None,
    dev_smoke_dry_run_path: Path | None = None,
    dev_live_dry_run_path: Path | None = None,
) -> str:
    preflight = load_json(preflight_path)
    model_quality = load_json(model_quality_path) if model_quality_path else {}
    candidate_model_quality = load_json(candidate_model_quality_path) if candidate_model_quality_path else {}
    production_pipeline = load_json(production_pipeline_path)
    dev_readiness = load_json(dev_readiness_path)
    dev_comparison = load_json(dev_comparison_path)
    evidence_package = load_json(evidence_package_path) if evidence_package_path else {}
    deployment_guard = load_json(deployment_guard_path) if deployment_guard_path else {}
    launch_safety = load_json(launch_safety_path) if launch_safety_path else {}
    promotion_gate = load_json(promotion_gate_path) if promotion_gate_path else {}
    production_dry_run = load_json(production_dry_run_path) if production_dry_run_path else {}
    dev_smoke_dry_run = load_json(dev_smoke_dry_run_path) if dev_smoke_dry_run_path else {}
    dev_live_dry_run = load_json(dev_live_dry_run_path) if dev_live_dry_run_path else {}

    lines: list[str] = []
    lines.append("# 姿态检测优化生产交接说明")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now(timezone.utc).isoformat()}")
    lines.append("- 结论级别：当前不能宣布生产可用，只能宣布门禁更硬、证据更清楚。")
    lines.append("- 核心判断：姿态链路的问题不是单个模型拉胯，而是模型、运行时调度、骨架绑定、时序入模、生产验证一起拖后腿。")
    lines.append("")

    lines.extend(section_current_verdict(preflight, production_pipeline, dev_readiness, dev_comparison))
    lines.extend(section_evidence_inventory(preflight_path, production_pipeline_path, dev_readiness_path, dev_comparison_path))
    lines.extend(section_model_quality(model_quality_path, model_quality, candidate_model_quality_path, candidate_model_quality))
    lines.extend(section_evidence_package(evidence_package_path, evidence_package))
    lines.extend(section_deployment_guard(deployment_guard_path, deployment_guard))
    lines.extend(section_launch_safety(launch_safety_path, launch_safety))
    lines.extend(section_promotion_gate(promotion_gate_path, promotion_gate))
    lines.extend(section_production_blockers(preflight, production_pipeline))
    lines.extend(section_dev_smoke_findings(dev_readiness, dev_comparison))
    lines.extend(section_commands(production_dry_run, dev_smoke_dry_run, dev_live_dry_run))
    lines.extend(section_acceptance_rules())
    lines.extend(section_next_steps())
    return "\n".join(lines).rstrip() + "\n"


def section_current_verdict(
    preflight: dict[str, Any],
    production_pipeline: dict[str, Any],
    dev_readiness: dict[str, Any],
    dev_comparison: dict[str, Any],
) -> list[str]:
    pipeline_summary = summary_of(production_pipeline)
    preflight_summary = summary_of(preflight)
    readiness_summary = summary_of(dev_readiness)
    comparison_summary = summary_of(dev_comparison).get("comparison", {})
    return [
        "## 1. 当前状态",
        "",
        f"- 生产流水线状态：`{pipeline_summary.get('status', 'unknown')}`，失败阶段：`{pipeline_summary.get('failed_stage') or 'none'}`。",
        f"- 生产预检：`passed={bool(preflight_summary.get('passed'))}`，这一步没过，后面的生产结论全都不能吹。",
        f"- 开发冒烟 readiness：`overall_ready={bool(readiness_summary.get('overall_ready'))}`，`production_ready={bool(readiness_summary.get('production_ready'))}`。",
        f"- LSTM 姿态对照：`passed={bool(comparison_summary.get('passed'))}`，当前姿态 LSTM 没有证明自己比 bbox+motion baseline 更有用。",
        "",
        "难听但重要：现在最危险的不是“姿态没有输出”，而是系统可能输出了一堆看起来像姿态证据的字段，但这些字段没有稳定、正确、有效地支撑跌倒判断。",
        "",
    ]


def section_evidence_inventory(
    preflight_path: Path,
    production_pipeline_path: Path,
    dev_readiness_path: Path,
    dev_comparison_path: Path,
) -> list[str]:
    rows = [
        ("生产预检", preflight_path, "检查 CUDA、依赖、生产参数、实时 /status。"),
        ("生产流水线", production_pipeline_path, "记录生产门禁执行到哪里失败。"),
        ("开发冒烟 readiness", dev_readiness_path, "开发证据汇总，只能说明链路形状，不能当生产证据。"),
        ("开发 LSTM 对照", dev_comparison_path, "baseline、pose LSTM、zero-pose ablation 的直接对比。"),
    ]
    lines = ["## 2. 已有证据文件", "", "| 证据 | 文件 | 用途 |", "| --- | --- | --- |"]
    for name, path, purpose in rows:
        lines.append(f"| {name} | `{normalize_path(path)}` | {purpose} |")
    lines.append("")
    return lines


def section_model_quality(
    path: Path | None,
    payload: dict[str, Any],
    candidate_path: Path | None = None,
    candidate_payload: dict[str, Any] | None = None,
) -> list[str]:
    if not payload:
        return [
            "## 3. 姿态模型质量门",
            "",
            "- 尚未生成 pose model quality check。没有这份证据，就不能证明当前接入的姿态模型比 baseline 更值得上生产。",
            "",
        ]
    summary = summary_of(payload)
    blockers = summary.get("blockers", []) if isinstance(summary.get("blockers"), list) else []
    warnings = summary.get("warnings", []) if isinstance(summary.get("warnings"), list) else []
    lines = [
        "## 3. 姿态模型质量门",
        "",
        f"- 校验文件：`{normalize_path(path) if path else 'unknown'}`",
        f"- passed：`{bool(summary.get('passed'))}`。",
        f"- baseline：`{summary.get('baseline_model')}`，pose mAP50-95：`{fmt_metric(summary.get('baseline_pose_map50_95'))}`。",
        f"- candidate：`{summary.get('candidate_model')}`，pose mAP50-95：`{fmt_metric(summary.get('candidate_pose_map50_95'))}`。",
        f"- delta pose mAP50-95：`{fmt_metric(summary.get('delta_pose_map50_95'))}`。",
        f"- next_action：{summary.get('next_action') or 'none'}",
        "",
    ]
    if blockers:
        lines.append(f"- blockers：{format_code_list(blockers)}")
        lines.append("")
    if warnings:
        lines.append(f"- warnings：{format_code_list(warnings)}")
        lines.append("")
    candidate_payload = candidate_payload or {}
    candidate_summary = summary_of(candidate_payload)
    if candidate_summary:
        lines.extend(
            [
                "- 候选模型诊断：",
                f"  - 文件：`{normalize_path(candidate_path) if candidate_path else 'unknown'}`",
                f"  - passed：`{bool(candidate_summary.get('passed'))}`。",
                f"  - candidate：`{candidate_summary.get('candidate_model')}`，pose mAP50-95：`{fmt_metric(candidate_summary.get('candidate_pose_map50_95'))}`。",
                f"  - blockers：{format_code_list(candidate_summary.get('blockers', []))}",
                "",
            ]
        )
    lines.append("刺耳但必要：候选模型更快不等于更好；如果 pose mAP50-95 低于 baseline，就不能拿它给姿态链路背书。")
    lines.append("默认生产启动应回退到 `yolo11n-pose.pt` baseline；`pose_yolo_batch001_003_yolo11s_best.pt` 只能作为候选继续诊断，不能当默认生产增强模型。")
    lines.append("")
    return lines


def section_evidence_package(path: Path | None, payload: dict[str, Any]) -> list[str]:
    if not payload:
        return [
            "## 4. 交接包校验",
            "",
            "- 尚未生成 evidence package check。请先运行 `python scripts\\check_pose_evidence_package.py`，否则工作人员只能人肉翻 JSON，容易漏掉硬伤。",
            "",
        ]
    summary = summary_of(payload)
    blockers = summary.get("blockers", []) if isinstance(summary.get("blockers"), list) else []
    warnings = summary.get("warnings", []) if isinstance(summary.get("warnings"), list) else []
    lines = [
        "## 4. 交接包校验",
        "",
        f"- 校验文件：`{normalize_path(path) if path else 'unknown'}`",
        f"- handoff_ready：`{bool(summary.get('handoff_ready'))}`。",
        f"- next_action：{summary.get('next_action') or 'none'}",
        "",
    ]
    if blockers:
        lines.append("| gate | blockers |")
        lines.append("| --- | --- |")
        for item in blockers:
            if isinstance(item, dict):
                lines.append(f"| `{item.get('gate', 'unknown')}` | {format_code_list(item.get('blockers', []))} |")
        lines.append("")
    if warnings:
        lines.append(f"- warnings：`{len(warnings)}` 条。")
        lines.append("")
    return lines


def section_deployment_guard(path: Path | None, payload: dict[str, Any]) -> list[str]:
    if not payload:
        return [
            "## 5. 部署门禁",
            "",
            "- 尚未生成 deployment guard。生产启动前必须运行 `python scripts\\check_pose_deployment_guard.py`，否则等于允许未验证姿态配置裸奔。",
            "",
        ]
    summary = summary_of(payload)
    blockers = summary.get("blockers", []) if isinstance(summary.get("blockers"), list) else []
    warnings = summary.get("warnings", []) if isinstance(summary.get("warnings"), list) else []
    metrics = payload.get("checks", {}).get("evidence_package", {}).get("metrics", {}) if isinstance(payload.get("checks"), dict) else {}
    lines = [
        "## 5. 部署门禁",
        "",
        f"- 校验文件：`{normalize_path(path) if path else 'unknown'}`",
        f"- deployment_allowed：`{bool(summary.get('deployment_allowed'))}`。",
        f"- active/evidence provider：`{metrics.get('active_pose_provider', 'unknown')}` / `{metrics.get('evidence_pose_provider', 'unknown')}`。",
        f"- active/evidence model：`{metrics.get('active_pose_model', 'unknown')}` / `{metrics.get('evidence_pose_model', 'unknown')}`。",
        f"- next_action：{summary.get('next_action') or 'none'}",
        "- `scripts\\start_current_camera.py` 在姿态开启且主系统告警开启时会自动执行该门禁；未通过会拒绝启动服务。",
        "- `app\\main.py` 的 FastAPI lifespan 也已接入同一套 deployment guard；直接 `uvicorn app.main:app` 也不能绕过姿态生产门禁。",
        "- `scripts\\start_phase5_test.py` 这类旧测试启动栈也已禁止回到 `POSE_RESULT_TTL_MS=500`、`POSE_MAX_FRAME_AGE_MS=500` 的脆弱默认。",
        "- 部署门禁会比对 `.env` 实际启动的 pose provider/model 和 evidence package 中通过 readiness/model quality 的 provider/model；过审一套、启动另一套会被拦。",
        "- 只有本地排查才允许显式使用 `--skip-pose-deployment-guard`，生产启动禁止使用这个绕过参数。",
        "",
    ]
    if blockers:
        lines.append("| gate | blockers |")
        lines.append("| --- | --- |")
        for item in blockers:
            if isinstance(item, dict):
                lines.append(f"| `{item.get('gate', 'unknown')}` | {format_code_list(item.get('blockers', []))} |")
        lines.append("")
    if warnings:
        lines.append("| gate | warnings |")
        lines.append("| --- | --- |")
        for item in warnings:
            if isinstance(item, dict):
                lines.append(f"| `{item.get('gate', 'unknown')}` | {format_code_list(item.get('warnings', []))} |")
        lines.append("")
    return lines


def section_launch_safety(path: Path | None, payload: dict[str, Any]) -> list[str]:
    if not payload:
        return [
            "## 6. 启动入口安全审计",
            "",
            "- 尚未生成 launch safety check。请运行 `python scripts\\check_pose_launch_safety.py`，确认没有启动脚本绕开姿态部署门禁。",
            "",
        ]
    summary = summary_of(payload)
    blockers = summary.get("blockers", []) if isinstance(summary.get("blockers"), list) else []
    warnings = summary.get("warnings", []) if isinstance(summary.get("warnings"), list) else []
    lines = [
        "## 6. 启动入口安全审计",
        "",
        f"- 校验文件：`{normalize_path(path) if path else 'unknown'}`",
        f"- launch_safety_passed：`{bool(summary.get('launch_safety_passed'))}`。",
        f"- next_action：{summary.get('next_action') or 'none'}",
        "",
    ]
    if blockers:
        lines.append("| script | blockers |")
        lines.append("| --- | --- |")
        for item in blockers:
            if isinstance(item, dict):
                lines.append(f"| `{item.get('script', 'unknown')}` | {format_code_list(item.get('blockers', []))} |")
        lines.append("")
    if warnings:
        lines.append("| script | warnings |")
        lines.append("| --- | --- |")
        for item in warnings:
            if isinstance(item, dict):
                lines.append(f"| `{item.get('script', 'unknown')}` | {format_code_list(item.get('warnings', []))} |")
        lines.append("")
    return lines


def section_promotion_gate(path: Path | None, payload: dict[str, Any]) -> list[str]:
    if not payload:
        return [
            "## 7. 生产推广总门禁",
            "",
            "- 尚未生成 promotion gate。请运行 `python scripts\\check_pose_promotion_gate.py`，不要只看单个子门禁就宣布姿态可上线。",
            "",
        ]
    summary = summary_of(payload)
    blockers = summary.get("blockers", []) if isinstance(summary.get("blockers"), list) else []
    warnings = summary.get("warnings", []) if isinstance(summary.get("warnings"), list) else []
    lines = [
        "## 7. 生产推广总门禁",
        "",
        f"- 校验文件：`{normalize_path(path) if path else 'unknown'}`",
        f"- promotion_allowed：`{bool(summary.get('promotion_allowed'))}`。",
        f"- next_action：{summary.get('next_action') or 'none'}",
        "",
    ]
    if blockers:
        lines.append("| gate | blockers |")
        lines.append("| --- | --- |")
        for item in blockers:
            if isinstance(item, dict):
                lines.append(f"| `{item.get('gate', 'unknown')}` | {format_code_list(item.get('blockers', []))} |")
        lines.append("")
    if warnings:
        lines.append(f"- warnings：`{len(warnings)}` 组，详见 `{normalize_path(path) if path else 'promotion gate JSON'}`。")
        lines.append("")
    return lines


def section_production_blockers(preflight: dict[str, Any], production_pipeline: dict[str, Any]) -> list[str]:
    blockers = preflight_blockers(preflight)
    pipeline_summary = summary_of(production_pipeline)
    lines = ["## 8. 生产阻塞项", ""]
    if blockers:
        lines.append("| gate | blocker | 影响 |")
        lines.append("| --- | --- | --- |")
        for blocker in blockers:
            lines.append(
                f"| `{blocker.get('gate', 'unknown')}` | `{blocker.get('blocker', 'unknown')}` | {blocker_impact(blocker.get('blocker'))} |"
            )
    else:
        lines.append("- 未在预检中看到 blocker；仍需检查生产流水线 readiness 是否真正通过。")
    lines.append("")
    lines.append(
        f"生产流水线只完成 `{pipeline_summary.get('completed_stage_count', 0)}/{pipeline_summary.get('stage_count', 0)}` 个阶段，"
        f"跳过 `{pipeline_summary.get('skipped_stage_count', 0)}` 个阶段，"
        f"失败在 `{pipeline_summary.get('failed_stage') or 'none'}`。这意味着完整 runtime/provider/temporal/LSTM 生产证据尚未生成。"
    )
    lines.append("")
    return lines


def section_dev_smoke_findings(dev_readiness: dict[str, Any], dev_comparison: dict[str, Any]) -> list[str]:
    readiness_summary = summary_of(dev_readiness)
    checks = dev_readiness.get("checks") if isinstance(dev_readiness.get("checks"), dict) else {}
    temporal_metrics = nested(checks, "temporal_data", "metrics")
    model_quality = nested(checks, "model_quality", "metrics")
    provider_check = checks.get("provider") if isinstance(checks.get("provider"), dict) else {}
    provider_metrics = provider_check.get("metrics") if isinstance(provider_check.get("metrics"), dict) else {}
    provider_candidates = provider_metrics.get("candidates") if isinstance(provider_metrics.get("candidates"), list) else []
    provider_sampled_frames = max(
        [int(item.get("sampled_frames", 0)) for item in provider_candidates if isinstance(item, dict)] or [0]
    )
    provider_attempts = max(
        [int(item.get("inference_attempt_count", 0)) for item in provider_candidates if isinstance(item, dict)] or [0]
    )
    comparison = summary_of(dev_comparison)
    baseline = comparison.get("baseline_lstm", {})
    pose = comparison.get("pose_lstm", {})
    ablation = comparison.get("pose_lstm_zero_pose_ablation", {})
    manifest = comparison.get("lstm_manifest", {}) if isinstance(comparison.get("lstm_manifest"), dict) else {}
    compare = comparison.get("comparison", {})
    lines = [
        "## 9. 开发冒烟发现",
        "",
        "- 好消息：开发冒烟证明字段链路能跑通，pose-aware temporal 数据里确实出现了 `pose_available=true` 的行。",
        "- 坏消息：这点不能自嗨。LSTM 对照里 pose LSTM、baseline、zero-pose ablation 指标完全一样，说明姿态特征目前没有贡献。",
        "",
        "| 指标 | bbox+motion baseline | bbox+motion+pose LSTM | zero-pose ablation |",
        "| --- | ---: | ---: | ---: |",
        f"| F1 | {fmt_metric(baseline.get('f1'))} | {fmt_metric(pose.get('f1'))} | {fmt_metric(ablation.get('f1'))} |",
        f"| FP | {fmt_metric(baseline.get('false_positive_count'))} | {fmt_metric(pose.get('false_positive_count'))} | {fmt_metric(ablation.get('false_positive_count'))} |",
        f"| Precision | {fmt_metric(baseline.get('precision'))} | {fmt_metric(pose.get('precision'))} | {fmt_metric(ablation.get('precision'))} |",
        f"| Recall | {fmt_metric(baseline.get('recall'))} | {fmt_metric(pose.get('recall'))} | {fmt_metric(ablation.get('recall'))} |",
        "",
        f"- LSTM 对照 blocker：{format_code_list(compare.get('blockers', []))}",
        f"- dev readiness failed gates：{format_code_list(readiness_summary.get('failed_gates', []))}",
        f"- temporal pose_available_true_ratio：`{fmt_metric(temporal_metrics.get('pose_available_true_ratio'))}`。",
        f"- model quality：`passed={bool(model_quality.get('passed'))}`，当前校验模型是 `{model_quality.get('configured_model', 'unknown')}`；这次不是拿 yolo11s 候选冒充生产增强。",
        f"- provider A/B：`passed={bool(provider_check.get('passed'))}`，设备是 `{provider_metrics.get('device', 'unknown')}`，最大 sampled_frames=`{provider_sampled_frames}`，最大 inference_attempts=`{provider_attempts}`；CPU 小样本跑得动，不等于生产性能合格。",
        f"- LSTM manifest hash：`{manifest.get('sha256', 'unknown')}`。",
        f"- metrics input manifest 对齐：`{bool(manifest.get('metric_manifest_sha256s_match_manifest'))}`；pose/zero-pose train_config manifest 对齐：`{bool(manifest.get('pose_train_config_manifest_sha256s_match_manifest'))}`。",
        "",
        "解释：姿态数据进入 LSTM，不等于姿态融合有效。zero-pose ablation 一样好，基本就是在告诉我们：当前时序模型还没学会用骨架，或者骨架信息质量/覆盖/标签对齐还不足以带来增益。",
        "换句话说，dev-smoke 这次的价值是证明证据链不再散装，坏处是也证明姿态特征现在还没给 LSTM 带来实际收益。别把它包装成效果提升，那会很丢人。",
        "",
    ]
    return lines


def section_commands(
    production_dry_run: dict[str, Any],
    dev_smoke_dry_run: dict[str, Any],
    dev_live_dry_run: dict[str, Any],
) -> list[str]:
    lines = [
        "## 10. 生产机执行顺序",
        "",
        "先在有 CUDA、服务已启动、`/api/v1/status` 能访问的机器上跑预检：",
        "",
        "```powershell",
        "python scripts\\check_pose_production_preflight.py --base-url http://127.0.0.1:8000/api/v1 --camera-id camera_01 --device cuda:0 --duration-seconds 120 --labels data\\phase7_labels\\phase7_video_labels.jsonl --temporal-output-dir data\\temporal_sequences_pose_v1 --lstm-eval-split test --output evaluations\\pose_production_preflight_20260705.json",
        "```",
        "",
        "预检通过后，先卡当前接入姿态模型本身的质量：",
        "",
        "```powershell",
        "python scripts\\check_pose_model_quality.py --metrics models\\pose_yolo_batch001_003_yolo11s_metrics.json --configured-model yolo11n-pose.pt --output evaluations\\pose_model_quality_20260705.json",
        "python scripts\\check_pose_model_quality.py --metrics models\\pose_yolo_batch001_003_yolo11s_metrics.json --configured-model models\\pose_yolo_batch001_003_yolo11s_best.pt --output evaluations\\pose_model_quality_yolo11s_candidate_20260705.json",
        "```",
        "",
        "预检过了再跑完整生产流水线：",
        "",
        "```powershell",
        "python scripts\\run_pose_optimization_pipeline.py --mode production --device cuda:0 --duration-seconds 120 --lstm-eval-split test --summary evaluations\\pose_optimization_pipeline_20260705.json",
        "```",
        "",
        "默认不传 `--configured-pose-model` 时，production pipeline 会读取 `.env` 当前 `POSE_PROVIDER` 对应的姿态模型路径；如果要诊断候选模型，必须显式传入 `--configured-pose-model`，别让质量门检查一套、服务启动另一套。",
        "",
        "这条 production pipeline 会在非 dry-run 模式下自动生成并回填后置门禁：`pose_evidence_package_check_20260705.json`、`pose_deployment_guard_20260705.json`、`pose_launch_safety_check_20260705.json`、`pose_promotion_gate_20260705.json`。",
        "证据包还会检查每个 `status=ok` stage 的 `output` 文件是否真实存在，并要求产物修改时间不早于该 stage 的 `started_at`，防止命令返回 0 但证据文件没落盘，或拿旧 JSON 冒充本轮新证据。",
        "生产模式退出码也受 `promotion_allowed` 约束；stage 全部跑完但总门禁没过，自动化仍应看到非零退出码。",
        "",
        "本机只能跑开发冒烟，命令如下；它可以帮助定位链路，但不能拿去做上线背书：",
        "",
        "```powershell",
        "python scripts\\run_pose_optimization_pipeline.py --mode dev-smoke --summary evaluations\\pose_optimization_pipeline_dev_smoke_20260705.json",
        "```",
        "",
        "生产机跑完后，用这条命令检查证据包能不能交接：",
        "",
        "```powershell",
        "python scripts\\check_pose_evidence_package.py --output evaluations\\pose_evidence_package_check_20260705.json",
        "```",
        "",
        "正式启动服务前，再跑部署门禁：",
        "",
        "```powershell",
        "python scripts\\check_pose_deployment_guard.py --env-file .env --evidence-package evaluations\\pose_evidence_package_check_20260705.json --output evaluations\\pose_deployment_guard_20260705.json",
        "```",
        "",
        "再跑启动入口安全审计，确认没有其他脚本绕过门禁或退回脆弱姿态参数：",
        "",
        "```powershell",
        "python scripts\\check_pose_launch_safety.py --output evaluations\\pose_launch_safety_check_20260705.json",
        "```",
        "",
        "最后跑生产推广总门禁，只有它通过才允许进入受控生产推广：",
        "",
        "```powershell",
        "python scripts\\check_pose_promotion_gate.py --output evaluations\\pose_promotion_gate_20260705.json",
        "```",
        "",
        "使用当前摄像头启动脚本时，若姿态和主系统告警同时开启，脚本会自动执行同一套部署门禁；门禁不过会直接拒绝启动：",
        "",
        "```powershell",
        "python scripts\\start_current_camera.py --enable-pose --enable-main-system-alerts",
        "```",
        "",
    ]
    lines.extend(planned_stage_summary("production dry-run", production_dry_run))
    lines.extend(planned_stage_summary("dev-smoke dry-run", dev_smoke_dry_run))
    lines.extend(planned_stage_summary("dev-live dry-run", dev_live_dry_run))
    return lines


def section_acceptance_rules() -> list[str]:
    return [
        "## 11. 验收口径",
        "",
        "- 生产预检必须 `passed=true`，否则别往下谈。",
        "- 生产预检必须检查 `.env` active pose provider/model/device；模型文件不存在、pose 被关闭、active device 不是 CUDA，后面的 runtime/provider/LSTM 讨论都先闭嘴。",
        "- live `/status` 里的 `pose_provider` 和 `pose_model_path` 必须匹配 `.env` active 配置；服务跑旧配置但接口还活着，这种假健康不能放过。",
        "- 交接包里的 preflight、model quality、temporal pose check、LSTM manifest、LSTM comparison、readiness 必须是同一轮 production pipeline 对应 stage 的 `output`；拿旧 JSON 拼包就是证据污染。",
        "- production pipeline 的模型质量门默认必须跟随 `.env` 当前 `POSE_PROVIDER` 的 active model；显式覆盖只用于候选诊断，不能让启动配置和质量证据各查各的。",
        "- evidence package 不能只相信 readiness summary 自称 ready；readiness 里必须带 runtime pose provider/model、provider device、passing providers、provider model paths、configured model，并且这些字段必须互相对齐。",
        "- 当前接入姿态模型必须通过 model quality gate；pose mAP50-95 低于 baseline 的候选，即使更快，也不能作为生产增强证据。",
        "- deployment guard 必须确认 `.env` 的 `POSE_PROVIDER` 与 handoff evidence 里的 runtime pose provider 一致；模型一致但 provider 换了，仍然是证据污染。",
        "- FastAPI 服务本体启动时也必须执行 deployment guard；只保护启动脚本、不保护 `app.main`，就等于给直接 uvicorn 留后门。",
        "- runtime 必须是真实 FastAPI 服务证据，不是 replay、mock、local smoke。",
        "- provider A/B 必须在 CUDA 上跑，CPU 结果只能说明代码能跑，不能说明生产性能。",
        "- provider A/B 不能只看 `pose_valid_rate`；采样帧数、姿态推理次数、平均延迟、骨架平均置信度也必须过线，否则就是小样本自嗨或慢吞吞的漂亮废物。",
        "- runtime、provider A/B、model quality 必须描述同一套姿态配置；runtime 里缺 `pose_provider`，或者 runtime 使用的 provider 没有通过 provider A/B，都只能算半截证据。",
        "- runtime probe 里的 `pose_model_path` 必须和 model quality 的 `configured_model` 一致；只匹配 provider 不够，模型文件不一致就是两套证据在互相冒充。",
        "- provider A/B 的 `provider_model_paths` 也必须和 model quality 的 `configured_model` 对齐；否则 A/B 性能是在测另一套模型。",
        "- pose-aware temporal 数据必须通过 pose gate，尤其要看 `pose_available_true_ratio`、`known_pose_quality_ratio`、`pose_track_mismatch`，以及可用骨架行是否带 `pose_runtime.pose_provider` 和 `pose_runtime.pose_model_path`。",
        "- `--require-pose` 的 LSTM manifest 也必须二次检查可用骨架行的 `pose_runtime.pose_provider` 和 `pose_runtime.pose_model_path`；时序检查被绕过时，manifest 不能继续把脏骨架喂给训练。",
        "- LSTM comparison 必须记录 `lstm_manifest.sha256`、`schema_hashes`、`pose_provider_counts`、`pose_model_path_counts`，并确认 metrics 的 `input_files` 与 manifest 一致，三份 metrics 自报的 `input_manifest.sha256` 必须等于 comparison 传入的 manifest，pose/zero-pose metrics 的 `train_config.input_manifest_sha256` 也必须等于同一份 manifest；否则指标漂亮也只是来源不明的散装数字。",
        "- pose-aware temporal 生产证据不能是几十行单数据集冒烟样本；至少要覆盖 `ur_fall`、`gmdcsa24`、`fall`、`non_fall`，并达到生产级行数和可用姿态行数。",
        "- bbox+motion+pose LSTM 必须同时打赢 bbox+motion baseline 和 zero-pose ablation，且 false positive 不能变差。",
        "- LSTM readiness 不能只相信 comparison 文件自称 passed；必须独立看到 baseline、pose、zero-pose ablation 的 F1 和 false positive 证据。",
        "- `low_quality` 不能直接支持告警，`pose_track_mismatch` 要当风险证据处理。",
        "- deployment guard 必须 `deployment_allowed=true`，否则即使服务能启动，也不准把姿态链路当生产能力宣传。",
        "- 生产启动不得使用 `--skip-pose-deployment-guard`；用了这个参数，启动结果只能算本地排查，不能算上线证据。",
        "- launch safety 必须无 blocker；debug 启动脚本允许 warning，但其输出不能作为生产证据。",
        "- promotion gate 必须 `promotion_allowed=true`；只通过 launch safety 或只通过 deployment guard 都不算姿态生产完成。",
        "",
    ]


def section_next_steps() -> list[str]:
    return [
        "## 12. 下一步计划",
        "",
        "1. 在 CUDA 生产候选机启动真实服务，先跑 production preflight，消掉 `cuda_unavailable` 和 `live_status_unreachable`。",
        "2. 跑完整 production pipeline，生成 runtime、provider、temporal、LSTM、readiness 全套 JSON。",
        "3. 如果 runtime 仍低于门槛，优先查 TTL、frame stale、busy lock、tracking frame delta，不要急着重训模型。",
        "4. 如果 runtime 稳定但 LSTM 对照仍打不赢 zero-pose ablation，再回到数据质量、骨架特征表达、标签对齐和模型结构。",
        "5. 只有生产 readiness 给出 `production_ready=true`，才允许讨论上线；在此之前，所有“效果变好了”的说法都算嘴硬。",
        "",
    ]


def planned_stage_summary(name: str, payload: dict[str, Any]) -> list[str]:
    if not payload:
        return []
    stages = payload.get("stages") if isinstance(payload.get("stages"), list) else []
    if not stages:
        return []
    lines = [f"{name} 计划阶段："]
    for item in stages:
        if isinstance(item, dict):
            lines.append(f"- `{item.get('name', 'unknown')}` -> `{item.get('output', '')}`")
    lines.append("")
    return lines


def blocker_impact(blocker: Any) -> str:
    text = str(blocker or "")
    mapping = {
        "cuda_unavailable": "当前机器无法证明生产性能，CPU 证据只能用于开发定位。",
        "live_status_unreachable": "真实服务未连通，runtime pose_valid_rate、TTL、publisher 行为都没有生产证据。",
        "production_device_is_not_cuda": "生产 provider 选择不能基于非 CUDA 设备。",
        "live_status_pose_section_missing": "服务状态没有暴露姿态诊断，下游无法排查骨架链路。",
    }
    if text in mapping:
        return mapping[text]
    if text.startswith("required_file_missing"):
        return "基础模型/标签/阈值文件不完整，后续评估会变成空转。"
    if text.startswith("missing_python_dependency"):
        return "运行环境缺依赖，训练或 ONNX 评估会直接断。"
    return "必须先消除，否则生产结论不可信。"


def preflight_blockers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = summary_of(payload).get("blockers", [])
    return [item for item in blockers if isinstance(item, dict)]


def summary_of(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    return summary if isinstance(summary, dict) else {}


def nested(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def fmt_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    try:
        return f"{float(value):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def format_code_list(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return "`none`"
    return ", ".join(f"`{item}`" for item in values)


def normalize_path(path: Path) -> str:
    return str(path).replace("/", "\\")


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = resolve_path(path)
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
