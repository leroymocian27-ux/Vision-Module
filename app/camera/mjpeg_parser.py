from __future__ import annotations


JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


def extract_jpeg_frames(buffer: bytes | bytearray, *, max_buffer_bytes: int = 8 * 1024 * 1024) -> tuple[list[bytes], bytes]:
    """Extract complete JPEG byte frames from an MJPEG byte buffer."""
    data = bytes(buffer)
    frames: list[bytes] = []
    while data:
        start = data.find(JPEG_SOI)
        if start < 0:
            return frames, data[-2:] if len(data) > 2 else data
        if start > 0:
            data = data[start:]
        end = data.find(JPEG_EOI, len(JPEG_SOI))
        if end < 0:
            if len(data) > max_buffer_bytes:
                data = data[-max_buffer_bytes:]
            return frames, data
        frame_end = end + len(JPEG_EOI)
        frames.append(data[:frame_end])
        data = data[frame_end:]
    return frames, b""


def jpeg_dimensions(jpeg_bytes: bytes) -> tuple[int | None, int | None]:
    """Return JPEG width/height from SOF markers without full image decoding."""
    if not jpeg_bytes.startswith(JPEG_SOI):
        return None, None
    index = 2
    length = len(jpeg_bytes)
    while index + 9 < length:
        if jpeg_bytes[index] != 0xFF:
            index += 1
            continue
        while index < length and jpeg_bytes[index] == 0xFF:
            index += 1
        if index >= length:
            return None, None
        marker = jpeg_bytes[index]
        index += 1
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            return None, None
        if index + 2 > length:
            return None, None
        segment_length = int.from_bytes(jpeg_bytes[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > length:
            return None, None
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length < 7:
                return None, None
            height = int.from_bytes(jpeg_bytes[index + 3:index + 5], "big")
            width = int.from_bytes(jpeg_bytes[index + 5:index + 7], "big")
            return width, height
        index += segment_length
    return None, None
