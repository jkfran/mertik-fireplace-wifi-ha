"""Mertik Maxitrol fireplaces with a WiFi module."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceEntry

from .const import CONF_MAC, CONF_MODEL, DOMAIN
from .coordinator import MertikConfigEntry, MertikDataCoordinator
from .discovery import Module, discover, discover_host
from .mertik import Mertik, MertikError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MertikConfigEntry) -> bool:
    """Set up a fireplace."""
    host = entry.data[CONF_HOST]
    known_mac = entry.data.get(CONF_MAC)
    mertik: Mertik | None = None
    module: Module | None = None
    try:
        mertik = await hass.async_add_executor_job(Mertik, host)
    except MertikError as err:
        problem = f"Unable to connect to fireplace at {host}: {err}"
    else:
        module = await hass.async_add_executor_job(discover_host, host)
        if known_mac and module and module.mac != known_mac:
            # The address has gone to another fireplace, which must not be
            # controlled in this one's name.
            mertik = None
            problem = f"Another fireplace answers at {host}"

    if mertik is None:
        # The module is known by its MAC address: look for it at another address.
        if (moved := await _async_find_moved(hass, entry)) is None:
            raise ConfigEntryNotReady(problem)
        _LOGGER.info("Fireplace %s moved from %s to %s", entry.title, host, moved.host)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_HOST: moved.host}
        )
        try:
            mertik = await hass.async_add_executor_job(Mertik, moved.host)
        except MertikError as err:
            raise ConfigEntryNotReady(
                f"Unable to connect to fireplace at {moved.host}: {err}"
            ) from err
        module = moved

    _learn_identity(hass, entry, module)
    await hass.async_add_executor_job(mertik.read_device_info)

    entry.runtime_data = MertikDataCoordinator(hass, entry, mertik)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MertikConfigEntry) -> bool:
    """Unload a fireplace."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MertikConfigEntry, device: DeviceEntry
) -> bool:
    """Allow removing devices left over from older versions, not the fireplace itself."""
    return (DOMAIN, entry.entry_id) not in device.identifiers


async def _async_find_moved(hass: HomeAssistant, entry: MertikConfigEntry) -> Module | None:
    """Look for this entry's module at another address."""
    if (mac := entry.data.get(CONF_MAC)) is None:
        return None
    for module in await hass.async_add_executor_job(discover):
        if module.mac == mac and module.host != entry.data[CONF_HOST]:
            return module
    return None


@callback
def _learn_identity(
    hass: HomeAssistant, entry: MertikConfigEntry, module: Module | None
) -> None:
    """Remember the module's MAC address and name, and identify the entry by the MAC.

    Entries made before 2.0 are identified by their IP address. The MAC address
    is what lets the entry follow the module to a new address, and what tells
    this fireplace from another one that is given its address.
    """
    if module is None:
        return
    known_mac = entry.data.get(CONF_MAC)
    if known_mac is not None and known_mac != module.mac:
        return
    data = {**entry.data, CONF_MAC: module.mac, CONF_MODEL: module.name}
    taken = any(
        other.unique_id == module.mac and other.entry_id != entry.entry_id
        for other in hass.config_entries.async_entries(DOMAIN)
    )
    unique_id = entry.unique_id if taken else module.mac
    if data != dict(entry.data) or unique_id != entry.unique_id:
        hass.config_entries.async_update_entry(entry, data=data, unique_id=unique_id)
