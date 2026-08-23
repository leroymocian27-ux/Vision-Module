# LAN Alert Setup

This project can post confirmed fall alerts to another server on the same LAN.

## Required Settings

Edit [../.env](D:/Program/vision_service/.env:1) and confirm these values:

```text
MAIN_SYSTEM_ALERT_ENABLED=true
MAIN_SYSTEM_BASE_URL=http://<target-server-ip>:8000/api/v1
MAIN_SYSTEM_FALL_EVENT_PATH=/video-bridge/fall-events
VISION_SERVICE_PUBLIC_BASE_URL=http://<this-vision-pc-ip>:8000
```

Current local vision host confirmed during setup:

```text
VISION_SERVICE_PUBLIC_BASE_URL=http://192.168.8.253:8000
```

Current verified main-system receiver:

```text
MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000/api/v1
```

The vision service PC is `192.168.8.253`; the main-system receiver is `192.168.8.254`.

## Start Services

Run the vision service on all interfaces so other LAN devices can reach snapshots:

```powershell
cd D:\Program\vision_service
D:\Anaconda\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

If you use the standalone identity service, start it the same way:

```powershell
cd D:\Program\vision_service\identity_service
D:\Anaconda\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8100
```

## Firewall

Open inbound access at least for:

```text
8000/tcp  vision_service
8100/tcp  identity_service if used remotely
```

The target alert receiver must also allow inbound access on its backend port, currently `8000/tcp`.

## What Happens

- `vision_service` sends confirmed-fall JSON to `MAIN_SYSTEM_BASE_URL + MAIN_SYSTEM_FALL_EVENT_PATH`
- the payload includes a `snapshot_url`
- other LAN machines can load that snapshot only if `VISION_SERVICE_PUBLIC_BASE_URL` points to this PC's LAN IP and port `8000`

## Smoke Test

After the receiver is online, test its endpoint directly:

```powershell
cd D:\Program\vision_service
python scripts\post_test_fall_event.py --main-system-base-url http://192.168.8.254:8000/api/v1
```
