"""Models for iGuardStove integration events and device data."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class StoveEventType(StrEnum):
    """Stove event types exposed by Home Assistant."""

    ACTIVITY_SEEN = "activity_seen"
    NIGHT_LOCK_ON = "night_lock_on"
    NIGHT_LOCK_OFF = "night_lock_off"
    STOVE_ON = "stove_on"
    STOVE_OFF = "stove_off"
    MOTION_AUTO_RESUMED = "motion_auto_resumed"
    AUTO_SHUT_OFF = "auto_shut_off"
    EMERGENCY_BUTTON = "emergency_button"
    TEMPERATURE_ALERT = "temperature_alert"
    LOST_COMMUNICATION = "lost_communication"
    BYPASSED = "bypassed"
    NO_ACTIVITY_GRACE_PERIOD = "no_activity_grace_period"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StoveEvent:
    """Dataclass representing an iGuardStove activity event."""

    occurred_at: datetime
    event_type: StoveEventType
    raw_label: str
    duplicate_ordinal: int = 0
