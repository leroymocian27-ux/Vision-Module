from __future__ import annotations

from pydantic import BaseModel


class WebRTCOfferRequest(BaseModel):
    camera_id: str
    sdp: str
    type: str


class WebRTCOfferResponse(BaseModel):
    peer_id: str
    sdp: str
    type: str


class IceCandidateRequest(BaseModel):
    peer_id: str
    candidate: dict


class AckResponse(BaseModel):
    ok: bool
    message: str = "ack"

