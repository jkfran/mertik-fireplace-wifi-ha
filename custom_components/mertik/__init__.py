import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import MertikDataCoordinator
from .mertik import Mertik

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "number", "sensor", "light", "climate", "select"]

type MertikConfigEntry = ConfigEntry[MertikDataCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MertikConfigEntry) -> bool:
    """Set up the Mertik component."""
    try:
        mertik = await hass.async_add_executor_job(Mertik, entry.data[CONF_HOST])
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Unable to connect to fireplace at {entry.data[CONF_HOST]}"
        ) from err

    coordinator = MertikDataCoordinator(hass, mertik, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MertikConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.mertik.close)
    return unloaded
