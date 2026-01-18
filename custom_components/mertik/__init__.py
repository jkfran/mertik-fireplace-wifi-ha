from homeassistant import config_entries, core
from homeassistant.const import CONF_HOST

from .const import DOMAIN
from .mertik import Mertik
from .mertikdatacoordinator import MertikDataCoordinator


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    mertik = Mertik(entry.data[CONF_HOST])

    """Set up the Mertik component."""
    coordinator = MertikDataCoordinator(hass, mertik)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to all platforms directly.
    await hass.config_entries.async_forward_entry_setups(
        entry, ["switch", "number", "sensor", "light"]
    )

    return True


async def async_setup(hass: core.HomeAssistant, config: dict) -> bool:
    return True


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["switch", "number", "sensor", "light"]
    )
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
