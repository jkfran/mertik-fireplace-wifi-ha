"""Operating mode: manual, the fireplace's own thermostat, eco."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .conftest import call, entity_id, poll, settled
from .fakes import FakeBox, FakeClock, FakeFireplace


@pytest.fixture
def select(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "select", "Mode")


@pytest.mark.parametrize(
    ("character", "option"), [("0", "manual"), ("1", "thermostat"), ("2", "eco")]
)
async def test_mode_follows_the_fireplace(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    select: str,
    character: str,
    option: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    fire.set(mode=character)
    await settled(hass, coordinator, clock)

    state = hass.states.get(select)
    assert state.state == option
    assert state.attributes["options"] == ["manual", "thermostat", "eco"]


async def test_select_eco_and_back(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, select: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)

    await call(hass, "select", "select_option", select, option="eco")
    assert box.commands == ["B301"]
    assert hass.states.get(select).state == "eco"

    await call(hass, "select", "select_option", select, option="manual")
    assert box.commands == ["B301", "B0"]
    assert hass.states.get(select).state == "manual"


async def test_select_thermostat_uses_the_fireplace_target(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, select: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    fire.set(target=0x00E6, room=0x00D2)  # target 23.0; the handset reports 21.0
    await settled(hass, coordinator, clock)

    await call(hass, "select", "select_option", select, option="thermostat")

    assert box.commands == ["B201", "B2FD00E6"]
    assert hass.states.get(select).state == "thermostat"


@pytest.mark.parametrize("option", ["eco", "thermostat"])
async def test_eco_and_thermostat_need_a_fire(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    select: str,
    option: str,
) -> None:
    fire.set(room=0x00D2)
    await poll(hass, coordinator)
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "select", "select_option", select, option=option)

    assert error.value.translation_key == "fireplace_off"
    assert box.commands == []


async def test_mode_chosen_while_igniting_waits_for_the_fire(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    select: str,
) -> None:
    await call(hass, "switch", "turn_on", entity_id(hass, entry, "switch", "OnOff"))
    await call(hass, "select", "select_option", select, option="eco")
    assert box.commands == ["1A"]

    fire.lit(12)
    clock.advance(61)
    await poll(hass, coordinator)

    assert box.commands == ["1A", "B301"]
    assert hass.states.get(select).state == "eco"
