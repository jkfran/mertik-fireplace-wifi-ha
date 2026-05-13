import logging

from homeassistant import config_entries, core
from homeassistant.const import CONF_HOST
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import MertikDataCoordinator
from .mertik import Mertik

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "number", "sensor", "light", "climate", "select"]


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up the Mertik component."""
    try:
        mertik = await hass.async_add_executor_job(Mertik, entry.data[CONF_HOST])
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Unable to connect to fireplace at {entry.data[CONF_HOST]}"
        ) from err

    entry.runtime_data = MertikDataCoordinator(hass, mertik)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_setup(hass: core.HomeAssistant, config: dict) -> bool:
    return True


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
