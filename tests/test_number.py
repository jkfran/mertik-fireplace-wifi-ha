"""Flame height."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .conftest import call, entity_id, poll, settled
from .fakes import FakeBox, FakeClock, FakeFireplace


@pytest.fixture
def number(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "number", "FlameHeight")


async def test_range(hass: HomeAssistant, number: str) -> None:
    """Twelve steps like the handset, and 0 for standby."""
    attributes = hass.states.get(number).attributes
    assert attributes["min"] == 0
    assert attributes["max"] == 12
    assert attributes["step"] == 1


@pytest.mark.parametrize(
    ("output", "step"),
    [
        (0x80, 1),
        (0x8B, 2),
        (0x97, 3),
        (0xA2, 4),
        (0xAE, 5),
        (0xB9, 6),
        (0xC5, 7),
        (0xD0, 8),
        (0xDC, 9),
        (0xE7, 10),
        (0xF3, 11),
        (0xFF, 12),
        # Between two steps (thermostat and eco modulate freely): the nearest.
        (0x69, 1),
        (0x90, 2),
        (0xFA, 12),
    ],
)
async def test_flame_height_is_the_step_nearest_to_the_burner_output(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    number: str,
    output: int,
    step: int,
    clock: FakeClock,
) -> None:
    fire.set(pilot=True, output=output)
    await settled(hass, coordinator, clock)

    state = hass.states.get(number)
    assert float(state.state) == step
    assert state.attributes["burner_output"] == output


async def test_flame_height_is_zero_without_a_main_flame(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, number: str,
    clock: FakeClock,
) -> None:
    fire.standby()
    await settled(hass, coordinator, clock)
    assert float(hass.states.get(number).state) == 0

    fire.off()
    await poll(hass, coordinator)
    assert float(hass.states.get(number).state) == 0

    # A cold fireplace can report a full burner output with its pilot out.
    fire.set(pilot=False, output=0xFF)
    await poll(hass, coordinator)
    assert float(hass.states.get(number).state) == 0


@pytest.mark.parametrize(
    ("value", "command"),
    [(1, "1680"), (3, "1697"), (8, "16D0"), (12, "16FF")],
)
async def test_set_flame_height(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    number: str,
    value: int,
    command: str,
    clock: FakeClock,
) -> None:
    fire.lit(6)
    await settled(hass, coordinator, clock)

    await call(hass, "number", "set_value", number, value=value)

    assert box.commands == [command]
    assert float(hass.states.get(number).state) == value


async def test_zero_turns_the_burner_down_to_the_pilot(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace, box: FakeBox, number: str,
    clock: FakeClock,
) -> None:
    fire.lit(6)
    await settled(hass, coordinator, clock)

    await call(hass, "number", "set_value", number, value=0)

    assert box.commands == ["1600"]
    assert float(hass.states.get(number).state) == 0
    assert hass.states.get(entity_id(hass, entry, "sensor", "Status")).state == "standby"
    # The fireplace stays on: its pilot burns.
    assert hass.states.get(entity_id(hass, entry, "switch", "OnOff")).state == "on"


async def test_flame_comes_back_up_from_standby(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace, box: FakeBox, number: str,
    clock: FakeClock,
) -> None:
    fire.standby()
    await settled(hass, coordinator, clock)

    await call(hass, "number", "set_value", number, value=5)

    assert box.commands == ["16AE"]
    assert hass.states.get(entity_id(hass, entry, "sensor", "Status")).state == "on"


async def test_requested_height_shows_while_the_valve_moves(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    number: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    box.on_command = None  # acknowledged, but the old output is still reported

    await call(hass, "number", "set_value", number, value=3)
    assert float(hass.states.get(number).state) == 3

    # A valve that never arrives is not covered up for long.
    clock.advance(13)
    await poll(hass, coordinator)
    assert float(hass.states.get(number).state) == 12


async def test_flame_height_needs_a_fire(
    hass: HomeAssistant, coordinator, box: FakeBox, number: str
) -> None:
    """Setting a flame never lights the fireplace."""
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "number", "set_value", number, value=5)

    assert error.value.translation_key == "fireplace_off"
    assert box.commands == []
