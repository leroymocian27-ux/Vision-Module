from __future__ import annotations

import io
import struct
from dataclasses import dataclass


MAGIC = b"VSF1"
VERSION = 1
HEADER_STRUCT = struct.Struct("<4sHHQQHHI")
HEADER_LEN = HEADER_STRUCT.size


@dataclass(frozen=True)
class CaptureFramePacket:
    seq: int
    timestamp_ms: int
    width: int
    height: int
    payload: bytes


class CaptureProtocolError(RuntimeError):
    pass


def pack_frame(
    *,
    seq: int,
    timestamp_ms: int,
    width: int,
    height: int,
    payload: bytes,
) -> bytes:
    header = HEADER_STRUCT.pack(
        MAGIC,
        VERSION,
        HEADER_LEN,
        seq,
        timestamp_ms,
        width,
        height,
        len(payload),
    )
    return header + payload


def read_frame_packet(stream: io.BufferedReader) -> CaptureFramePacket:
    header = _read_exact(stream, HEADER_LEN)
    if not header:
        raise EOFError("capture stream closed")
    magic, version, header_len, seq, timestamp_ms, width, height, payload_len = HEADER_STRUCT.unpack(header)
    if magic != MAGIC:
        raise CaptureProtocolError("invalid capture packet magic")
    if version != VERSION:
        raise CaptureProtocolError(f"unsupported capture packet version: {version}")
    if header_len != HEADER_LEN:
        raise CaptureProtocolError(f"invalid capture packet header length: {header_len}")
    if payload_len <= 0:
        raise CaptureProtocolError(f"invalid capture packet payload length: {payload_len}")
    payload = _read_exact(stream, payload_len)
    if len(payload) != payload_len:
        raise EOFError("capture stream closed while reading payload")
    return CaptureFramePacket(
        seq=seq,
        timestamp_ms=timestamp_ms,
        width=width,
        height=height,
        payload=payload,
    )


def _read_exact(stream: io.BufferedReader, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            if chunks:
                return b"".join(chunks)
            return b""
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
