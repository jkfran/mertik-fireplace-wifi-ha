"""The thermostat entity, in both of its forms.

Without a temperature sensor in the options it drives the fireplace's own
thermostat mode. With one, Home Assistant regulates the flame itself. Neither
ever ignites the fireplace.
"""

from __future__ import annotations

import logging

import pytest
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError

from custom_components.mertik.const import CONF_TEMPERATURE_SENSOR

from .conftest import call, entity_id, poll, settled
from .fakes import FakeBox, FakeClock, FakeFireplace

ROOM = "sensor.room"
CLIMATE = "climate.fireplace_thermostat"


def set_room(hass: HomeAssistant, value: str, unit: str = "°C") -> None:
    hass.states.async_set(
        ROOM, value, {"unit_of_measurement": unit, "device_class": "temperature"}
    )


def restore(hass: HomeAssistant, state: str, **memory) -> None:
    """Put a thermostat of before the restart in the restore cache."""
    mock_restore_cache_with_extra_data(
        hass, [(State(CLIMATE, state, {"temperature": 72}), memory)]
    )


@pytest.fixture
def with_sensor(hass: HomeAssistant, entry) -> None:
    """Options: Home Assistant regulates on sensor.room (18 degrees to start)."""
    hass.config_entries.async_update_entry(
        entry, options={CONF_TEMPERATURE_SENSOR: ROOM}
    )
    set_room(hass, "18.0")


@pytest.fixture
def climate(hass: HomeAssistant, entry, coordinator) -> str:
    found = entity_id(hass, entry, "climate", "Thermostat")
    assert found == CLIMATE
    return found


# --- The fireplace's own thermostat ----------------------------------------------


async def test_own_thermostat_is_off_with_the_fire_off(
    hass: HomeAssistant, climate: str
) -> None:
    state = hass.states.get(climate)
    assert state.state == "off"
    assert state.attributes["hvac_modes"] == ["off", "heat"]
    assert state.attributes["hvac_action"] == "off"
    assert state.attributes["min_temp"] == 5
    assert state.attributes["max_temp"] == 36
    assert state.attributes["target_temp_step"] == 0.5
    # The target the fireplace keeps; no room temperature without a handset.
    assert state.attributes["temperature"] == 20.0
    assert state.attributes["current_temperature"] is None


async def test_own_thermostat_set_temperature_starts_it(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, climate: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    fire.set(room=0x00CD)  # 20.5 on the handset
    await settled(hass, coordinator, clock)
    assert hass.states.get(climate).state == "off"
    assert hass.states.get(climate).attributes["current_temperature"] == 20.5

    await call(hass, "climate", "set_temperature", climate, temperature=22.5)

    assert box.commands == ["B201", "B2FD00E1"]
    state = hass.states.get(climate)
    assert state.state == "heat"
    assert state.attributes["temperature"] == 22.5
    assert state.attributes["hvac_action"] == "heating"


async def test_own_thermostat_works_in_half_degrees(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, climate: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    fire.set(room=0x00D2)
    await settled(hass, coordinator, clock)

    await call(hass, "climate", "set_temperature", climate, temperature=21.3)

    assert box.commands == ["B201", "B2FD00D7"]  # 21.5


async def test_own_thermostat_is_idle_on_the_pilot(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, climate: str,
    clock: FakeClock,
) -> None:
    """Room warm enough: the fireplace turned itself down to the pilot."""
    fire.standby()
    fire.set(mode="1")
    await settled(hass, coordinator, clock)

    state = hass.states.get(climate)
    assert state.state == "heat"
    assert state.attributes["hvac_action"] == "idle"


async def test_own_thermostat_on_and_off(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, climate: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    fire.set(room=0x00D2)
    await settled(hass, coordinator, clock)

    await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="heat")
    assert box.commands == ["B201", "B2FD00C8"]  # the target it had: 20.0
    assert hass.states.get(climate).state == "heat"

    await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="off")
    assert box.commands == ["B201", "B2FD00C8", "B0"]
    state = hass.states.get(climate)
    assert state.state == "off"
    assert state.attributes["hvac_action"] == "off"
    # Off only ends the regulating; the fire burns on.
    assert "10" not in box.commands


async def test_own_thermostat_turn_on_and_turn_off_services(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, climate: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    fire.set(room=0x00D2)
    await settled(hass, coordinator, clock)

    await call(hass, "climate", "turn_on", climate)
    assert hass.states.get(climate).state == "heat"

    await call(hass, "climate", "turn_off", climate)
    assert hass.states.get(climate).state == "off"
    assert box.commands == ["B201", "B2FD00C8", "B0"]


async def test_own_thermostat_needs_a_fire(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, climate: str
) -> None:
    fire.set(room=0x00D2)
    await poll(hass, coordinator)
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "climate", "set_temperature", climate, temperature=22)
    assert error.value.translation_key == "fireplace_off"

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="heat")
    assert error.value.translation_key == "fireplace_off"

    assert box.commands == []


async def test_own_thermostat_set_while_igniting_waits_for_the_fire(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    fire.set(room=0x00D2)
    await poll(hass, coordinator)
    await call(hass, "switch", "turn_on", entity_id(hass, entry, "switch", "OnOff"))
    await call(hass, "climate", "set_temperature", climate, temperature=23)
    assert box.commands == ["1A"]
    assert hass.states.get(climate).state == "heat"

    fire.lit(12)
    clock.advance(61)
    await poll(hass, coordinator)

    assert box.commands == ["1A", "B201", "B2FD00E6"]
    assert hass.states.get(climate).state == "heat"


async def test_own_thermostat_needs_the_handset(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    """It measures with the handset. Without a reading it would regulate on nothing."""
    fire.lit(12)
    await settled(hass, coordinator, clock)
    assert hass.states.get(climate).attributes["current_temperature"] is None

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "climate", "set_temperature", climate, temperature=22)
    assert error.value.translation_key == "no_handset"
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="heat")
    assert error.value.translation_key == "no_handset"
    with pytest.raises(ServiceValidationError) as error:
        await call(
            hass,
            "select",
            "select_option",
            entity_id(hass, entry, "select", "Mode"),
            option="thermostat",
        )
    assert error.value.translation_key == "no_handset"
    assert box.commands == []


async def test_out_of_range_target_from_the_fireplace_is_not_shown(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, climate: str
) -> None:
    fire.set(target=0x0000)
    await poll(hass, coordinator)

    assert hass.states.get(climate).attributes["temperature"] is None


# --- Home Assistant regulating on a sensor -----------------------------------------


async def test_ha_thermostat_reads_the_sensor(
    hass: HomeAssistant, with_sensor, climate: str
) -> None:
    state = hass.states.get(climate)
    assert state.state == "off"
    assert state.attributes["current_temperature"] == 18.0
    assert state.attributes["temperature"] == 20.0


async def test_ha_thermostat_reads_a_fahrenheit_sensor(
    hass: HomeAssistant, with_sensor, coordinator, climate: str
) -> None:
    set_room(hass, "68", "°F")
    await poll(hass, coordinator)

    assert hass.states.get(climate).attributes["current_temperature"] == 20.0


@pytest.mark.parametrize("value", ["unavailable", "unknown", "", "warm", "nan", "inf"])
async def test_ha_thermostat_takes_only_numbers_for_a_reading(
    hass: HomeAssistant, with_sensor, coordinator, climate: str, value: str
) -> None:
    hass.states.async_set(ROOM, value)
    await poll(hass, coordinator)

    assert hass.states.get(climate).attributes["current_temperature"] is None


async def test_ha_thermostat_without_its_sensor_entity(
    hass: HomeAssistant, with_sensor, coordinator, climate: str
) -> None:
    hass.states.async_remove(ROOM)
    await poll(hass, coordinator)

    assert hass.states.get(climate).attributes["current_temperature"] is None


async def test_ha_thermostat_never_ignites(
    hass: HomeAssistant, with_sensor, coordinator, box: FakeBox, climate: str
) -> None:
    """A cold room is no reason to light a gas fire unattended."""
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="heat")
    assert error.value.translation_key == "fireplace_off"

    await poll(hass, coordinator)
    assert box.commands == []
    assert hass.states.get(climate).state == "off"


async def test_ha_thermostat_keeps_a_target_set_while_off(
    hass: HomeAssistant, with_sensor, coordinator, box: FakeBox, climate: str
) -> None:
    await call(hass, "climate", "set_temperature", climate, temperature=22)

    state = hass.states.get(climate)
    assert state.state == "off"
    assert state.attributes["temperature"] == 22.0
    assert box.commands == []


async def test_ha_thermostat_regulates_the_flame(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)

    # Cold room, fire at full: nothing to change.
    await call(hass, "climate", "set_temperature", climate, temperature=21)
    state = hass.states.get(climate)
    assert state.state == "heat"
    assert state.attributes["hvac_action"] == "heating"
    assert box.commands == []

    # Warm enough: down to the pilot.
    set_room(hass, "21.4")
    await poll(hass, coordinator)
    assert box.commands == ["1600"]
    assert hass.states.get(climate).state == "heat"
    assert hass.states.get(climate).attributes["hvac_action"] == "idle"

    # Cooling off again, but the flame was changed a moment ago.
    set_room(hass, "20.6")
    await poll(hass, coordinator)
    assert box.commands == ["1600"]

    clock.advance(121)
    await poll(hass, coordinator)
    assert box.commands == ["1600", "1680"]  # low flame
    assert hass.states.get(climate).attributes["hvac_action"] == "heating"

    # A degree or more short: full flame.
    set_room(hass, "19.9")
    clock.advance(121)
    await poll(hass, coordinator)
    assert box.commands == ["1600", "1680", "16FF"]

    # Nearly there: back to the low flame.
    set_room(hass, "20.6")
    clock.advance(121)
    await poll(hass, coordinator)
    assert box.commands == ["1600", "1680", "16FF", "1680"]

    # It only ever moved the flame.
    assert set(box.commands) <= {"1600", "1680", "16FF"}


async def test_ha_thermostat_takes_the_fireplace_out_of_its_own_modes(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    climate: str,
    clock: FakeClock,
) -> None:
    """Two thermostats on one flame would fight."""
    fire.lit(12)
    fire.set(mode="1")
    await settled(hass, coordinator, clock)

    await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="heat")

    assert box.commands == ["B0"]
    assert hass.states.get(climate).state == "heat"


async def test_ha_thermostat_goes_to_the_pilot_when_the_sensor_is_lost(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "climate", "set_temperature", climate, temperature=21)

    hass.states.async_set(ROOM, "unavailable")
    await poll(hass, coordinator)
    assert box.commands == []  # a short gap is tolerated
    assert hass.states.get(climate).attributes["current_temperature"] is None

    clock.advance(301)
    with caplog.at_level(logging.WARNING):
        await poll(hass, coordinator)
    assert box.commands == ["1600"]
    assert "no reading from sensor.room" in caplog.text

    # The sensor returns and the room is cold: heat again, once the interval allows.
    set_room(hass, "18.0")
    clock.advance(121)
    await poll(hass, coordinator)
    assert box.commands == ["1600", "16FF"]


async def test_ha_thermostat_does_not_repeat_itself_while_the_valve_moves(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    """The fireplace reports its flame for a while after being told to go down."""
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "climate", "set_temperature", climate, temperature=21)
    box.on_command = None  # acknowledged, but the flame is still reported

    hass.states.async_set(ROOM, "unavailable")
    await poll(hass, coordinator)
    clock.advance(301)
    await poll(hass, coordinator)
    assert box.commands == ["1600"]

    for _ in range(3):
        clock.advance(10)
        await poll(hass, coordinator)
    assert box.commands == ["1600"]

    # Still a flame two minutes later: the command did not take, so once more.
    clock.advance(121)
    await poll(hass, coordinator)
    assert box.commands == ["1600", "1600"]

    # The same holds with a reading: warm room, flame reported, one command.
    set_room(hass, "25.0")
    for _ in range(3):
        clock.advance(10)
        await poll(hass, coordinator)
    assert box.commands == ["1600", "1600"]


async def test_ha_thermostat_stops_when_the_flame_is_set_by_hand(
    hass: HomeAssistant,
    entry,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "climate", "set_temperature", climate, temperature=21)

    number = entity_id(hass, entry, "number", "FlameHeight")
    await call(hass, "number", "set_value", number, value=5)
    assert hass.states.get(climate).state == "off"

    set_room(hass, "25.0")
    clock.advance(121)
    await poll(hass, coordinator)
    assert box.commands == ["16AE"]


async def test_ha_thermostat_off_leaves_the_fire_as_it_is(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "climate", "set_temperature", climate, temperature=21)

    await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="off")
    assert hass.states.get(climate).state == "off"

    set_room(hass, "25.0")
    clock.advance(121)
    await poll(hass, coordinator)
    assert box.commands == []


async def test_ha_thermostat_ends_with_the_fire(
    hass: HomeAssistant,
    entry,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    """Lighting the fire again later does not bring the thermostat back."""
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "climate", "set_temperature", climate, temperature=21)

    await call(hass, "switch", "turn_off", entity_id(hass, entry, "switch", "OnOff"))
    fire.off()
    await poll(hass, coordinator)
    assert hass.states.get(climate).state == "off"

    fire.lit(12)
    set_room(hass, "25.0")
    clock.advance(600)
    await poll(hass, coordinator)
    assert hass.states.get(climate).state == "off"
    assert box.commands == ["10"]


async def test_ha_thermostat_set_while_igniting_starts_once_lit(
    hass: HomeAssistant,
    entry,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    await call(hass, "switch", "turn_on", entity_id(hass, entry, "switch", "OnOff"))
    set_room(hass, "22.0")
    await call(hass, "climate", "set_temperature", climate, temperature=21)

    state = hass.states.get(climate)
    assert state.state == "heat"
    assert state.attributes["hvac_action"] == "preheating"
    assert box.commands == ["1A"]

    fire.lit(12)
    clock.advance(61)
    await poll(hass, coordinator)

    # Lit, and the room is already warm: straight down to the pilot.
    assert box.commands == ["1A", "1600"]
    assert hass.states.get(climate).state == "heat"


async def test_ha_thermostat_stops_when_the_sensor_is_removed_from_the_options(
    hass: HomeAssistant,
    entry,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    climate: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "climate", "set_temperature", climate, temperature=21)

    hass.config_entries.async_update_entry(entry, options={})
    await hass.async_block_till_done()
    set_room(hass, "25.0")
    clock.advance(121)
    await poll(hass, coordinator)

    assert box.commands == []
    # Back to the fireplace's own thermostat, which is not running.
    assert hass.states.get(climate).state == "off"


# --- After a restart ------------------------------------------------------------------


async def test_ha_thermostat_resumes_after_a_restart_if_the_fire_burns(
    hass: HomeAssistant, entry, with_sensor, fire: FakeFireplace, box: FakeBox
) -> None:
    restore(hass, "heat", target=22.5, active=True)
    fire.lit(12)
    set_room(hass, "23.5")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(CLIMATE)
    assert state.state == "heat"
    assert state.attributes["temperature"] == 22.5

    await poll(hass, entry.runtime_data)
    assert box.commands == ["1600"]


async def test_ha_thermostat_does_not_resume_with_the_fire_off(
    hass: HomeAssistant, entry, with_sensor, fire: FakeFireplace, box: FakeBox
) -> None:
    restore(hass, "heat", target=22.5, active=True)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await poll(hass, entry.runtime_data)

    state = hass.states.get(CLIMATE)
    assert state.state == "off"
    assert state.attributes["temperature"] == 22.5  # the target is kept
    assert box.commands == []


async def test_ha_thermostat_stays_off_after_a_restart_if_it_was_off(
    hass: HomeAssistant, entry, with_sensor, fire: FakeFireplace, box: FakeBox
) -> None:
    restore(hass, "off", target=22.5, active=False)
    fire.lit(12)
    set_room(hass, "25.0")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await poll(hass, entry.runtime_data)

    assert hass.states.get(CLIMATE).state == "off"
    assert box.commands == []


async def test_restored_state_does_not_touch_the_own_thermostat(
    hass: HomeAssistant, entry, fire: FakeFireplace, box: FakeBox
) -> None:
    restore(hass, "heat", target=22.5, active=True)
    fire.lit(12)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await poll(hass, entry.runtime_data)

    state = hass.states.get(CLIMATE)
    assert state.state == "off"  # the fireplace is in manual mode
    assert state.attributes["temperature"] == 20.0  # and reports its own target
    assert box.commands == []
