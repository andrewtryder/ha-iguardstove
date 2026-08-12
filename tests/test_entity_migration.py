"""Tests for Master Lock / lockout entity registry migration."""

from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove import async_migrate_entry
from custom_components.iguardstove.const import DOMAIN
from custom_components.iguardstove.entity_migration import (
    async_migrate_legacy_stove_lock_entities,
)

MOCK_DEVICES = [{"device_id": "AABBCCDD1234", "device_name": "Guest House Stove"}]
MOCK_DEVICES_TWO = [
    {"device_id": "DEV1", "device_name": "Kitchen Stove"},
    {"device_id": "DEV2", "device_name": "Guest Stove"},
]

DEVICE_DATA_OFF = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Stove Off",
    "status_raw": "iGuardStove is off",
    "is_master_locked": False,
    "is_lockout_active": False,
    "last_check_in": "20 minutes ago",
    "temperature": 72.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}

DEVICE_DATA_NIGHT_LOCK_MASTER_OFF = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Night Lock",
    "status_raw": "iGuardStove is LOCKED OUT for the night",
    "is_master_locked": False,
    "is_lockout_active": True,
    "last_check_in": "5 minutes ago",
    "temperature": 70.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}


def _make_entry(
    *,
    version: int = 1,
    devices: list[dict] | None = None,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=version,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": devices or MOCK_DEVICES,
        },
    )


async def _setup_with_device_data(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    device_data: dict,
    *,
    enable_master_lock: bool = False,
) -> None:
    """Set up integration with patched client returning fixed device data."""
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=entry.data["devices"],
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=device_data,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        if enable_master_lock:
            registry = er.async_get(hass)
            entity_id = registry.async_get_entity_id(
                "lock", DOMAIN, f"{device_data['device_id']}_master_lock"
            )
            assert entity_id is not None
            registry.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()


async def test_fresh_install_canonical_unique_ids(hass: HomeAssistant) -> None:
    """Fresh install uses master_lock and stove_lockout; no legacy stove_lock."""
    entry = _make_entry(version=2)
    await _setup_with_device_data(hass, entry, DEVICE_DATA_OFF)

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("lock", DOMAIN, "AABBCCDD1234_master_lock")
        is not None
    )
    assert (
        registry.async_get_entity_id(
            "binary_sensor", DOMAIN, "AABBCCDD1234_stove_lockout"
        )
        is not None
    )
    assert (
        registry.async_get_entity_id("lock", DOMAIN, "AABBCCDD1234_stove_lock") is None
    )
    assert entry.version == 2


async def test_legacy_stove_lock_migrates_to_master_lock(hass: HomeAssistant) -> None:
    """Legacy _stove_lock is retired; Master Lock uses _master_lock."""
    entry = _make_entry(version=1)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "lock",
        DOMAIN,
        "AABBCCDD1234_stove_lock",
        config_entry=entry,
        suggested_object_id="stove_lock",
        disabled_by=None,
    )
    legacy_entity_id = legacy.entity_id
    assert legacy.disabled_by is None

    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == 2

    assert registry.async_get(legacy_entity_id) is None
    assert (
        registry.async_get_entity_id("lock", DOMAIN, "AABBCCDD1234_stove_lock") is None
    )
    master_entity_id = registry.async_get_entity_id(
        "lock", DOMAIN, "AABBCCDD1234_master_lock"
    )
    assert master_entity_id is not None
    master = registry.async_get(master_entity_id)
    assert master is not None
    assert master.disabled_by is None
    assert master.entity_id != legacy_entity_id


async def test_user_renamed_legacy_entity_id_not_preserved(
    hass: HomeAssistant,
) -> None:
    """Custom entity_id is not reused; custom name is preserved on Master Lock."""
    entry = _make_entry(version=1)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "lock",
        DOMAIN,
        "AABBCCDD1234_stove_lock",
        config_entry=entry,
        suggested_object_id="stove_lock",
    )
    registry.async_update_entity(
        legacy.entity_id,
        name="Kitchen Remote Lock",
        new_entity_id="lock.my_custom_stove_lock",
    )
    assert registry.async_get("lock.my_custom_stove_lock") is not None

    assert await async_migrate_entry(hass, entry) is True

    assert registry.async_get("lock.my_custom_stove_lock") is None
    master_entity_id = registry.async_get_entity_id(
        "lock", DOMAIN, "AABBCCDD1234_master_lock"
    )
    assert master_entity_id is not None
    assert master_entity_id != "lock.my_custom_stove_lock"
    master = registry.async_get(master_entity_id)
    assert master is not None
    assert master.name == "Kitchen Remote Lock"


async def test_disabled_legacy_preserves_disabled_by(hass: HomeAssistant) -> None:
    """Disabled legacy lock seeds a disabled Master Lock registry entry."""
    entry = _make_entry(version=1)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "lock",
        DOMAIN,
        "AABBCCDD1234_stove_lock",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    assert await async_migrate_entry(hass, entry) is True

    master_entity_id = registry.async_get_entity_id(
        "lock", DOMAIN, "AABBCCDD1234_master_lock"
    )
    assert master_entity_id is not None
    master = registry.async_get(master_entity_id)
    assert master is not None
    assert master.disabled_by is er.RegistryEntryDisabler.USER


async def test_multiple_devices_migrate_independently(hass: HomeAssistant) -> None:
    """Each device's legacy lock migrates to its own Master Lock unique_id."""
    entry = _make_entry(version=1, devices=MOCK_DEVICES_TWO)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for device_id in ("DEV1", "DEV2"):
        registry.async_get_or_create(
            "lock",
            DOMAIN,
            f"{device_id}_stove_lock",
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )

    assert await async_migrate_entry(hass, entry) is True

    for device_id in ("DEV1", "DEV2"):
        assert (
            registry.async_get_entity_id("lock", DOMAIN, f"{device_id}_stove_lock")
            is None
        )
        assert (
            registry.async_get_entity_id("lock", DOMAIN, f"{device_id}_master_lock")
            is not None
        )


async def test_migration_idempotent(hass: HomeAssistant) -> None:
    """Running migration twice does not create duplicates or mutate further."""
    entry = _make_entry(version=1)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "lock",
        DOMAIN,
        "AABBCCDD1234_stove_lock",
        config_entry=entry,
        disabled_by=None,
    )

    assert await async_migrate_entry(hass, entry) is True
    master_entity_id = registry.async_get_entity_id(
        "lock", DOMAIN, "AABBCCDD1234_master_lock"
    )
    assert master_entity_id is not None
    master_before = registry.async_get(master_entity_id)
    assert master_before is not None

    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == 2
    assert (
        registry.async_get_entity_id("lock", DOMAIN, "AABBCCDD1234_master_lock")
        == master_entity_id
    )
    # Explicit second pass of the helper after version gate would be a no-op
    # for missing legacy entries.
    await async_migrate_legacy_stove_lock_entities(hass, entry)
    lock_entries = [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "lock" and e.unique_id.endswith("_master_lock")
    ]
    assert len(lock_entries) == 1


async def test_partial_migration_removes_leftover_legacy(hass: HomeAssistant) -> None:
    """If Master Lock already exists, leftover _stove_lock is removed only."""
    entry = _make_entry(version=1)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    master = registry.async_get_or_create(
        "lock",
        DOMAIN,
        "AABBCCDD1234_master_lock",
        config_entry=entry,
        disabled_by=None,
        suggested_object_id="master_lock",
    )
    legacy = registry.async_get_or_create(
        "lock",
        DOMAIN,
        "AABBCCDD1234_stove_lock",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    assert await async_migrate_entry(hass, entry) is True

    assert registry.async_get(legacy.entity_id) is None
    assert registry.async_get(master.entity_id) is not None
    still_master = registry.async_get(master.entity_id)
    assert still_master is not None
    assert still_master.disabled_by is None
    assert still_master.unique_id == "AABBCCDD1234_master_lock"


async def test_orphan_legacy_lock_migrates_without_discovery_device(
    hass: HomeAssistant,
) -> None:
    """Legacy lock migrates even when its device is absent from entry devices."""
    entry = _make_entry(
        version=1,
        devices=[{"device_id": "DEV_A", "device_name": "Kitchen Stove"}],
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "lock",
        DOMAIN,
        "ORPHAN_stove_lock",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )

    assert await async_migrate_entry(hass, entry) is True

    assert registry.async_get_entity_id("lock", DOMAIN, "ORPHAN_stove_lock") is None
    master_entity_id = registry.async_get_entity_id(
        "lock", DOMAIN, "ORPHAN_master_lock"
    )
    assert master_entity_id is not None
    master = registry.async_get(master_entity_id)
    assert master is not None
    assert master.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_night_lock_master_off_runtime_semantics(hass: HomeAssistant) -> None:
    """Night Lock with Master Lock off: Master unlocked, lockout on."""
    entry = _make_entry(version=2)
    await _setup_with_device_data(
        hass, entry, DEVICE_DATA_NIGHT_LOCK_MASTER_OFF, enable_master_lock=True
    )

    lock_state = hass.states.get("lock.guest_house_stove_master_lock")
    assert lock_state is not None
    assert lock_state.state == "unlocked"

    lockout_state = hass.states.get("binary_sensor.guest_house_stove_stove_lockout")
    assert lockout_state is not None
    assert lockout_state.state == STATE_ON
