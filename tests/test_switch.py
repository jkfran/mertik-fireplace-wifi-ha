"""The fireplace switch (ignite, off) and the secondary burner."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .conftest import call, entity_id, poll, settled
from .fakes import FakeBox, FakeClock, FakeFireplace


@pytest.fixture
def switch(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "switch", "OnOff")


@pytest.fixture
def aux(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "switch", "AuxOnOff")


@pytest.fixture
def status(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "sensor", "Status")


async def test_turn_on_ignites_and_waits_for_the_fire_to_settle(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    assert hass.states.get(switch).state == "off"

    await call(hass, "switch", "turn_on", switch)

    assert box.commands == ["1A"]
    assert hass.states.get(switch).state == "on"
    assert hass.states.get(status).state == "igniting"

    # The pilot catches and the burner opens, but a fresh ignition has to hold.
    fire.lit(12)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "igniting"

    clock.advance(61)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "on"
    assert hass.states.get(switch).state == "on"
    assert box.commands == ["1A"]


@pytest.mark.parametrize("flame", [12, 0], ids=["burning", "standby"])
async def test_turn_on_does_not_ignite_a_fire_that_is_on(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    switch: str,
    flame: int,
    clock: FakeClock,
) -> None:
    """A second ignite would restart the ignition of a burning fire."""
    fire.lit(flame)
    await settled(hass, coordinator, clock)
    assert hass.states.get(switch).state == "on"

    await call(hass, "switch", "turn_on", switch)

    assert box.commands == []


async def test_turn_on_does_not_ignite_twice(
    hass: HomeAssistant, coordinator, box: FakeBox, switch: str
) -> None:
    await call(hass, "switch", "turn_on", switch)
    await call(hass, "switch", "turn_on", switch)

    assert box.commands == ["1A"]


async def test_turn_off(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    switch: str,
    status: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)

    await call(hass, "switch", "turn_off", switch)

    assert box.commands == ["10"]
    assert hass.states.get(switch).state == "off"
    assert hass.states.get(status).state == "shutting_down"

    fire.off()
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "off"


async def test_off_shows_at_once_even_if_the_box_is_slow_to_report_it(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    box.on_command = None  # the box keeps reporting the fire as burning

    await call(hass, "switch", "turn_off", switch)
    assert hass.states.get(status).state == "shutting_down"

    # It does not stay that way if the fire really keeps burning: the status
    # shows what the box reports, and the off is sent again.
    clock.advance(21)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "on"
    assert hass.states.get(switch).state == "off"
    assert box.commands == ["10", "10"]


async def test_turn_on_is_refused_while_shutting_down_and_just_after(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    """The receiver ignores an ignition during a shutdown and right after it."""
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "switch", "turn_off", switch)

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "switch", "turn_on", switch)
    assert error.value.translation_key == "shutting_down"

    fire.off()
    await poll(hass, coordinator)
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "switch", "turn_on", switch)
    assert error.value.translation_key == "shutting_down"
    assert box.commands == ["10"]

    clock.advance(16)
    await call(hass, "switch", "turn_on", switch)
    assert box.commands == ["10", "1A"]


async def test_a_cold_fireplace_can_be_ignited_right_away(
    hass: HomeAssistant, coordinator, box: FakeBox, switch: str
) -> None:
    """The wait after a shutdown only applies to one that was seen."""
    await call(hass, "switch", "turn_on", switch)
    assert box.commands == ["1A"]


async def test_failed_ignition_ends_up_off(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    await call(hass, "switch", "turn_on", switch)
    # The pilot does not catch: the box reports the fireplace off again.
    fire.off()

    # "Off" does not end an ignition: the receiver tries several times and
    # reports off between two attempts. A minute without a sign of it does.
    clock.advance(40)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "igniting"

    clock.advance(21)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "off"
    assert hass.states.get(switch).state == "off"


async def test_fire_lit_with_the_handset_is_followed(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    fire.set(igniting=True)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "igniting"
    assert hass.states.get(switch).state == "on"

    fire.lit(12)
    clock.advance(61)
    await settled(hass, coordinator, clock)
    assert hass.states.get(status).state == "on"


async def test_secondary_burner(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, aux: str,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    assert hass.states.get(aux).state == "off"

    await call(hass, "switch", "turn_on", aux)
    assert box.commands == ["2001"]
    assert hass.states.get(aux).state == "on"

    await call(hass, "switch", "turn_off", aux)
    assert box.commands == ["2001", "2000"]
    assert hass.states.get(aux).state == "off"


async def test_secondary_burner_reads_off_while_the_fireplace_is_off(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, aux: str
) -> None:
    """The box keeps the bit of the last fire; nothing burns with the fire off."""
    fire.set(aux=True)
    await poll(hass, coordinator)
    assert hass.states.get(aux).state == "off"

    # Turning it off is already the case; turning it on needs a fire.
    await call(hass, "switch", "turn_off", aux)
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "switch", "turn_on", aux)
    assert error.value.translation_key == "fireplace_off"
    assert box.commands == []


async def test_secondary_burner_request_shows_until_the_box_reports_it(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    aux: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    box.on_command = None  # the box acknowledges, its status lags behind

    await call(hass, "switch", "turn_on", aux)
    assert hass.states.get(aux).state == "on"

    # If the report never comes, what the box says wins.
    clock.advance(13)
    await poll(hass, coordinator)
    assert hass.states.get(aux).state == "off"


async def test_commands_given_while_igniting_wait_for_the_fire(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    aux: str,
) -> None:
    """The receiver must be left alone while it lights the fire."""
    number = entity_id(hass, entry, "number", "FlameHeight")
    await call(hass, "switch", "turn_on", switch)

    await call(hass, "number", "set_value", number, value=4)
    await call(hass, "switch", "turn_on", aux)

    assert box.commands == ["1A"]
    assert float(hass.states.get(number).state) == 4
    assert hass.states.get(aux).state == "on"

    fire.lit(12)
    await poll(hass, coordinator)
    assert box.commands == ["1A"]  # still settling

    clock.advance(61)
    await poll(hass, coordinator)

    # Secondary burner first: it is refused while the valve moves to a new flame.
    assert box.commands == ["1A", "2001", "16A2"]
    assert float(hass.states.get(number).state) == 4
    assert hass.states.get(aux).state == "on"


async def test_commands_waiting_for_the_fire_are_dropped_if_it_does_not_light(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    number = entity_id(hass, entry, "number", "FlameHeight")
    await call(hass, "switch", "turn_on", switch)
    await call(hass, "number", "set_value", number, value=4)

    fire.off()
    clock.advance(61)
    await poll(hass, coordinator)
    assert float(hass.states.get(number).state) == 0

    # A fire lit later does not get the old request.
    fire.lit(12)
    clock.advance(600)
    await settled(hass, coordinator, clock)
    assert box.commands == ["1A"]
    assert float(hass.states.get(number).state) == 12


async def test_commands_waiting_for_the_fire_expire(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    """An ignition that never ends does not hold a command for ever."""
    number = entity_id(hass, entry, "number", "FlameHeight")
    await call(hass, "switch", "turn_on", switch)
    await call(hass, "number", "set_value", number, value=4)

    clock.advance(301)
    await poll(hass, coordinator)  # the box still reports the ignition

    fire.lit(12)
    clock.advance(61)
    await poll(hass, coordinator)
    assert box.commands == ["1A"]


async def test_turning_off_drops_what_was_waiting(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    number = entity_id(hass, entry, "number", "FlameHeight")
    await call(hass, "switch", "turn_on", switch)
    await call(hass, "number", "set_value", number, value=4)

    await call(hass, "switch", "turn_off", switch)

    assert box.commands == ["1A", "10"]
    assert float(hass.states.get(number).state) == 0
