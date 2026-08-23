from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import cv2


def _mask_url(url: str) -> str:
    return re.sub(r"(rtsp://[^:]+:)[^@]+(@)", r"\1***\2", url)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/probe_rtsp_opencv.py <rtsp-url> [output.jpg]")
        return 2

    url = sys.argv[1]
    output = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("rtsp_opencv_probe.jpg")
    output.parent.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        "rtsp_transport;tcp|stimeout;5000000|max_delay;500000",
    )

    print("OpenCV:", cv2.__version__)
    print("URL:", _mask_url(url))
    print("OPENCV_FFMPEG_CAPTURE_OPTIONS:", os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS"))

    started = time.perf_counter()
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    print("open_elapsed_ms:", round((time.perf_counter() - started) * 1000, 2))

    if not cap.isOpened():
        print("FAILED: cap.isOpened() == False")
        cap.release()
        return 2

    for i in range(60):
        ok, frame = cap.read()
        shape = None if frame is None else frame.shape
        print(i, ok, shape)
        if ok and frame is not None:
            cv2.imwrite(str(output), frame)
            print("SAVED:", output)
            cap.release()
            return 0
        time.sleep(0.1)

    print("FAILED: opened but no readable frame")
    cap.release()
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
