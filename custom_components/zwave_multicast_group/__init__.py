"""Z-Wave Multicast Group: group Z-Wave JS entities and drive them with one multicast frame."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_GROUP_TYPE

_LOGGER = logging.getLogger(__name__)


def _platforms(entry: ConfigEntry) -> list[Platform]:
    return [Platform(entry.options[CONF_GROUP_TYPE])]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a multicast group from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a multicast group."""
    return await hass.config_entries.async_unload_platforms(entry, _platforms(entry))


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.1 -> 1.2: every 0.1.x group was a cover group; record that as its group type."""
    if entry.version > 1:
        return False  # from a newer release; don't guess
    if entry.minor_version < 2:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_GROUP_TYPE: entry.options.get(CONF_GROUP_TYPE, "cover")},
            minor_version=2,
        )
        _LOGGER.debug("Migrated %s to 1.2 (group_type cover)", entry.title)
    return True
