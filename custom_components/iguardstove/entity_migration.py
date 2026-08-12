"""Entity registry migration helpers for iGuardStove."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

LEGACY_STOVE_LOCK_SUFFIX = "_stove_lock"
MASTER_LOCK_SUFFIX = "_master_lock"


def _device_id_from_legacy_lock_unique_id(unique_id: str) -> str | None:
    """Return device_id prefix for a legacy stove_lock unique_id, else None."""
    if not unique_id.endswith(LEGACY_STOVE_LOCK_SUFFIX):
        return None
    device_id = unique_id[: -len(LEGACY_STOVE_LOCK_SUFFIX)]
    return device_id or None


async def async_migrate_legacy_stove_lock_entities(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Retire legacy lock unique_ids and seed Master Lock registry rows.

    Legacy ``{device_id}_stove_lock`` lock entities meant effective lockout.
    Master Lock must use ``{device_id}_master_lock`` so the old identity is not
    silently repurposed. Cross-platform lock→binary_sensor transfer is not
    supported; Stove Lockout keeps ``{device_id}_stove_lockout``.

    Migration is scoped to entity-registry entries owned by this config entry.
    It does **not** consult portal discovery or ``entry.data["devices"]``, so
    legacy lock rows still migrate when that stove is offline or absent from
    the current discovery result.

    Preserves ``disabled_by``, custom ``name``, ``icon``, ``area_id``, and
    ``labels`` / ``categories`` when seeding the new Master Lock row. Does
    **not** reuse the legacy ``entity_id``.
    """
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)

    for entry in list(entries):
        if entry.domain != "lock" or entry.platform != DOMAIN:
            continue

        device_id = _device_id_from_legacy_lock_unique_id(entry.unique_id)
        if device_id is None:
            continue

        master_unique_id = f"{device_id}{MASTER_LOCK_SUFFIX}"
        existing_master_entity_id = registry.async_get_entity_id(
            "lock", DOMAIN, master_unique_id
        )

        if existing_master_entity_id is not None:
            _LOGGER.info(
                "Removing leftover legacy lock %s (%s); Master Lock already exists as %s",
                entry.entity_id,
                entry.unique_id,
                existing_master_entity_id,
            )
            registry.async_remove(entry.entity_id)
            continue

        disabled_by = entry.disabled_by
        name = entry.name
        icon = entry.icon
        area_id = entry.area_id
        labels = set(entry.labels) if entry.labels else set()
        categories = dict(entry.categories) if entry.categories else {}
        device_registry_id = entry.device_id

        _LOGGER.info(
            "Migrating legacy lock %s (%s) to Master Lock unique_id %s "
            "(entity_id will not be preserved)",
            entry.entity_id,
            entry.unique_id,
            master_unique_id,
        )
        registry.async_remove(entry.entity_id)

        new_entry = registry.async_get_or_create(
            "lock",
            DOMAIN,
            master_unique_id,
            config_entry=config_entry,
            device_id=device_registry_id,
            disabled_by=disabled_by,
            suggested_object_id="master_lock",
            translation_key="master_lock",
            has_entity_name=True,
        )

        registry.async_update_entity(
            new_entry.entity_id,
            name=name,
            icon=icon,
            area_id=area_id,
            labels=labels,
            categories=categories,
        )

        _LOGGER.debug(
            "Created Master Lock registry entry %s (unique_id=%s, disabled_by=%s)",
            new_entry.entity_id,
            master_unique_id,
            disabled_by,
        )
