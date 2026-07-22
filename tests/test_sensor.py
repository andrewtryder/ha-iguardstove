"""Tests for iGuardStove sensor entities."""

from unittest.mock import patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.const import DOMAIN

MOCK_DEVICES = [{"device_id": "AABBCCDD1234", "device_name": "Guest House Stove"}]

# ---------------------------------------------------------------------------
# Mock device data sets
# ---------------------------------------------------------------------------

DEVICE_DATA_NORMAL = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Stove Off",
    "status_raw": "iGuardStove is off",
    "is_locked": False,
    "last_check_in": "20 minutes ago",
    "temperature": 72.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}

DEVICE_DATA_LOCKED = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Night Lock",
    "status_raw": "iGuardStove is LOCKED OUT for the night",
    "is_locked": True,
    "last_check_in": "5 minutes ago",
    "temperature": 70.0,
    "temperature_unit": "°F",
    "fires_prevented": 3,
}

DEVICE_DATA_CELSIUS = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": "Stove Off",
    "status_raw": "iGuardStove is off",
    "is_locked": False,
    "last_check_in": "1 hour ago",
    "temperature": 22.0,
    "temperature_unit": "°C",
    "fires_prevented": 0,
}

DEVICE_DATA_NO_DATA = {
    "device_id": "AABBCCDD1234",
    "device_name": "Guest House Stove",
    "status": None,
    "status_raw": None,
    "is_locked": False,
    "last_check_in": None,
    "temperature": None,
    "temperature_unit": "°F",
    "fires_prevented": None,
}


def _make_entry() -> MockConfigEntry:
    """Create a mock ConfigEntry for testing.

    Returns:
        The created MockConfigEntry.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
    )


async def _setup_integration(hass: HomeAssistant, device_data: dict) -> MockConfigEntry:
    """Helper: set up the integration with fixed device data.

    Args:
        hass: The HomeAssistant core object.
        device_data: The mocked device data to use.

    Returns:
        The created MockConfigEntry.
    """
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=MOCK_DEVICES,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_device_data",
            return_value=device_data,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


# ---------------------------------------------------------------------------
# Status sensor
# ---------------------------------------------------------------------------


async def test_status_sensor_stove_off(hass: HomeAssistant) -> None:
    """Test the status sensor reports 'Stove Off'.

    Args:
        hass: The HomeAssistant core object.
    """
    await _setup_integration(hass, DEVICE_DATA_NORMAL)
    state = hass.states.get("sensor.guest_house_stove_status")
    assert state is not None
    assert state.state == "Stove Off"
    assert state.attributes.get("status_raw") == "iGuardStove is off"


async def test_status_sensor_locked(hass: HomeAssistant) -> None:
    """Test the status sensor reports 'Night Lock' when locked.

    Args:
        hass: The HomeAssistant core object.
    """
    await _setup_integration(hass, DEVICE_DATA_LOCKED)
    state = hass.states.get("sensor.guest_house_stove_status")
    assert state is not None
    assert state.state == "Night Lock"


async def test_status_sensor_no_data(hass: HomeAssistant) -> None:
    """Test the status sensor is unknown when status data is missing.

    Args:
        hass: The HomeAssistant core object.
    """
    await _setup_integration(hass, DEVICE_DATA_NO_DATA)
    state = hass.states.get("sensor.guest_house_stove_status")
    assert state is not None
    assert state.state == "unknown"


# ---------------------------------------------------------------------------
# Last check-in sensor
# ---------------------------------------------------------------------------


async def test_last_checkin_sensor(hass: HomeAssistant) -> None:
    """Test the last check-in sensor returns the relative time string.

    Args:
        hass: The HomeAssistant core object.
    """
    await _setup_integration(hass, DEVICE_DATA_NORMAL)
    state = hass.states.get("sensor.guest_house_stove_last_check_in")
    assert state is not None
    assert state.state == "20 minutes ago"


async def test_last_checkin_sensor_none(hass: HomeAssistant) -> None:
    """Test the last check-in sensor is unknown when data is absent.

    Args:
        hass: The HomeAssistant core object.
    """
    await _setup_integration(hass, DEVICE_DATA_NO_DATA)
    state = hass.states.get("sensor.guest_house_stove_last_check_in")
    assert state is not None
    assert state.state == "unknown"


# ---------------------------------------------------------------------------
# Temperature sensor
# ---------------------------------------------------------------------------


async def test_temperature_sensor_fahrenheit(hass: HomeAssistant) -> None:
    """Test the temperature sensor in Fahrenheit.

    Args:
        hass: The HomeAssistant core object.
    """
    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    hass.config.units = US_CUSTOMARY_SYSTEM
    await _setup_integration(hass, DEVICE_DATA_NORMAL)
    state = hass.states.get("sensor.guest_house_stove_temperature")
    assert state is not None
    assert state.state == "72.0"
    assert state.attributes.get("unit_of_measurement") == "°F"


async def test_temperature_sensor_celsius(hass: HomeAssistant) -> None:
    """Test the temperature sensor in Celsius.

    Args:
        hass: The HomeAssistant core object.
    """
    await _setup_integration(hass, DEVICE_DATA_CELSIUS)
    state = hass.states.get("sensor.guest_house_stove_temperature")
    assert state is not None
    assert state.state == "22.0"
    assert state.attributes.get("unit_of_measurement") == "°C"


async def test_temperature_sensor_none(hass: HomeAssistant) -> None:
    """Test the temperature sensor is unknown when value is None.

    Args:
        hass: The HomeAssistant core object.
    """
    await _setup_integration(hass, DEVICE_DATA_NO_DATA)
    state = hass.states.get("sensor.guest_house_stove_temperature")
    assert state.state == "unknown"
