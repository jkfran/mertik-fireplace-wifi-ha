"""Diagnostics download."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

from custom_components.mertik.const import CONF_TEMPERATURE_SENSOR
from custom_components.mertik.diagnostics import async_get_config_entry_diagnostics

from .conftest import HOST, MAC, poll
from .fakes import FakeBox, FakeFireplace


async def test_diagnostics(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace
) -> None:
    fire.lit(5)
    fire.set(room=0x00D2, light=True, light_level=0xFB, aux=True)
    await poll(hass, coordinator)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["state"] == {
        "state": "on",
        "available": True,
        "receiver_connected": True,
        "receiver_lost": False,
        "handset_connected": True,
        "fault_stored": True,
        "flame_height": 5,
        "mode": "manual",
        "thermostat_by_home_assistant": False,
        "thermostat_active": False,
    }
    assert result["status"] == {
        "setup_state": "47",
        "burner_output": 0xAE,
        "word": "808F",
        "light_level": "FB",
        "fan_level": 0,
        "mode_character": "0",
        "flags": "00",
        "room_temperature": 21.0,
        "target_temperature": 20.0,
    }
    assert result["last_frame"] == fire.box.status
    json.dumps(result)  # it has to be serialisable


async def test_diagnostics_hide_the_address_and_mac(
    hass: HomeAssistant, entry, box: FakeBox, fire: FakeFireplace
) -> None:
    # The device info reply carries the MAC address in the middle.
    box.device_info = "005400000000" + "0500233CAABBCC1602" + "5A38382E70313331"
    hass.config_entries.async_update_entry(
        entry, options={CONF_TEMPERATURE_SENSOR: "sensor.room"}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["entry"]["data"]["host"] == "**REDACTED**"
    assert result["entry"]["data"]["mac"] == "**REDACTED**"
    assert result["entry"]["data"]["name"] == "Fireplace"
    assert result["entry"]["options"] == {CONF_TEMPERATURE_SENSOR: "sensor.room"}
    assert result["state"]["thermostat_by_home_assistant"] is True
    assert result["device_info"] == "00540000000005**REDACTED**16025A38382E70313331"

    text = json.dumps(result).lower()
    assert HOST not in text
    assert MAC not in text
    assert MAC.replace(":", "") not in text


async def test_diagnostics_before_any_status(hass: HomeAssistant, entry, coordinator) -> None:
    """Nothing here depends on a status having been decoded."""
    coordinator.mertik._status = None

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["status"] is None
    assert result["state"]["state"] is None
