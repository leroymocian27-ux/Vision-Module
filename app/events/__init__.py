"""Event-semantic pipeline primitives.

This package is intentionally isolated from the realtime detection path until
the feature-flagged integration phase.
"""

from app.events.incident_manager import IncidentManager, IncidentResolution
from app.events.outbox import EventOutbox

__all__ = ["EventOutbox", "IncidentManager", "IncidentResolution"]
