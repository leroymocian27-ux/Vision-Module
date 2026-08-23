from __future__ import annotations

import asyncio
import uuid

from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.logger import get_logger

logger = get_logger(__name__)


class PeerManager:
    def __init__(self, settings: Settings, source_manager: CameraSourceManager) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self._peers: dict[str, object] = {}
        self._dependency_error: str | None = None

    @property
    def client_count(self) -> int:
        return len(self._peers)

    async def handle_offer(self, camera_id: str, sdp: str, type_: str) -> tuple[str, str, str]:
        runtime = self.source_manager.get_runtime(camera_id)
        if runtime is None:
            raise ValueError(f"camera {camera_id} is not running")
        deps = self._load_dependencies()
        if deps is None:
            raise ValueError(f"webrtc unavailable: {self._dependency_error}")
        RTCConfiguration = deps["RTCConfiguration"]
        RTCIceServer = deps["RTCIceServer"]
        RTCPeerConnection = deps["RTCPeerConnection"]
        RTCSessionDescription = deps["RTCSessionDescription"]
        LatestFrameVideoTrack = deps["LatestFrameVideoTrack"]

        peer_id = uuid.uuid4().hex
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(
                iceServers=[RTCIceServer(urls=[self.settings.webrtc_stun_server])]
            )
        )
        self._peers[peer_id] = pc

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            logger.info(
                "peer_connection_state peer_id=%s state=%s",
                peer_id,
                pc.connectionState,
            )
            if pc.connectionState in {"failed", "closed", "disconnected"}:
                await self.close(peer_id)

        track = LatestFrameVideoTrack(runtime.frame_buffer, self.settings).track
        pc.addTrack(track)

        offer = RTCSessionDescription(sdp=sdp, type=type_)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await self._wait_for_ice_complete(pc)
        logger.info("peer_created peer_id=%s camera_id=%s", peer_id, camera_id)
        return peer_id, pc.localDescription.sdp, pc.localDescription.type

    async def add_ice_candidate(self, peer_id: str, candidate: dict) -> None:
        pc = self._peers.get(peer_id)
        if pc is None:
            raise ValueError(f"peer not found: {peer_id}")
        deps = self._load_dependencies()
        if deps is None:
            raise ValueError(f"webrtc unavailable: {self._dependency_error}")
        rtc_candidate = self._parse_candidate(candidate)
        await pc.addIceCandidate(rtc_candidate)

    def _parse_candidate(self, candidate: dict):
        deps = self._load_dependencies()
        if deps is None:
            raise ValueError(f"webrtc unavailable: {self._dependency_error}")
        candidate_from_sdp = deps["candidate_from_sdp"]
        raw = str(candidate.get("candidate") or "").strip()
        if not raw:
            raise ValueError("candidate is required")
        if raw.startswith("candidate:"):
            raw = raw.split(":", 1)[1]
        rtc_candidate = candidate_from_sdp(raw)
        rtc_candidate.sdpMid = candidate.get("sdpMid")
        rtc_candidate.sdpMLineIndex = candidate.get("sdpMLineIndex")
        return rtc_candidate

    async def close(self, peer_id: str) -> None:
        pc = self._peers.pop(peer_id, None)
        if pc:
            await pc.close()
            logger.info("peer_closed peer_id=%s", peer_id)

    async def close_all(self) -> None:
        for peer_id in list(self._peers.keys()):
            await self.close(peer_id)

    @staticmethod
    async def _wait_for_ice_complete(pc: RTCPeerConnection, timeout_sec: float = 3.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_sec
        while pc.iceGatheringState != "complete" and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)

    def _load_dependencies(self) -> dict[str, object] | None:
        try:
            from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
            from aiortc.sdp import candidate_from_sdp
            from app.streaming.media_track import LatestFrameVideoTrack

            self._dependency_error = None
            return {
                "RTCConfiguration": RTCConfiguration,
                "RTCIceServer": RTCIceServer,
                "RTCPeerConnection": RTCPeerConnection,
                "RTCSessionDescription": RTCSessionDescription,
                "candidate_from_sdp": candidate_from_sdp,
                "LatestFrameVideoTrack": LatestFrameVideoTrack,
            }
        except Exception as exc:
            self._dependency_error = str(exc)
            logger.warning("webrtc_dependencies_unavailable error=%s", exc)
            return None
