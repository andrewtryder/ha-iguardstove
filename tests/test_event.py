"""Tests for iGuardStove event entity platform and deduplication."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.const import DOMAIN
from custom_components.iguardstove.event import make_event_fingerprint
from custom_components.iguardstove.models import StoveEvent, StoveEventType


@pytest.mark.asyncio
async def test_event_entity_creation_and_initial_seeding(hass: HomeAssistant) -> None:
    """Test that event entity is created per stove and seeds initial events without firing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    event_1 = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
        event_type=StoveEventType.ACTIVITY_SEEN,
        raw_label="Activity Seen",
    )

    device_data = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (event_1,),
        "events_error": None,
    }

    captured_events: list = []

    @callback
    def _handle_event(evt):
        captured_events.append(evt)

    hass.bus.async_listen("state_changed", _handle_event)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=device_data,
        ) as mock_get_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Check entity existence
        state = hass.states.get("event.kitchen_stove_activity")
        assert state is not None

        # Verify no extra HTTP request during setup pass
        assert mock_get_data.call_count == 1


@pytest.mark.asyncio
async def test_event_entity_fires_new_events_oldest_first(
    hass: HomeAssistant,
) -> None:
    """Test that new events on subsequent updates fire exactly once, oldest-first."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    initial_event = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 7, 0, tzinfo=mock_tz),
        event_type=StoveEventType.NIGHT_LOCK_OFF,
        raw_label="Night Lock OFF",
    )

    data_pass_1 = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (initial_event,),
        "events_error": None,
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_1,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator

        # Pass 2: portal has 2 new events (table is newest-first: 9:50 AM then 9:47 AM)
        new_event_1 = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
            event_type=StoveEventType.ACTIVITY_SEEN,
            raw_label="Activity Seen",
        )
        new_event_2 = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 9, 50, tzinfo=mock_tz),
            event_type=StoveEventType.STOVE_ON,
            raw_label="Stove Turned ON",
        )

        data_pass_2 = {
            "device_id": "AABBCCDD1234",
            "device_name": "Kitchen Stove",
            "status": "Stove On",
            "today_events": (new_event_2, new_event_1, initial_event),
            "events_error": None,
        }

        fired_events: list[tuple[str, str]] = []

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None

        original_trigger = entity._trigger_event

        def _spy_trigger(event_type: str, event_data: dict):
            fired_events.append((event_type, event_data["occurred_at"]))
            original_trigger(event_type, event_data)

        entity._trigger_event = _spy_trigger

        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # Should fire oldest first: 9:47 AM then 9:50 AM
        assert len(fired_events) == 2
        assert fired_events[0] == (
            "activity_seen",
            datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz).isoformat(),
        )
        assert fired_events[1] == (
            "stove_on",
            datetime(2026, 7, 22, 9, 50, tzinfo=mock_tz).isoformat(),
        )

        # Pass 3: refresh with identical data -> no new events fired
        fired_events.clear()
        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert len(fired_events) == 0


@pytest.mark.asyncio
async def test_same_minute_duplicate_events(hass: HomeAssistant) -> None:
    """Test that two identical same-minute events can both fire once."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    data_pass_1 = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (),
        "events_error": None,
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_1,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator
        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )

        fired_events: list[str] = []

        def _spy_trigger(event_type: str, event_data: dict):
            fired_events.append(event_type)

        entity._trigger_event = _spy_trigger

        # Two identical events in same minute
        dup_event_0 = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
            event_type=StoveEventType.ACTIVITY_SEEN,
            raw_label="Activity Seen",
            duplicate_ordinal=0,
        )
        dup_event_1 = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
            event_type=StoveEventType.ACTIVITY_SEEN,
            raw_label="Activity Seen",
            duplicate_ordinal=1,
        )

        data_pass_2 = {
            "device_id": "AABBCCDD1234",
            "device_name": "Kitchen Stove",
            "status": "Stove Off",
            "today_events": (dup_event_0, dup_event_1),
            "events_error": None,
        }

        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert len(fired_events) == 2
        assert fired_events == ["activity_seen", "activity_seen"]


@pytest.mark.asyncio
async def test_unknown_events_fire_with_raw_label(hass: HomeAssistant) -> None:
    """Test that unknown events fire with event_type='unknown' and raw_label attribute."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    data_pass_1 = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (),
        "events_error": None,
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_1,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator
        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )

        fired_data: list[tuple[str, dict]] = []

        def _spy_trigger(event_type: str, event_data: dict):
            fired_data.append((event_type, event_data))

        entity._trigger_event = _spy_trigger

        unknown_evt = StoveEvent(
            occurred_at=datetime(2026, 7, 22, 10, 15, tzinfo=mock_tz),
            event_type=StoveEventType.UNKNOWN,
            raw_label="Rare Custom Alert",
        )

        data_pass_2 = {
            "device_id": "AABBCCDD1234",
            "device_name": "Kitchen Stove",
            "status": "Stove Off",
            "today_events": (unknown_evt,),
            "events_error": None,
        }

        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        assert len(fired_data) == 1
        assert fired_data[0][0] == "unknown"
        assert fired_data[0][1]["raw_label"] == "Rare Custom Alert"


@pytest.mark.asyncio
async def test_multi_device_independent_seen_state(hass: HomeAssistant) -> None:
    """Test that multi-device setups keep independent seen event state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [
                {"device_id": "DEV1", "device_name": "Stove 1"},
                {"device_id": "DEV2", "device_name": "Stove 2"},
            ],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    event_dev1 = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 9, 0, tzinfo=mock_tz),
        event_type=StoveEventType.ACTIVITY_SEEN,
        raw_label="Activity Seen",
    )

    def _get_data(dev_id, *args, **kwargs):
        if dev_id == "DEV1":
            return {
                "device_id": "DEV1",
                "device_name": "Stove 1",
                "status": "Stove Off",
                "today_events": (event_dev1,),
                "events_error": None,
            }
        return {
            "device_id": "DEV2",
            "device_name": "Stove 2",
            "status": "Stove Off",
            "today_events": (),
            "events_error": None,
        }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "DEV1", "device_name": "Stove 1"},
                {"device_id": "DEV2", "device_name": "Stove 2"},
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=_get_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_1 = hass.data["entity_components"]["event"].get_entity(
            "event.stove_1_activity"
        )
        entity_2 = hass.data["entity_components"]["event"].get_entity(
            "event.stove_2_activity"
        )

        assert entity_1 is not None
        assert entity_2 is not None

        # Pass 2: DEV2 receives the same event timing & label as DEV1 had
        fired_2: list[str] = []
        entity_2._trigger_event = lambda et, ed: fired_2.append(et)

        def _get_data_pass_2(dev_id, *args, **kwargs):
            return {
                "device_id": dev_id,
                "device_name": f"Stove {dev_id[-1]}",
                "status": "Stove Off",
                "today_events": (event_dev1,),
                "events_error": None,
            }

        coordinator = entry.runtime_data.coordinator
        with patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            side_effect=_get_data_pass_2,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

        # DEV2 fires because DEV1's seen state is independent
        assert len(fired_2) == 1
        assert fired_2[0] == "activity_seen"


@pytest.mark.asyncio
async def test_reloading_integration_does_not_replay_persisted_events(
    hass: HomeAssistant,
) -> None:
    """Test that reloading integration with persisted storage does not replay events."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    mock_tz = ZoneInfo("UTC")
    event_1 = StoveEvent(
        occurred_at=datetime(2026, 7, 22, 9, 47, tzinfo=mock_tz),
        event_type=StoveEventType.ACTIVITY_SEEN,
        raw_label="Activity Seen",
    )
    fp = make_event_fingerprint("AABBCCDD1234", event_1)

    mock_store_data = {"version": 1, "seen_events": {"AABBCCDD1234": [fp]}}

    device_data = {
        "device_id": "AABBCCDD1234",
        "device_name": "Kitchen Stove",
        "status": "Stove Off",
        "today_events": (event_1,),
        "events_error": None,
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=device_data,
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=mock_store_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None

        fired_events: list[str] = []
        entity._trigger_event = lambda et, ed: fired_events.append(et)

        coordinator = entry.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # No events replayed because stored fingerprint was loaded!
        assert len(fired_events) == 0


@pytest.mark.asyncio
async def test_event_pruning_and_day_rotation(hass: HomeAssistant) -> None:
    """Test pruning of fingerprints older than 48 hours."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    now = dt_util.now()

    old_dt = now - timedelta(days=3)
    old_event = StoveEvent(
        occurred_at=old_dt,
        event_type=StoveEventType.ACTIVITY_SEEN,
        raw_label="Activity Seen",
    )
    old_fp = make_event_fingerprint("AABBCCDD1234", old_event)

    new_event = StoveEvent(
        occurred_at=now - timedelta(hours=1),
        event_type=StoveEventType.STOVE_ON,
        raw_label="Stove Turned ON",
    )
    new_fp = make_event_fingerprint("AABBCCDD1234", new_event)

    mock_store_data = {
        "version": 1,
        "seen_events": {"AABBCCDD1234": [old_fp, new_fp]},
    }

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "AABBCCDD1234",
                "device_name": "Kitchen Stove",
                "status": "Stove Off",
                "today_events": (new_event,),
                "events_error": None,
            },
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            return_value=mock_store_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None

        # Trigger pruning
        entity._prune_fingerprints()

        # Old fingerprint pruned, new fingerprint retained
        assert old_fp not in entity._seen_fingerprints
        assert new_fp in entity._seen_fingerprints


@pytest.mark.asyncio
async def test_event_store_load_error_and_save_error(hass: HomeAssistant) -> None:
    """Test handling of store load and save errors."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "AABBCCDD1234",
                "device_name": "Kitchen Stove",
                "status": "Stove Off",
                "today_events": (),
                "events_error": None,
            },
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_load",
            side_effect=OSError("Read error"),
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_save",
            side_effect=OSError("Write error"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None
        assert entity.available is True

        # Test save error resilience
        await entity._async_save_store_data()


@pytest.mark.asyncio
async def test_event_entity_availability_on_events_error(
    hass: HomeAssistant,
) -> None:
    """Test entity availability behavior when events_error is present or data is missing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "user@example.com",
            "password": "secret",
            "devices": [{"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}],
        },
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[
                {"device_id": "AABBCCDD1234", "device_name": "Kitchen Stove"}
            ],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value={
                "device_id": "AABBCCDD1234",
                "device_name": "Kitchen Stove",
                "status": "Stove Off",
                "today_events": (),
                "events_error": "Today's Events section missing",
            },
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity = hass.data["entity_components"]["event"].get_entity(
            "event.kitchen_stove_activity"
        )
        assert entity is not None
        assert entity.available is False
