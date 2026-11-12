"""Diagnostics: what the fireplace reports, for bug reports and protocol work."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_MAC
from .coordinator import MertikConfigEntry

TO_REDACT = {CONF_HOST, CONF_MAC}
REDACTED = "**REDACTED**"


WITHHELD = "withheld: it holds the MAC address, which this entry does not know"


def _without_mac(text: str | None, mac: str | None) -> str | None:
    """Remove the MAC address from a raw reply, or keep the reply back."""
    if text is None:
        return None
    if mac is None:
        return WITHHELD
    compact = mac.replace(":", "")
    for variant in (compact.upper(), compact.lower()):
        text = text.replace(variant, REDACTED)
    return text


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MertikConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    mertik = coordinator.mertik
    status = mertik.status
    mac = entry.data.get(CONF_MAC)
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "state": {
            "state": coordinator.state,
            "available": coordinator.available,
            "receiver_connected": mertik.receiver_connected,
            "receiver_lost": mertik.receiver_lost,
            "handset_connected": mertik.handset_connected,
            "fault_stored": mertik.is_faulted,
            "flame_height": mertik.flame_height,
            "mode": mertik.mode,
            "thermostat_by_home_assistant": coordinator.temperature_sensor is not None,
            "thermostat_active": coordinator.is_thermostat_on,
        },
        "status": None
        if status is None
        else {
            "setup_state": f"{status.setup_state:02X}",
            "burner_output": status.burner_output,
            "word": f"{status.word:04X}",
            "light_level": f"{status.light_level:02X}",
            "fan_level": status.fan_level,
            "mode_character": status.mode_character,
            "flags": f"{status.flags:02X}",
            "room_temperature": status.room_temperature,
            "target_temperature": status.target_temperature,
        },
        "last_frame": mertik.last_frame,
        "device_info": _without_mac(mertik.device_info, mac),
    }
