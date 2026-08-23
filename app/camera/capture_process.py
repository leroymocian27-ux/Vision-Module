from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass

import cv2

from app.camera.capture_process_protocol import pack_frame


@dataclass(frozen=True)
class CaptureProcessConfig:
    backend: str
    rtsp_url: str
    output_height: int
    jpeg_quality: int
    write_fps: float
    buffersize: int
    open_timeout_ms: int
    read_timeout_ms: int


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _resize_to_height(frame, output_height: int):
    if output_height <= 0:
        return frame
    height, width = frame.shape[:2]
    if height <= output_height:
        return frame
    scale = output_height / height
    new_width = max(1, int(width * scale))
    return cv2.resize(frame, (new_width, output_height), interpolation=cv2.INTER_AREA)


def _capture_loop(
    config: CaptureProcessConfig,
    stop_event: threading.Event,
    latest_queue: queue.Queue[tuple[int, int, int, int, bytes]],
) -> None:
    if config.backend == "subprocess_pyav":
        _capture_loop_pyav(config, stop_event, latest_queue)
        return
    _capture_loop_opencv(config, stop_event, latest_queue)


def _capture_loop_opencv(
    config: CaptureProcessConfig,
    stop_event: threading.Event,
    latest_queue: queue.Queue[tuple[int, int, int, int, bytes]],
) -> None:
    cap = cv2.VideoCapture(config.rtsp_url, cv2.CAP_FFMPEG)
    if config.buffersize > 0:
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, config.buffersize)
        except Exception:
            pass
    try:
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, max(config.open_timeout_ms, 1))
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, max(config.read_timeout_ms, 1))
    except Exception:
        pass
    if not cap.isOpened():
        _log("open_failed")
        stop_event.set()
        return

    seq = 0
    last_ok_at = time.monotonic()
    consecutive_failures = 0
    try:
        while not stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                consecutive_failures += 1
                elapsed_ms = (time.monotonic() - last_ok_at) * 1000
                if elapsed_ms >= max(config.read_timeout_ms, 1):
                    _log(f"read_timeout:consecutive_failures={consecutive_failures}")
                    stop_event.set()
                    return
                time.sleep(0.03)
                continue
            consecutive_failures = 0
            last_ok_at = time.monotonic()
            seq = _encode_and_enqueue(config, latest_queue, frame, seq)
    finally:
        cap.release()


def _capture_loop_pyav(
    config: CaptureProcessConfig,
    stop_event: threading.Event,
    latest_queue: queue.Queue[tuple[int, int, int, int, bytes]],
) -> None:
    import av

    container = None
    stream = None
    seq = 0
    has_frame = False
    stage = "open"
    try:
        container = av.open(
            config.rtsp_url,
            mode="r",
            options={
                "rtsp_transport": "tcp",
                "fflags": "nobuffer",
                "flags": "low_delay",
            },
            timeout=(
                max(config.open_timeout_ms, 1) / 1000,
                max(config.read_timeout_ms, 1) / 1000,
            ),
        )
        stream = next((item for item in container.streams if item.type == "video"), None)
        if stream is None:
            _log("open_failed:no_video_stream")
            stop_event.set()
            return
        stream.thread_type = "AUTO"
        stage = "decode"
        for frame in container.decode(stream):
            if stop_event.is_set():
                return
            image = frame.to_ndarray(format="bgr24")
            seq = _encode_and_enqueue(config, latest_queue, image, seq)
            has_frame = True
        _log("stream_closed")
        stop_event.set()
    except Exception as exc:
        text = str(exc).lower()
        if stage == "open":
            _log(f"open_failed:{exc}")
        elif not has_frame:
            if "timeout" in text:
                _log(f"first_frame_timeout:{exc}")
            else:
                _log(f"open_failed:{exc}")
        elif "timeout" in text:
            _log(f"read_timeout:{exc}")
        else:
            _log(f"stream_closed:{exc}")
        stop_event.set()
    finally:
        if container is not None:
            container.close()


def _encode_and_enqueue(
    config: CaptureProcessConfig,
    latest_queue: queue.Queue[tuple[int, int, int, int, bytes]],
    frame,
    seq: int,
) -> int:
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), max(1, min(100, config.jpeg_quality))]
    frame = _resize_to_height(frame, config.output_height)
    ok, encoded = cv2.imencode(".jpg", frame, encode_params)
    if not ok:
        _log("decode_failed:encode")
        return seq
    seq += 1
    height, width = frame.shape[:2]
    payload = bytes(encoded)
    item = (seq, int(time.time() * 1000), width, height, payload)
    while True:
        try:
            latest_queue.get_nowait()
        except queue.Empty:
            break
    try:
        latest_queue.put_nowait(item)
    except queue.Full:
        pass
    return seq


def _writer_loop(
    config: CaptureProcessConfig,
    stop_event: threading.Event,
    latest_queue: queue.Queue[tuple[int, int, int, int, bytes]],
) -> None:
    min_interval = 1.0 / config.write_fps if config.write_fps > 0 else 0.0
    last_written_at = 0.0
    stdout = sys.stdout.buffer
    while not stop_event.is_set():
        try:
            item = latest_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        now = time.monotonic()
        wait_for = min_interval - (now - last_written_at)
        if wait_for > 0:
            stop_event.wait(wait_for)
            if stop_event.is_set():
                return
        seq, timestamp_ms, width, height, payload = item
        packet = pack_frame(
            seq=seq,
            timestamp_ms=timestamp_ms,
            width=width,
            height=height,
            payload=payload,
        )
        try:
            stdout.write(packet)
            stdout.flush()
            last_written_at = time.monotonic()
        except BrokenPipeError:
            stop_event.set()
            return


def parse_args() -> CaptureProcessConfig:
    parser = argparse.ArgumentParser(description="RTSP capture subprocess.")
    parser.add_argument("--backend", default=os.getenv("CAPTURE_BACKEND", "subprocess_opencv"))
    parser.add_argument("--rtsp-url", required=True)
    parser.add_argument("--output-height", type=int, default=int(os.getenv("CAPTURE_PROCESS_OUTPUT_HEIGHT", "720")))
    parser.add_argument("--jpeg-quality", type=int, default=int(os.getenv("CAPTURE_JPEG_QUALITY", "60")))
    parser.add_argument("--write-fps", type=float, default=float(os.getenv("CAPTURE_PROCESS_WRITE_FPS", "10")))
    parser.add_argument("--buffersize", type=int, default=int(os.getenv("OPENCV_CAPTURE_BUFFERSIZE", "1")))
    parser.add_argument("--open-timeout-ms", type=int, default=int(os.getenv("CAPTURE_PROCESS_OPEN_TIMEOUT_MS", "5000")))
    parser.add_argument("--read-timeout-ms", type=int, default=int(os.getenv("CAPTURE_PROCESS_READ_TIMEOUT_MS", "5000")))
    args = parser.parse_args()
    return CaptureProcessConfig(
        backend=args.backend,
        rtsp_url=args.rtsp_url,
        output_height=args.output_height,
        jpeg_quality=args.jpeg_quality,
        write_fps=args.write_fps,
        buffersize=args.buffersize,
        open_timeout_ms=args.open_timeout_ms,
        read_timeout_ms=args.read_timeout_ms,
    )


def main() -> int:
    config = parse_args()
    latest_queue: queue.Queue[tuple[int, int, int, int, bytes]] = queue.Queue(maxsize=1)
    stop_event = threading.Event()
    capture_thread = threading.Thread(
        target=_capture_loop,
        args=(config, stop_event, latest_queue),
        name="capture-process-reader",
        daemon=True,
    )
    writer_thread = threading.Thread(
        target=_writer_loop,
        args=(config, stop_event, latest_queue),
        name="capture-process-writer",
        daemon=True,
    )
    capture_thread.start()
    writer_thread.start()
    while not stop_event.is_set():
        if not capture_thread.is_alive():
            stop_event.set()
            break
        stop_event.wait(0.5)
    capture_thread.join(timeout=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
