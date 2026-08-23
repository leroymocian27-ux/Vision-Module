from pathlib import Path

from scripts.check_go2_readiness import evaluate


def test_missing_approval_and_sdk_root_block_read_only_gate(tmp_path: Path) -> None:
    result = evaluate(go2_root=tmp_path / "missing", approved_read_only=False)
    assert result["gate_status"] == "BLOCKED"
    assert result["network_probe_executed"] is False
    assert result["dds_probe_executed"] is False
    assert result["motion_commands_sent"] == 0
    assert set(result["blockers"]) == {"MISSING_APPROVE_GO2_READ_ONLY", "GO2_DEVELOPMENT_ROOT_NOT_FOUND"}


def test_approved_local_sdk_layout_is_ready_only_for_next_read_only_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "unitree_sdk2py").mkdir()
    result = evaluate(go2_root=tmp_path, approved_read_only=True)
    assert result["gate_status"] == "PASS"
    assert result["next_allowed_action"] == "read-only network and DDS diagnostics"
