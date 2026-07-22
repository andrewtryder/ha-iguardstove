"""Tests for iGuardStove config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.iguardstove.client import CannotConnect, InvalidAuth
from custom_components.iguardstove.const import DOMAIN

MOCK_DEVICES = [{"device_id": "AABBCCDD1234", "device_name": "Guest House Stove"}]


async def test_flow_user_init(hass: HomeAssistant) -> None:
    """Test that the user step shows a form with no errors initially."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_flow_user_success(hass: HomeAssistant) -> None:
    """Test successful config flow creates an entry with device data stored."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": ["AABBCCDD1234"],
            "devices": MOCK_DEVICES,
        },
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "secret",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == "iGuardStove (user@example.com)"
    assert result2["data"][CONF_USERNAME] == "user@example.com"
    assert result2["data"][CONF_PASSWORD] == "secret"
    assert result2["data"]["devices"] == MOCK_DEVICES


async def test_flow_user_cannot_connect(hass: HomeAssistant) -> None:
    """Test config flow shows an error on CannotConnect."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        side_effect=CannotConnect("Connection refused"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_flow_user_invalid_auth(hass: HomeAssistant) -> None:
    """Test config flow shows an error on InvalidAuth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        side_effect=InvalidAuth("Bad password"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "wrong"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_flow_user_unknown_exception(hass: HomeAssistant) -> None:
    """Test config flow shows an error on unexpected exceptions."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        side_effect=Exception("Something unexpected"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "unknown"}


async def test_flow_duplicate_entry_aborted(hass: HomeAssistant) -> None:
    """Test that a duplicate account (same username) is aborted."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": ["AABBCCDD1234"],
            "devices": MOCK_DEVICES,
        },
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_flow_reauth_success(hass: HomeAssistant) -> None:
    """Test successful reauthentication updates entry password."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "old_password",
            "devices": MOCK_DEVICES,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data={"username": "user@example.com", "password": "old_password"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": ["AABBCCDD1234"],
            "devices": MOCK_DEVICES,
        },
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new_password"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new_password"


async def test_flow_reauth_invalid_auth(hass: HomeAssistant) -> None:
    """Test reauth flow shows error when invalid password provided."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "old_password",
            "devices": MOCK_DEVICES,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data={"username": "user@example.com", "password": "old_password"},
    )

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        side_effect=InvalidAuth("Bad password"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "wrong_password"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}
