# Remote Bridge Linkage Debug Record - 2026-06-09

## Current conclusion

The active push path from this vision-service machine to the remote main backend is working.

- Sender machine observed by remote backend: `10.12.14.29`
- Correct remote backend: `172.18.33.66:8000`
- Correct push endpoint: `POST http://172.18.33.66:8000/api/v1/video-bridge/fall-events`
- Required auth header: `X-Vision-Service-Token: <configured bridge token>`
- Current simulated push interval: `10` seconds

The previous target `172.22.144.1` should not be used for this linkage test. According to the remote-side integration guide, it is a WSL virtual NIC address and is not the LAN backend address that should receive alert pushes.

## Evidence collected on this machine

Latest continuous probe log entries show successful responses:

- `status: 200`
- `ok: true`
- response contains `accepted: true`
- response contains `pushed: true`
- response contains generated `alarm_id`
- response `alarm_type` is `fall_injury_risk`

Remote health check:

- `GET http://172.18.33.66:8000/healthz`
- Result: `200 OK`

Remote bridge status:

- `GET http://172.18.33.66:8000/api/v1/video-bridge/status`
- Result: `ok: true`
- `last_source_ip: 10.12.14.29`
- `last_promoted_at: 2026-06-09T04:35:07.342907+00:00`

This means the remote backend has received push events from this machine and promoted them into alarm flow.

## Current local probe process

The continuous simulation process is still running:

- PID: `18536`
- Script: `scripts/continuous_alert_probe.py`
- Runtime config file: `data/alert_probe_target.json`
- Log file: `logs/continuous_alert_probe.log`

Current runtime config:

```json
{
  "target_ip": "172.18.33.66",
  "port": 8000,
  "base_path": "/api/v1/video-bridge/fall-events",
  "interval": 10.0,
  "token": "<configured bridge token>"
}
```

The target can be changed without restarting the running probe:

```powershell
python scripts\set_alert_probe_target.py --target-ip <REMOTE_IP> --port 8000 --base-path /api/v1/video-bridge/fall-events --interval 10 --token <configured bridge token>
```

## Important distinction for both sides

There are two different linkage directions:

1. This machine pushes fall events to the remote backend.
2. The remote backend polls this vision-service machine.

Direction 1 is currently confirmed working.

Direction 2 is still failing on the remote side. The remote status endpoint reports that it is trying:

```text
http://10.12.14.9:8000/healthz
```

and the latest error is a connection timeout.

So the remaining issue is not the push endpoint above. It is the remote backend's polling access to this vision-service HTTP service. If polling is required, the next check should be whether this vision-service process is actually bound to a LAN-reachable address and port, for example `0.0.0.0:8000`, and whether Windows firewall or network routing allows the remote backend to reach it.

## Suggested handoff message to the remote-side engineer

Please use `172.18.33.66:8000` as the receiving backend address, not `172.22.144.1`.

The vision-service machine is now continuously sending simulated confirmed-fall events to:

```text
POST http://172.18.33.66:8000/api/v1/video-bridge/fall-events
X-Vision-Service-Token: <configured bridge token>
```

The remote backend has returned `200 OK` with `accepted: true` and `pushed: true`, and `/api/v1/video-bridge/status` shows `last_source_ip: 10.12.14.29`, so push reception is established.

If there are still failures, please separate them into:

- Push reception failure: check `/api/v1/video-bridge/fall-events`, token header, and alarm promotion.
- Reverse polling failure: check remote polling target `http://10.12.14.9:8000/healthz`, local service bind address, firewall, and route.
