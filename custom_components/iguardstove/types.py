"""Type definitions for the iGuardStove integration."""

from typing import TypedDict


class DeviceSummary(TypedDict):
    """Summary of a discovered device on the account dashboard."""

    device_id: str
    device_name: str


class DeviceData(TypedDict, total=False):
    """Detailed status data parsed from a device page."""

    device_id: str
    device_name: str
    status_raw: str | None
    status: str | None
    is_locked: bool | None
    last_check_in: str | None
    temperature: float | None
    temperature_unit: str
    fires_prevented: int | None
