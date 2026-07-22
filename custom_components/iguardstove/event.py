"""Event platform for iGuardStove integration."""

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
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

    try:
        stored_data = await store.async_load()
    except Exception as err:
        _LOGGER.warning("Error loading event deduplication store: %s", err)
        stored_data = None

    seen_events_map: dict[str, list[str]] = (
        stored_data.get("seen_events", {}) if isinstance(stored_data, dict) else {}
    )

    known_devices = set(coordinator.device_ids)
    entities: list[IGuardStoveActivityEventEntity] = [
        IGuardStoveActivityEventEntity(
            coordinator, device_id, store, seen_events_map.get(device_id, [])
        )
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
                        store,
                        seen_events_map.get(device_id, []),
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
    _attr_event_types = [e.value for e in StoveEventType]

    def __init__(
        self,
        coordinator: IGuardStoveDataUpdateCoordinator,
        device_id: str,
        store: Store[dict[str, Any]],
        initial_seen_fingerprints: list[str],
    ) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, device_id)
        self._store = store
        self._attr_unique_id = f"{device_id}_activity"
        self._seen_fingerprints: set[str] = set(initial_seen_fingerprints)
        self._has_persisted_state = bool(initial_seen_fingerprints)

        # Seed initial events if coordinator data is already available and no store exists
        if not self._has_persisted_state and self._device_data:
            initial_events = self._device_data.get("today_events", ())
            for event in initial_events:
                fp = make_event_fingerprint(self.device_id, event)
                self._seen_fingerprints.add(fp)

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

        new_events: list[StoveEvent] = []
        for event in events:
            fp = make_event_fingerprint(self.device_id, event)
            if fp not in self._seen_fingerprints:
                new_events.append(event)
                self._seen_fingerprints.add(fp)

        if new_events:
            # Emit oldest-first so automations observe proper chronology
            for event in reversed(new_events):
                event_data = {
                    "occurred_at": event.occurred_at.isoformat(),
                    "raw_label": event.raw_label,
                }
                self._trigger_event(event.event_type.value, event_data)

            self._prune_fingerprints()
            self._async_save_store()

        super()._handle_coordinator_update()

    def _prune_fingerprints(self) -> None:
        """Prune fingerprints older than 48 hours to maintain a bounded window."""
        now = dt_util.now()
        cutoff = now - timedelta(days=2)
        retained: set[str] = set()

        for fp in self._seen_fingerprints:
            parts = fp.split("|")
            if len(parts) >= 2:
                try:
                    dt = datetime.fromisoformat(parts[1])
                    if dt >= cutoff:
                        retained.add(fp)
                    continue
                except ValueError:
                    pass
            retained.add(fp)

        if len(retained) > 500:
            retained = set(list(retained)[-500:])

        self._seen_fingerprints = retained

    def _async_save_store(self) -> None:
        """Save seen fingerprints to persistent storage."""
        self.hass.async_create_task(self._async_save_store_data())

    async def _async_save_store_data(self) -> None:
        """Helper to safely save store data."""
        try:
            stored = await self._store.async_load()
            data: dict[str, Any] = (
                dict(stored) if isinstance(stored, dict) and stored else {"version": 1}
            )
            seen_map = data.setdefault("seen_events", {})
            seen_map[self.device_id] = list(self._seen_fingerprints)
            await self._store.async_save(data)
        except Exception as err:
            _LOGGER.warning(
                "Failed to save event deduplication store for %s: %s",
                self.device_id,
                err,
            )
