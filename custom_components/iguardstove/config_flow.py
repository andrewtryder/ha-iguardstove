"""Config flow for the iGuardStove integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import CannotConnect, IGuardStoveClient, InvalidAuth
from .const import (
    CONF_ALLOW_REMOTE_UNLOCK,
    CONF_ENABLE_ACTIVITY_EVENTS,
    CONF_REDISCOVER_DEVICES,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate that the provided credentials work and discover devices.

    Returns a dict with 'title' (for the config entry) and 'device_ids'.
    """
    username = data[CONF_USERNAME].strip()
    session = async_create_clientsession(
        hass, auto_cleanup=False, headers={"User-Agent": USER_AGENT}
    )
    client = IGuardStoveClient(session, username, data[CONF_PASSWORD])

    try:
        await client.async_login()
        devices = await client.async_get_devices()

        if not devices:
            raise CannotConnect("No iGuardStove devices found on this account")

        return {
            "title": f"iGuardStove ({username})",
            "device_ids": [d["device_id"] for d in devices],
            "devices": devices,
        }
    finally:
        await client.close()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iGuardStove."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_username = user_input[CONF_USERNAME]
            normalized_username = raw_username.strip().casefold()
            await self.async_set_unique_id(normalized_username)
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
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        **user_input,
                        CONF_USERNAME: raw_username.strip(),
                        "devices": info["devices"],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle initiation of reauthentication flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication confirmation step."""
        errors: dict[str, str] = {}
        reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )

        if user_input is not None and reauth_entry is not None:
            data = {
                CONF_USERNAME: reauth_entry.data[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                info = await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during reauth flow")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        "devices": info["devices"],
                    },
                )

        schema = vol.Schema({vol.Required(CONF_PASSWORD): str})
        username = reauth_entry.data[CONF_USERNAME] if reauth_entry else ""
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"username": username},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user-initiated reconfiguration flow."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            raw_username = user_input[CONF_USERNAME].strip()
            normalized_username = raw_username.casefold()

            if normalized_username != reconfigure_entry.unique_id:
                for entry in self._async_current_entries():
                    if (
                        entry.entry_id != reconfigure_entry.entry_id
                        and entry.unique_id == normalized_username
                    ):
                        return self.async_abort(reason="already_configured")

            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during reconfigure flow")
                errors["base"] = "unknown"
            else:
                if normalized_username != reconfigure_entry.unique_id:
                    await self.async_set_unique_id(normalized_username)

                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=info["title"],
                    data={
                        **reconfigure_entry.data,
                        CONF_USERNAME: raw_username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        "devices": info["devices"],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME,
                    default=reconfigure_entry.data.get(CONF_USERNAME, ""),
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create options flow handler."""
        return IGuardStoveOptionsFlowHandler()


class IGuardStoveOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle iGuardStove options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ALLOW_REMOTE_UNLOCK,
                    default=current_options.get(CONF_ALLOW_REMOTE_UNLOCK, False),
                ): bool,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current_options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Optional(
                    CONF_ENABLE_ACTIVITY_EVENTS,
                    default=current_options.get(CONF_ENABLE_ACTIVITY_EVENTS, True),
                ): bool,
                vol.Optional(
                    CONF_REDISCOVER_DEVICES,
                    default=False,
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
