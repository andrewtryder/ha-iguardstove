"""Type definitions for the iGuardStove integration."""

from typing import NotRequired, Required, TypedDict

from .models import StoveEvent


class DeviceSummary(TypedDict):
    """Summary of a discovered device on the account dashboard."""

    device_id: str
    device_name: str


class DeviceData(TypedDict):
    """Detailed status data parsed from a device page."""

    device_id: Required[str]
    device_name: Required[str]
    status_raw: NotRequired[str | None]
    status: NotRequired[str | None]
    is_locked: NotRequired[bool | None]
    last_check_in: NotRequired[str | None]
    temperature: NotRequired[float | None]
    temperature_unit: NotRequired[str]
    fires_prevented: NotRequired[int | None]
    today_events: NotRequired[tuple[StoveEvent, ...]]
    events_error: NotRequired[str | None]
