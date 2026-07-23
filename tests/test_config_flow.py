"""Tests for iGuardStove config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

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


async def test_flow_user_recovery_after_invalid_auth(hass: HomeAssistant) -> None:
    """Test initial user flow recovers and creates entry after invalid credentials first."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # First attempt: invalid auth
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

    # Second attempt: corrected credentials
    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": ["AABBCCDD1234"],
            "devices": MOCK_DEVICES,
        },
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )
        await hass.async_block_till_done()

    assert result3["type"] is FlowResultType.CREATE_ENTRY
    assert result3["title"] == "iGuardStove (user@example.com)"
    assert result3["data"][CONF_USERNAME] == "user@example.com"
    assert result3["data"][CONF_PASSWORD] == "secret"
    assert result3["data"]["devices"] == MOCK_DEVICES


async def test_flow_user_recovery_after_cannot_connect(hass: HomeAssistant) -> None:
    """Test initial user flow recovers and creates entry after connection failure first."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # First attempt: connection error
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

    # Second attempt: retry after connection restored
    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": ["AABBCCDD1234"],
            "devices": MOCK_DEVICES,
        },
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )
        await hass.async_block_till_done()

    assert result3["type"] is FlowResultType.CREATE_ENTRY
    assert result3["title"] == "iGuardStove (user@example.com)"
    assert result3["data"][CONF_USERNAME] == "user@example.com"
    assert result3["data"][CONF_PASSWORD] == "secret"
    assert result3["data"]["devices"] == MOCK_DEVICES


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


async def test_validate_input_session_close(hass: HomeAssistant) -> None:
    """Test that validate_input uses auto_cleanup=False and detaches session in finally."""
    from custom_components.iguardstove.config_flow import validate_input

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
            "custom_components.iguardstove.config_flow.async_create_clientsession"
        ) as mock_create_session,
    ):
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.detach = MagicMock()
        mock_create_session.return_value = mock_session

        info = await validate_input(
            hass, {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
        )
        assert info["device_ids"] == ["AABBCCDD1234"]

        mock_create_session.assert_called_once()
        assert mock_create_session.call_args.kwargs.get("auto_cleanup") is False
        mock_session.detach.assert_called_once()


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


async def test_flow_reauth_cannot_connect(hass: HomeAssistant) -> None:
    """Test reauth flow shows error when connection fails."""
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
        side_effect=CannotConnect("Connection failed"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new_password"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_flow_reauth_recovery_after_bad_password(hass: HomeAssistant) -> None:
    """Test reauth flow recovers and completes after submitting invalid password first."""
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

    # First attempt: invalid auth
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

    # Second attempt: valid credentials
    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": ["AABBCCDD1234"],
            "devices": MOCK_DEVICES,
        },
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {CONF_PASSWORD: "correct_password"},
        )
        await hass.async_block_till_done()

    assert result3["type"] is FlowResultType.ABORT
    assert result3["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "correct_password"


async def test_validate_input_success(hass: HomeAssistant) -> None:
    """Test validate_input function with valid credentials and discovered devices."""
    from custom_components.iguardstove.config_flow import validate_input

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=MOCK_DEVICES,
        ),
    ):
        result = await validate_input(
            hass, {CONF_USERNAME: "user@example.com ", CONF_PASSWORD: "secret"}
        )

    assert result["title"] == "iGuardStove (user@example.com)"
    assert result["device_ids"] == ["AABBCCDD1234"]
    assert result["devices"] == MOCK_DEVICES


async def test_validate_input_no_devices(hass: HomeAssistant) -> None:
    """Test validate_input raises CannotConnect when no devices found on account."""
    import pytest

    from custom_components.iguardstove.config_flow import validate_input

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[],
        ),
        pytest.raises(CannotConnect, match="No iGuardStove devices found"),
    ):
        await validate_input(
            hass, {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
        )


async def test_validate_input_dashboard_parse_error_is_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """DashboardParseError from discovery must surface as CannotConnect."""
    import pytest

    from custom_components.iguardstove.config_flow import validate_input
    from custom_components.iguardstove.exceptions import DashboardParseError

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            side_effect=DashboardParseError("malformed dashboard"),
        ),
        pytest.raises(CannotConnect, match="dashboard could not be parsed"),
    ):
        await validate_input(
            hass, {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
        )


async def test_flow_user_dashboard_parse_error_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """User flow maps DashboardParseError to cannot_connect, not unknown."""
    from custom_components.iguardstove.exceptions import DashboardParseError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            side_effect=DashboardParseError("malformed dashboard"),
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.close",
            new_callable=AsyncMock,
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_validate_input_no_devices_allowed_when_not_required(
    hass: HomeAssistant,
) -> None:
    """Reauth/reconfigure may validate credentials without requiring devices."""
    from custom_components.iguardstove.config_flow import validate_input

    with (
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_login",
            return_value=True,
        ),
        patch(
            "custom_components.iguardstove.client.IGuardStoveClient.async_get_devices",
            return_value=[],
        ),
    ):
        result = await validate_input(
            hass,
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
            require_devices=False,
        )

    assert result["title"] == "iGuardStove (user@example.com)"
    assert result["device_ids"] == []
    assert result["devices"] == []


async def test_flow_reauth_zero_devices_success(hass: HomeAssistant) -> None:
    """Successful reauth with zero devices persists an empty device list."""
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
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": [],
            "devices": [],
        },
    ) as mock_validate:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new_password"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new_password"
    assert entry.data["devices"] == []
    assert mock_validate.await_args.kwargs.get("require_devices") is False


async def test_flow_reconfigure_zero_devices_success(hass: HomeAssistant) -> None:
    """Successful reconfigure with zero devices persists an empty device list."""
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

    result = await entry.start_reconfigure_flow(hass)
    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": [],
            "devices": [],
        },
    ) as mock_validate:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new_password"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PASSWORD] == "new_password"
    assert entry.data["devices"] == []
    assert mock_validate.await_args.kwargs.get("require_devices") is False


async def test_flow_reauth_unknown_exception(hass: HomeAssistant) -> None:
    """Test reauth flow shows unknown error on unexpected exception."""
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
        side_effect=RuntimeError("Unexpected error"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new_password"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "unknown"}


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test updating integration options via options flow."""
    from custom_components.iguardstove.const import (
        CONF_ALLOW_REMOTE_UNLOCK,
        CONF_ENABLE_ACTIVITY_EVENTS,
        CONF_REDISCOVER_DEVICES,
        CONF_SCAN_INTERVAL,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ALLOW_REMOTE_UNLOCK: True,
            CONF_SCAN_INTERVAL: 120,
            CONF_ENABLE_ACTIVITY_EVENTS: False,
            CONF_REDISCOVER_DEVICES: False,
        },
    )
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_ALLOW_REMOTE_UNLOCK: True,
        CONF_SCAN_INTERVAL: 120,
        CONF_ENABLE_ACTIVITY_EVENTS: False,
    }
    assert CONF_REDISCOVER_DEVICES not in entry.options


async def test_flow_reconfigure_success(hass: HomeAssistant) -> None:
    """Test successful user-initiated reconfigure flow."""
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

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

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
                CONF_PASSWORD: "new_password",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PASSWORD] == "new_password"
    assert entry.unique_id == "user@example.com"
    assert entry.data[CONF_USERNAME] == "user@example.com"


async def test_flow_reconfigure_preserves_account_identity(hass: HomeAssistant) -> None:
    """Test reconfigure only updates password and keeps account unique_id fixed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "password",
            "devices": MOCK_DEVICES,
        },
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    schema_keys = {marker.schema for marker in result["data_schema"].schema}
    assert CONF_USERNAME not in schema_keys
    assert CONF_PASSWORD in schema_keys

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        return_value={
            "title": "iGuardStove (user@example.com)",
            "device_ids": ["AABBCCDD1234"],
            "devices": MOCK_DEVICES,
        },
    ) as mock_validate:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new_password"},
        )
        await hass.async_block_till_done()

    assert result2["reason"] == "reconfigure_successful"
    assert mock_validate.await_args.args[1][CONF_USERNAME] == "user@example.com"
    assert entry.unique_id == "user@example.com"


async def test_flow_reconfigure_invalid_auth(hass: HomeAssistant) -> None:
    """Test reconfigure flow displays error on invalid auth."""
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

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        side_effect=InvalidAuth("Bad password"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_PASSWORD: "wrong_password",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_flow_reconfigure_cannot_connect(hass: HomeAssistant) -> None:
    """Test reconfigure flow displays error on connection failure."""
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

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        side_effect=CannotConnect("Offline"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_PASSWORD: "new_password",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_flow_reconfigure_unknown_exception(hass: HomeAssistant) -> None:
    """Test reconfigure flow displays error on unexpected exception."""
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

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with patch(
        "custom_components.iguardstove.config_flow.validate_input",
        side_effect=RuntimeError("Unexpected error"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_PASSWORD: "new_password",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "unknown"}


async def test_options_flow_rediscover_triggers_coordinator(
    hass: HomeAssistant,
) -> None:
    """Rediscover checkbox runs one-shot discovery and is not persisted."""
    from custom_components.iguardstove.const import (
        CONF_ALLOW_REMOTE_UNLOCK,
        CONF_ENABLE_ACTIVITY_EVENTS,
        CONF_REDISCOVER_DEVICES,
        CONF_SCAN_INTERVAL,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_rediscover_now = AsyncMock(return_value=MOCK_DEVICES)
    entry.runtime_data = MagicMock(coordinator=coordinator)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ALLOW_REMOTE_UNLOCK: False,
            CONF_SCAN_INTERVAL: 60,
            CONF_ENABLE_ACTIVITY_EVENTS: True,
            CONF_REDISCOVER_DEVICES: True,
        },
    )
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    coordinator.async_rediscover_now.assert_awaited_once()
    assert CONF_REDISCOVER_DEVICES not in entry.options


async def test_options_flow_rediscover_invalid_auth(hass: HomeAssistant) -> None:
    """Auth failures during rediscovery must not save options or reload."""
    from custom_components.iguardstove.const import (
        CONF_ALLOW_REMOTE_UNLOCK,
        CONF_ENABLE_ACTIVITY_EVENTS,
        CONF_REDISCOVER_DEVICES,
        CONF_SCAN_INTERVAL,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
        options={CONF_SCAN_INTERVAL: 90},
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_rediscover_now = AsyncMock(side_effect=InvalidAuth("bad"))
    entry.runtime_data = MagicMock(coordinator=coordinator)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ALLOW_REMOTE_UNLOCK: True,
            CONF_SCAN_INTERVAL: 120,
            CONF_ENABLE_ACTIVITY_EVENTS: False,
            CONF_REDISCOVER_DEVICES: True,
        },
    )
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}
    assert entry.options == {CONF_SCAN_INTERVAL: 90}
    assert CONF_REDISCOVER_DEVICES not in entry.options


async def test_options_flow_rediscover_cannot_connect(hass: HomeAssistant) -> None:
    """Connection failures during rediscovery must not save options or reload."""
    from custom_components.iguardstove.const import (
        CONF_ALLOW_REMOTE_UNLOCK,
        CONF_ENABLE_ACTIVITY_EVENTS,
        CONF_REDISCOVER_DEVICES,
        CONF_SCAN_INTERVAL,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
        options={CONF_ALLOW_REMOTE_UNLOCK: False},
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_rediscover_now = AsyncMock(side_effect=CannotConnect("offline"))
    entry.runtime_data = MagicMock(coordinator=coordinator)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ALLOW_REMOTE_UNLOCK: True,
            CONF_SCAN_INTERVAL: 120,
            CONF_ENABLE_ACTIVITY_EVENTS: False,
            CONF_REDISCOVER_DEVICES: True,
        },
    )
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}
    assert entry.options == {CONF_ALLOW_REMOTE_UNLOCK: False}
    assert CONF_REDISCOVER_DEVICES not in entry.options


async def test_options_flow_rediscover_missing_runtime(hass: HomeAssistant) -> None:
    """Missing runtime during rediscovery is reported as cannot_connect."""
    from custom_components.iguardstove.const import (
        CONF_ALLOW_REMOTE_UNLOCK,
        CONF_ENABLE_ACTIVITY_EVENTS,
        CONF_REDISCOVER_DEVICES,
        CONF_SCAN_INTERVAL,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            "devices": MOCK_DEVICES,
        },
        options={CONF_SCAN_INTERVAL: 60},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ALLOW_REMOTE_UNLOCK: True,
            CONF_SCAN_INTERVAL: 120,
            CONF_ENABLE_ACTIVITY_EVENTS: False,
            CONF_REDISCOVER_DEVICES: True,
        },
    )
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}
    assert entry.options == {CONF_SCAN_INTERVAL: 60}
