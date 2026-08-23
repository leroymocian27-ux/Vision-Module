# Phase 5 Test Launcher

Use this helper for live browser testing. It starts the standalone
`identity_service` and the main `vision_service` with the current machine's
available Python interpreter.

```powershell
cd D:\vision_service
D:\Anaconda\python.exe scripts\start_phase5_test.py
```

The script starts:

- Identity Service: `http://127.0.0.1:8100`
- Vision Service: `http://127.0.0.1:8000`
- Demo page: `http://127.0.0.1:8000/demo?v=phase53`

The demo RTSP field is prefilled with this editable template:

```text
rtsp://admin:***@192.168.8.254:554/tcp/av0_1
```

In the actual page, replace the password placeholder with the camera password
before clicking `Start`. Do not include real passwords in screenshots.

Press `Ctrl+C` in the launcher window to stop both services.
