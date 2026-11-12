"""Sensors and binary sensors."""

from __future__ import annotations

import pytest

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.mertik.const import DOMAIN

from .conftest import HOST, entity_id, poll, settled
from .fakes import FakeBox, FakeClock, FakeFireplace


@pytest.fixture
def all_enabled(hass: HomeAssistant, entry) -> None:
    """Enable the entities that are disabled by default (before setup)."""
    registry = er.async_get(hass)
    for platform, key in (
        ("sensor", "FanLevel"),
        ("sensor", "IPAddress"),
        ("binary_sensor", "Igniting"),
        ("binary_sensor", "ShuttingDown"),
        ("binary_sensor", "Fault"),
        ("binary_sensor", "Fan"),
    ):
        registry.async_get_or_create(
            platform, DOMAIN, f"{entry.entry_id}-{key}", config_entry=entry
        )


def state_of(hass: HomeAssistant, entry, platform: str, key: str) -> str:
    return hass.states.get(entity_id(hass, entry, platform, key)).state


async def test_ambient_temperature(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace
) -> None:
    fire.set(room=0x00D7)
    await poll(hass, coordinator)

    state = hass.states.get(entity_id(hass, entry, "sensor", "AmbientTemperature"))
    assert float(state.state) == 21.5
    assert state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["device_class"] == "temperature"
    assert state.attributes["state_class"] == "measurement"


async def test_ambient_temperature_is_unknown_without_a_handset(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace
) -> None:
    """Without a handset reading the box reports 0666, which is not 163.8 degrees."""
    fire.set(room="0666")
    await poll(hass, coordinator)

    assert state_of(hass, entry, "sensor", "AmbientTemperature") == STATE_UNKNOWN


async def test_status_sensor_follows_the_fire(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace, clock: FakeClock
) -> None:
    status = entity_id(hass, entry, "sensor", "Status")
    assert hass.states.get(status).state == "off"
    assert hass.states.get(status).attributes["options"] == [
        "off",
        "standby",
        "igniting",
        "on",
        "shutting_down",
    ]

    fire.set(igniting=True)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "igniting"

    fire.lit(12)
    clock.advance(61)
    await settled(hass, coordinator, clock)
    assert hass.states.get(status).state == "on"

    fire.standby()
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "standby"

    fire.set(shutting_down=True)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "shutting_down"

    fire.off()
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "off"


async def test_pilot_flame(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace,
    clock: FakeClock,
) -> None:
    assert state_of(hass, entry, "binary_sensor", "PilotFlame") == "off"

    fire.standby()
    await settled(hass, coordinator, clock)
    assert state_of(hass, entry, "binary_sensor", "PilotFlame") == "on"

    fire.lit(7)
    await poll(hass, coordinator)
    assert state_of(hass, entry, "binary_sensor", "PilotFlame") == "on"

    # A cold fireplace reporting a full burner output has no pilot.
    fire.set(pilot=False, output=0xFF)
    await poll(hass, coordinator)
    assert state_of(hass, entry, "binary_sensor", "PilotFlame") == "off"


async def test_remote(hass: HomeAssistant, entry, coordinator, fire: FakeFireplace) -> None:
    """A handset shows by its status bit, or by the temperature it reports."""
    assert state_of(hass, entry, "binary_sensor", "RemoteConnection") == "off"

    fire.set(room=0x00D2)
    await poll(hass, coordinator)
    assert state_of(hass, entry, "binary_sensor", "RemoteConnection") == "on"

    fire.set(room="0666", handset=True)
    await poll(hass, coordinator)
    assert state_of(hass, entry, "binary_sensor", "RemoteConnection") == "on"


async def test_receiver_link(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace, clock: FakeClock
) -> None:
    """The receiver sensor stays readable while its link is what is missing."""
    assert state_of(hass, entry, "binary_sensor", "ReceiverConnection") == "on"

    fire.set(link=False)
    await poll(hass, coordinator)
    assert state_of(hass, entry, "binary_sensor", "ReceiverConnection") == "off"
    assert state_of(hass, entry, "sensor", "Status") == "off"

    clock.advance(46)
    await poll(hass, coordinator)
    assert state_of(hass, entry, "binary_sensor", "ReceiverConnection") == "off"
    assert state_of(hass, entry, "sensor", "Status") == STATE_UNAVAILABLE


async def test_entities_disabled_by_default(
    hass: HomeAssistant,
    entry,
    all_enabled,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
) -> None:
    assert state_of(hass, entry, "sensor", "IPAddress") == HOST
    assert state_of(hass, entry, "sensor", "FanLevel") == "0"
    assert state_of(hass, entry, "binary_sensor", "Fan") == "off"
    assert state_of(hass, entry, "binary_sensor", "Igniting") == "off"
    assert state_of(hass, entry, "binary_sensor", "ShuttingDown") == "off"
    # A fireplace whose handset does not report keeps the fault F44 stored.
    assert state_of(hass, entry, "binary_sensor", "Fault") == "on"

    fire.set(fan=True, fan_level=3, igniting=True)
    await poll(hass, coordinator)
    assert state_of(hass, entry, "sensor", "FanLevel") == "3"
    assert state_of(hass, entry, "binary_sensor", "Fan") == "on"
    assert state_of(hass, entry, "binary_sensor", "Igniting") == "on"

    fire.set(igniting=False, pilot=True, shutting_down=True)
    await poll(hass, coordinator)
    assert state_of(hass, entry, "binary_sensor", "ShuttingDown") == "on"

    # The address stays readable when the fireplace does not answer.
    box.fail_connects = 2
    await poll(hass, coordinator)
    assert state_of(hass, entry, "sensor", "Status") == STATE_UNAVAILABLE
    assert state_of(hass, entry, "sensor", "IPAddress") == HOST
