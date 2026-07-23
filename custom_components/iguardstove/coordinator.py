"""DataUpdateCoordinator for iGuardStove."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import (
    CannotConnect,
    IGuardStoveClient,
    IGuardStoveException,
    InvalidAuth,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .exceptions import DashboardParseError
from .models import CoordinatorData
from .types import DeviceData, DeviceSummary

if TYPE_CHECKING:
    from .event import EventStoreManager

_LOGGER = logging.getLogger(__name__)

# Default poll interval; overridable via options (30-300s)
SCAN_INTERVAL = timedelta(seconds=60)
# Perform dynamic device discovery pass every 6 hours
DISCOVERY_INTERVAL = timedelta(hours=6)
MIN_DISCOVERY_BACKOFF = timedelta(minutes=5)
MAX_DISCOVERY_BACKOFF = timedelta(hours=6)
# Consecutive validated-empty discoveries required before removing all devices
EMPTY_DISCOVERY_CONFIRMATIONS = 3


@dataclass
class IGuardStoveData:
    """Runtime data stored in ConfigEntry.runtime_data."""

    client: IGuardStoveClient
    coordinator: "IGuardStoveDataUpdateCoordinator"
    event_store: "EventStoreManager | None" = None


type IGuardStoveConfigEntry = ConfigEntry[IGuardStoveData]


class IGuardStoveDataUpdateCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinator that polls all iGuardStove devices on a configurable interval."""

    config_entry: IGuardStoveConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: IGuardStoveClient,
        device_ids: list[str],
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.device_ids = list(device_ids)
        self._unavailable_devices: set[str] = set()
        self._pending_stale_counts: dict[str, int] = {}
        self._empty_discovery_count: int = 0
        self._last_discovery_attempt: datetime | None = None
        self._last_successful_discovery: datetime | None = None
        self._discovery_fail_count: int = 0
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    def _persist_devices(self, devices: list[DeviceSummary]) -> None:
        """Persist the discovered device list on the config entry."""
        if not hasattr(self, "config_entry") or self.config_entry is None:
            return
        entry = self.config_entry
        if self.hass.config_entries.async_get_entry(entry.entry_id) is None:
            return
        current = entry.data.get("devices", [])
        if current == devices:
            return
        self.hass.config_entries.async_update_entry(
            entry,
            data={**dict(entry.data), "devices": devices},
        )

    def _remove_devices_from_registry(self, device_ids: list[str]) -> None:
        """Detach this config entry from stale devices and drop local state."""
        if not device_ids:
            return
        _LOGGER.info(
            "Reconciling %d removed iGuardStove device(s): %s",
            len(device_ids),
            device_ids,
        )
        dev_reg = dr.async_get(self.hass)
        event_store = None
        if hasattr(self, "config_entry") and self.config_entry:
            runtime = getattr(self.config_entry, "runtime_data", None)
            if runtime is not None:
                event_store = runtime.event_store

        for did in device_ids:
            if did in self.device_ids:
                self.device_ids.remove(did)
            self._pending_stale_counts.pop(did, None)
            self._unavailable_devices.discard(did)
            if self.data and did in self.data.devices:
                self.data.devices.pop(did, None)
            if self.data and did in self.data.errors:
                self.data.errors.pop(did, None)
            if event_store is not None:
                event_store.clear_device(did)

            device_entry = dev_reg.async_get_device(identifiers={(DOMAIN, did)})
            if device_entry and hasattr(self, "config_entry") and self.config_entry:
                dev_reg.async_update_device(
                    device_entry.id,
                    remove_config_entry_id=self.config_entry.entry_id,
                )

    def _reconcile_stale_devices(
        self, discovered: list[DeviceSummary], discovered_ids: set[str]
    ) -> None:
        """Reconcile stale devices after confirmed consecutive missing passes."""
        for did in discovered_ids:
            self._pending_stale_counts.pop(did, None)

        if not discovered_ids and self.device_ids:
            self._empty_discovery_count += 1
            _LOGGER.warning(
                "Validated empty discovery (%d/%d) while %d device(s) are registered (%s)",
                self._empty_discovery_count,
                EMPTY_DISCOVERY_CONFIRMATIONS,
                len(self.device_ids),
                self.device_ids,
            )
            if self._empty_discovery_count < EMPTY_DISCOVERY_CONFIRMATIONS:
                return
            stale_all = list(self.device_ids)
            self._remove_devices_from_registry(stale_all)
            self._empty_discovery_count = 0
            self._persist_devices([])
            return

        self._empty_discovery_count = 0

        stale_candidates = [did for did in self.device_ids if did not in discovered_ids]
        stale_device_ids: list[str] = []
        for did in stale_candidates:
            count = self._pending_stale_counts.get(did, 0) + 1
            self._pending_stale_counts[did] = count
            if count >= 2:
                stale_device_ids.append(did)

        if stale_device_ids:
            self._remove_devices_from_registry(stale_device_ids)
            known_summaries = {
                d["device_id"]: d
                for d in discovered
                if d["device_id"] in self.device_ids
            }
            for did in self.device_ids:
                if did not in known_summaries:
                    known_summaries[did] = {
                        "device_id": did,
                        "device_name": f"iGuardStove {did}",
                    }
            self._persist_devices(list(known_summaries.values()))

    def _should_attempt_discovery(self, now: datetime) -> bool:
        """Check if dynamic discovery should run based on schedule or exponential backoff."""
        if (
            self._last_successful_discovery is None
            or self._last_discovery_attempt is None
        ):
            return True

        if self._discovery_fail_count == 0:
            return (now - self._last_successful_discovery) >= DISCOVERY_INTERVAL

        backoff_minutes = min(360, 5 * (2 ** (self._discovery_fail_count - 1)))
        backoff_delay = timedelta(minutes=backoff_minutes)
        return (now - self._last_discovery_attempt) >= backoff_delay

    async def async_rediscover_now(self) -> list[DeviceSummary]:
        """Run a one-shot discovery pass and persist results."""
        now = dt_util.now()
        await self._async_discover_devices(now)
        stored = self.config_entry.data.get("devices", []) if self.config_entry else []
        return list(stored) if isinstance(stored, list) else []

    async def _async_discover_devices(self, now: datetime) -> bool:
        """Perform dynamic device discovery pass with controlled backoff and exception scoping."""
        self._last_discovery_attempt = now
        try:
            discovered = await self.client.async_get_devices()
            discovered_ids = {d["device_id"] for d in discovered}

            new_device_ids = [
                d["device_id"]
                for d in discovered
                if d["device_id"] not in self.device_ids
            ]
            if new_device_ids:
                _LOGGER.info(
                    "Discovered %d new iGuardStove device(s): %s",
                    len(new_device_ids),
                    new_device_ids,
                )
                self.device_ids.extend(new_device_ids)
                if hasattr(self, "config_entry") and self.config_entry:
                    async_dispatcher_send(
                        self.hass,
                        f"{DOMAIN}_{self.config_entry.entry_id}_new_device",
                        new_device_ids,
                    )

            self._reconcile_stale_devices(discovered, discovered_ids)
            if discovered_ids:
                self._persist_devices(discovered)
            self._discovery_fail_count = 0
            self._last_successful_discovery = now
            return True
        except InvalidAuth as err:
            self._empty_discovery_count = 0
            self._discovery_fail_count += 1
            raise ConfigEntryAuthFailed(
                f"Authentication error during discovery pass: {err}"
            ) from err
        except (CannotConnect, DashboardParseError) as err:
            self._empty_discovery_count = 0
            self._discovery_fail_count += 1
            _LOGGER.warning(
                "Discovery pass failed (fail count %d): %s",
                self._discovery_fail_count,
                err,
            )
            return False

    def async_prepare_device_removal(self, device_id: str) -> bool:
        """Prepare local state for manual device removal. Return False if still active."""
        if (
            self.data
            and device_id in self.data.devices
            and device_id not in self._unavailable_devices
            and not (self.data.errors and device_id in self.data.errors)
        ):
            return False

        self._remove_devices_from_registry([device_id])
        if hasattr(self, "config_entry") and self.config_entry is not None:
            remaining: list[DeviceSummary] = [
                {
                    "device_id": str(d["device_id"]),
                    "device_name": str(d.get("device_name", d["device_id"])),
                }
                for d in self.config_entry.data.get("devices", [])
                if isinstance(d, dict)
                and isinstance(d.get("device_id"), str)
                and d.get("device_id") != device_id
            ]
            self._persist_devices(remaining)
        return True

    async def _async_update_data(self) -> CoordinatorData:
        """Fetch data for all registered devices with error isolation and discovery."""
        now = dt_util.now()

        if hasattr(self, "config_entry") and self.config_entry:
            options = self.config_entry.options
            scan_sec = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            if self.update_interval != timedelta(seconds=scan_sec):
                self.update_interval = timedelta(seconds=scan_sec)

        if self._should_attempt_discovery(now):
            await self._async_discover_devices(now)

        event_date = now.date()
        tzinfo = now.tzinfo

        devices: dict[str, DeviceData] = {}
        errors: dict[str, str] = {}
        for device_id in list(self.device_ids):
            try:
                data = await self.client.async_get_device_data(
                    device_id, event_date=event_date, tzinfo=tzinfo
                )
                devices[device_id] = data
                if device_id in self._unavailable_devices:
                    _LOGGER.info("iGuardStove %s is available again", device_id)
                    self._unavailable_devices.remove(device_id)
            except InvalidAuth as err:
                raise ConfigEntryAuthFailed(
                    f"Authentication error for {device_id}: {err}"
                ) from err
            except (CannotConnect, IGuardStoveException) as err:
                if device_id not in self._unavailable_devices:
                    _LOGGER.info("iGuardStove %s is unavailable: %s", device_id, err)
                    self._unavailable_devices.add(device_id)
                errors[device_id] = str(err)

                if self.data and device_id in self.data.devices:
                    devices[device_id] = self.data.devices[device_id]

        if len(errors) == len(self.device_ids) and self.device_ids:
            raise UpdateFailed("Failed to fetch data for all iGuardStove devices")

        return CoordinatorData(devices=devices, errors=errors)
