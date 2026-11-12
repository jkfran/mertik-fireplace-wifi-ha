"""Availability, errors and repairs."""

from __future__ import annotations

import logging

import pytest

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from custom_components.mertik.const import DOMAIN

from .conftest import call, entity_id, poll
from .fakes import NO_RECEIVER, FakeBox, FakeClock, FakeFireplace, framed


@pytest.fixture
def switch(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "switch", "OnOff")


def issue(hass: HomeAssistant, entry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"receiver_lost_{entry.entry_id}")


async def test_unavailable_while_the_box_does_not_answer(
    hass: HomeAssistant, coordinator, box: FakeBox, switch: str
) -> None:
    box.fail_connects = 2  # the request and its one retry
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == STATE_UNAVAILABLE

    await poll(hass, coordinator)
    assert hass.states.get(switch).state == "off"


async def test_one_failed_attempt_is_retried_unnoticed(
    hass: HomeAssistant, coordinator, box: FakeBox, switch: str
) -> None:
    box.fail_connects = 1
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == "off"


async def test_ignition_does_not_make_the_fireplace_unavailable(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    clock: FakeClock,
    switch: str,
) -> None:
    """The box drops its receiver link for 20-30 s during every ignition."""
    await call(hass, "switch", "turn_on", switch)
    # While the link is down the box reports nonsense: pilot out, no ignition.
    fire.set(link=False, igniting=False)

    for _ in range(3):
        clock.advance(10)
        await poll(hass, coordinator)
        assert hass.states.get(switch).state == "on"
        assert hass.states.get(entity_id(hass, entry, "sensor", "Status")).state == "igniting"
    assert issue(hass, entry) is None


async def test_lost_receiver_link_makes_the_fireplace_unavailable(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    clock: FakeClock,
    switch: str,
) -> None:
    """Without the link nothing the box says about the fire can be trusted."""
    fire.lit(12)
    await poll(hass, coordinator)

    fire.set(link=False, pilot=False, output=0x00)
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == "on"  # the last reliable state
    assert issue(hass, entry) is None

    clock.advance(46)
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == STATE_UNAVAILABLE
    found = issue(hass, entry)
    assert found is not None
    assert found.translation_key == "receiver_lost"
    assert found.translation_placeholders == {"name": "Fireplace"}
    assert found.severity is ir.IssueSeverity.WARNING
    assert not found.is_fixable

    # The link returns: the box's word counts again, and the repair goes away.
    fire.set(link=True)
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == "off"
    assert issue(hass, entry) is None


async def test_box_answering_no_receiver_to_polls(
    hass: HomeAssistant,
    entry,
    coordinator,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    """Some boxes answer every request with E101 instead of clearing a bit."""
    box.no_receiver = True
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == "off"
    receiver = entity_id(hass, entry, "binary_sensor", "ReceiverConnection")
    assert hass.states.get(receiver).state == "off"

    clock.advance(46)
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == STATE_UNAVAILABLE
    assert issue(hass, entry) is not None

    box.no_receiver = False
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == "off"
    assert hass.states.get(receiver).state == "on"
    assert issue(hass, entry) is None


async def test_command_refused_for_lack_of_a_receiver(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace, box: FakeBox
) -> None:
    fire.lit(12)
    await poll(hass, coordinator)
    box.no_receiver = True

    with pytest.raises(HomeAssistantError) as error:
        await call(
            hass,
            "number",
            "set_value",
            entity_id(hass, entry, "number", "FlameHeight"),
            value=3,
        )

    assert not isinstance(error.value, ServiceValidationError)
    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == "no_receiver"
    # Sent, refused, and tried once more.
    assert box.commands == ["1697", "1697"]


async def test_command_to_an_unreachable_box(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace, box: FakeBox
) -> None:
    fire.lit(12)
    await poll(hass, coordinator)
    box.fail_connects = 2

    with pytest.raises(HomeAssistantError) as error:
        await call(
            hass, "light", "turn_on", entity_id(hass, entry, "light", "Light")
        )

    assert error.value.translation_key == "cannot_reach"
    assert "192.168.1.100" in error.value.translation_placeholders["error"]
    assert box.commands == []


async def test_ignite_is_never_sent_twice(
    hass: HomeAssistant, coordinator, box: FakeBox, switch: str
) -> None:
    """An unanswered ignite is not repeated: the first one may have arrived."""
    box.script["1A"] = []  # received, never acknowledged

    with pytest.raises(HomeAssistantError) as error:
        await call(hass, "switch", "turn_on", switch)

    assert error.value.translation_key == "cannot_reach"
    assert box.requests.count("1A") == 1


async def test_failure_of_a_waiting_command_is_logged_not_raised(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await call(hass, "switch", "turn_on", switch)
    await call(
        hass, "number", "set_value", entity_id(hass, entry, "number", "FlameHeight"), value=4
    )
    box.script["16A2"] = [framed(NO_RECEIVER)]

    fire.lit(12)
    clock.advance(61)
    with caplog.at_level(logging.WARNING):
        await poll(hass, coordinator)

    assert "Mertik Fireplace" in caplog.text
    # It is not tried again on every poll after that.
    sent = len(box.requests)
    await poll(hass, coordinator)
    assert box.requests[sent:] == ["03"]


async def test_status_read_after_a_command_may_fail(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace, box: FakeBox
) -> None:
    """The command went through; a failed read right after it is not an error."""
    fire.lit(12)
    await poll(hass, coordinator)
    number = entity_id(hass, entry, "number", "FlameHeight")
    box.script["03"] = []

    await call(hass, "number", "set_value", number, value=3)

    assert box.commands == ["1697"]
    assert float(hass.states.get(number).state) == 3


async def test_polls_keep_their_distance_from_commands(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
) -> None:
    """Two control commands are at least two seconds apart; polls are free."""
    fire.lit(12)
    await poll(hass, coordinator)
    number = entity_id(hass, entry, "number", "FlameHeight")

    await call(hass, "number", "set_value", number, value=3)
    first = clock.now
    await poll(hass, coordinator)
    assert clock.now == first  # the poll did not wait

    await call(hass, "number", "set_value", number, value=4)
    assert clock.now - first >= 2.0
