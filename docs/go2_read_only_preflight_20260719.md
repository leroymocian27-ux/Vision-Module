# Go2 只读门禁预检

```text
gate_name: GO2_READ_ONLY_READY
gate_status: BLOCKED
evidence_type: CODE_ONLY + local filesystem preflight
```

执行：

```powershell
.\.venv\Scripts\python.exe scripts\check_go2_readiness.py --json
```

结果：

```text
MISSING_APPROVE_GO2_READ_ONLY
GO2_DEVELOPMENT_ROOT_NOT_FOUND
network_probe_executed=false
dds_probe_executed=false
motion_commands_sent=0
```

脚本仅检查本机目录和显式批准标志；它不会 ping、发送 UDP/DDS、导入 Unitree SDK、启动 ROS2 或控制机器狗。

解除阻断后，下一允许动作只是网络/DDS **只读** 诊断，仍禁止控制。
