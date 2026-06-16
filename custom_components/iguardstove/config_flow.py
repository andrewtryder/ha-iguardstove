"""Config flow for the iGuardStove integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import CannotConnect, IGuardStoveClient, InvalidAuth
from .const import DOMAIN, USER_AGENT

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate that the provided credentials work and discover devices.

    Returns a dict with 'title' (for the config entry) and 'device_ids'.
    """
    session = async_create_clientsession(hass, headers={"User-Agent": USER_AGENT})
    client = IGuardStoveClient(session, data[CONF_USERNAME], data[CONF_PASSWORD])

    await client.async_login()
    devices = await client.async_get_devices()

    if not devices:
        raise CannotConnect("No iGuardStove devices found on this account")

    return {
        "title": f"iGuardStove ({data[CONF_USERNAME]})",
        "device_ids": [d["device_id"] for d in devices],
        "devices": devices,
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iGuardStove."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during config flow")
                errors["base"] = "unknown"
            else:
                # Store devices alongside credentials so __init__.py can use them
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        **user_input,
                        "devices": info["devices"],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
