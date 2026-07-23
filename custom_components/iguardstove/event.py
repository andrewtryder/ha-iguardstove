"""Event platform for iGuardStove integration."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_ENABLE_ACTIVITY_EVENTS, DOMAIN
from .coordinator import (
    IGuardStoveConfigEntry,
    IGuardStoveDataUpdateCoordinator,
)
from .entity import IGuardStoveEntity
from .models import StoveEvent, StoveEventType

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_events_dedup"


def make_event_fingerprint(device_id: str, event: StoveEvent) -> str:
    """Generate a unique fingerprint string for an event occurrence."""
    norm_label = " ".join(event.raw_label.casefold().split())
    return f"{device_id}|{event.occurred_at.isoformat()}|{norm_label}|{event.duplicate_ordinal}"


class EventStoreManager:
    """Manager for persisting and synchronizing seen event fingerprints safely across devices."""

    def __init__(self, store: Store[dict[str, Any]]) -> None:
        """Initialize the event store manager."""
        self._store = store
        self._lock = asyncio.Lock()
        self._seen_events: dict[str, set[str]] = {}

    async def async_load(self) -> None:
        """Load stored fingerprints into memory safely under lock."""
        async with self._lock:
            try:
                stored_data = await self._store.async_load()
            except Exception as err:
                _LOGGER.warning("Error loading event deduplication store: %s", err)
                stored_data = None

            if isinstance(stored_data, dict) and "seen_events" in stored_data:
                raw_seen = stored_data.get("seen_events", {})
                if isinstance(raw_seen, dict):
                    self._seen_events = {
                        dev_id: {fp for fp in fps if isinstance(fp, str)}
                        if isinstance(fps, list)
                        else set()
                        for dev_id, fps in raw_seen.items()
                        if isinstance(dev_id, str)
                    }

    def get_seen(self, device_id: str) -> set[str]:
        """Get copy of seen fingerprints for a device."""
        raw_set = self._seen_events.get(device_id, set())
        return {fp for fp in raw_set if isinstance(fp, str)}

    def update_seen(self, device_id: str, fingerprints: set[str]) -> None:
        """Update seen fingerprints for a device and schedule delayed save."""
        self._seen_events[device_id] = {
            fp for fp in fingerprints if isinstance(fp, str)
        }
        self._store.async_delay_save(self._data_to_save, delay=2.0)

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        """Return serialized data dictionary for Home Assistant Store delayed save."""
        return {
            "version": STORAGE_VERSION,
            "seen_events": {
                dev_id: list(fps) for dev_id, fps in self._seen_events.items()
            },
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IGuardStoveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGuardStove event entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    store = Store[dict[str, Any]](
        hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry.entry_id}"
    )
    store_manager = EventStoreManager(store)
    await store_manager.async_load()

    known_devices = set(coordinator.device_ids)
    entities: list[IGuardStoveActivityEventEntity] = [
        IGuardStoveActivityEventEntity(coordinator, device_id, store_manager)
        for device_id in coordinator.device_ids
    ]

    async_add_entities(entities)

    @callback
    def _async_add_new_devices(new_device_ids: list[str]) -> None:
        new_entities: list[IGuardStoveActivityEventEntity] = []
        for device_id in new_device_ids:
            if device_id not in known_devices:
                known_devices.add(device_id)
                new_entities.append(
                    IGuardStoveActivityEventEntity(
                        coordinator,
                        device_id,
                        store_manager,
                    )
                )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_{entry.entry_id}_new_device",
            _async_add_new_devices,
        )
    )


class IGuardStoveActivityEventEntity(IGuardStoveEntity, EventEntity):
    """Event entity for tracking iGuardStove portal activity events."""

    _attr_translation_key = "activity"

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
        store_manager: EventStoreManager,
    ) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, device_id)
        self._attr_event_types = [e.value for e in StoveEventType]
        self._store_manager = store_manager
        self._attr_unique_id = f"{device_id}_activity"
        self._seen_fingerprints: set[str] = store_manager.get_seen(device_id)
        self._initial_seeded: bool = False

        # NOTE (Intentional Startup Policy):
        # We seed all events from the initial coordinator snapshot directly into seen_fingerprints
        # without emitting HA event triggers. This intentionally suppresses events that occurred
        # while Home Assistant was offline to prevent firing stale automation triggers upon startup.
        if self._device_data:
            initial_events = self._device_data.get("today_events", ())
            for event in initial_events:
                fp = make_event_fingerprint(self.device_id, event)
                self._seen_fingerprints.add(fp)
            self._store_manager.update_seen(self.device_id, self._seen_fingerprints)
            self._initial_seeded = True

    @property
    def available(self) -> bool:
        """Return True if entity and event data are available."""
        data = self._device_data
        if data is None:
            return False
        return super().available and data.get("events_error") is None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self._device_data
        if not data or "today_events" not in data:
            super()._handle_coordinator_update()
            return

        events = data.get("today_events", ())

        # Always merge initial coordinator snapshot into seen set without emitting events
        if not self._initial_seeded:
            for event in events:
                fp = make_event_fingerprint(self.device_id, event)
                self._seen_fingerprints.add(fp)
            self._store_manager.update_seen(self.device_id, self._seen_fingerprints)
            self._initial_seeded = True
            super()._handle_coordinator_update()
            return

        new_events: list[StoveEvent] = []
        for event in events:
            fp = make_event_fingerprint(self.device_id, event)
            if fp not in self._seen_fingerprints:
                new_events.append(event)
                self._seen_fingerprints.add(fp)

        if new_events:
            # Sort explicitly by occurred_at and duplicate_ordinal (oldest first)
            new_events.sort(
                key=lambda event: (
                    event.occurred_at,
                    event.duplicate_ordinal,
                )
            )

            enable_events = True
            if (
                hasattr(self.coordinator, "config_entry")
                and self.coordinator.config_entry
            ):
                enable_events = self.coordinator.config_entry.options.get(
                    CONF_ENABLE_ACTIVITY_EVENTS, True
                )

            for event in new_events:
                if enable_events:
                    event_data = {
                        "occurred_at": event.occurred_at.isoformat(),
                        "raw_label": event.raw_label,
                    }
                    self._trigger_event(event.event_type.value, event_data)

            self._prune_fingerprints()
            self._store_manager.update_seen(self.device_id, self._seen_fingerprints)

        super()._handle_coordinator_update()

    def _prune_fingerprints(self) -> None:
        """Prune fingerprints older than 48 hours and retain newest 500 deterministically."""
        now = dt_util.now()
        cutoff = now - timedelta(days=2)
        retained: set[str] = set()

        def _extract_fp_datetime(fp: str) -> datetime:
            if not isinstance(fp, str):
                return datetime.min.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            parts = fp.split("|")
            if len(parts) >= 2:
                try:
                    dt = datetime.fromisoformat(parts[1])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                    return dt
                except ValueError:
                    pass
            return datetime.min.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

        for fp in self._seen_fingerprints:
            if not isinstance(fp, str):
                continue
            dt = _extract_fp_datetime(fp)
            if (
                dt == datetime.min.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                or dt >= cutoff
            ):
                retained.add(fp)

        if len(retained) > 500:
            sorted_fps = sorted(retained, key=lambda fp: (_extract_fp_datetime(fp), fp))
            retained = set(sorted_fps[-500:])

        self._seen_fingerprints = retained
