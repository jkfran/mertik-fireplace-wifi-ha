"""What must never happen with a gas fire, each case found by trying to make it happen.

Three rules run through these tests:

* An ignite command only goes to a fireplace that has just been seen to be off,
  and never a second time into an ignition that may be under way.
* Being told to turn off is never dropped, forgotten or passed off as done.
* While the fireplace ignites or shuts down, nothing else is sent to it.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import threading

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.mertik.const import CONF_TEMPERATURE_SENSOR, DOMAIN
from custom_components.mertik.diagnostics import (
    WITHHELD,
    async_get_config_entry_diagnostics,
)

from .conftest import HOST, NAME, Network, call, entity_id, poll, settled
from .fakes import NO_RECEIVER, FakeBox, FakeClock, FakeFireplace, ack, framed

ROOM = "sensor.room"
CLIMATE = "climate.fireplace_thermostat"


def set_room(hass: HomeAssistant, value: str) -> None:
    hass.states.async_set(
        ROOM, value, {"unit_of_measurement": "°C", "device_class": "temperature"}
    )


@pytest.fixture
def with_sensor(hass: HomeAssistant, entry) -> None:
    hass.config_entries.async_update_entry(entry, options={CONF_TEMPERATURE_SENSOR: ROOM})
    set_room(hass, "18.0")


@pytest.fixture
def switch(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "switch", "OnOff")


@pytest.fixture
def status(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "sensor", "Status")


@pytest.fixture
def number(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "number", "FlameHeight")


# --- Never a second ignite -------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [[], [framed(NO_RECEIVER)]],
    ids=["no acknowledgement", "answered with no receiver"],
)
async def test_ignite_that_may_have_arrived_is_not_repeated(
    hass: HomeAssistant, coordinator, box: FakeBox, clock: FakeClock, switch: str, status: str, reply
) -> None:
    """The user sees an error and presses again; an automation retries."""
    box.script["1A"] = reply
    with pytest.raises(HomeAssistantError):
        await call(hass, "switch", "turn_on", switch)
    assert hass.states.get(status).state == "igniting"

    del box.script["1A"]
    clock.advance(5)
    await call(hass, "switch", "turn_on", switch)
    assert box.commands == ["1A"]


async def test_stray_no_receiver_does_not_fail_an_accepted_ignite(
    hass: HomeAssistant, coordinator, box: FakeBox, switch: str, status: str
) -> None:
    box.script["1A"] = [framed(NO_RECEIVER), framed(ack("1A"))]

    await call(hass, "switch", "turn_on", switch)

    assert box.commands == ["1A"]
    assert hass.states.get(status).state == "igniting"


async def test_no_ignite_into_an_ignition_started_with_the_handset(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    """The polls only caught frames without the receiver link."""
    fire.set(link=False, igniting=True)
    clock.advance(10)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "igniting"
    assert hass.states.get(switch).state == "on"

    await call(hass, "switch", "turn_on", switch)
    assert box.commands == []


async def test_no_ignite_while_nothing_is_known_about_the_fire(
    hass: HomeAssistant, entry, fire: FakeFireplace, box: FakeBox
) -> None:
    """At start-up the box answers "no receiver": the fire may well be burning."""
    fire.lit(12)
    box.no_receiver = True

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert box.commands == []


async def test_no_ignite_on_a_state_that_may_be_out_of_date(
    hass: HomeAssistant, coordinator, box: FakeBox, switch: str
) -> None:
    """Off was the last thing known, a while ago. The box does not answer now."""
    box.fail_connects = 99

    with pytest.raises(HomeAssistantError) as error:
        await call(hass, "switch", "turn_on", switch)

    assert error.value.translation_key == "cannot_reach"
    assert box.commands == []


async def test_shutdown_between_two_polls_still_delays_the_next_ignition(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    """Turned off with the handset; the last poll still saw the fire burning."""
    fire.lit(12)
    await settled(hass, coordinator, clock)
    fire.off()

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "switch", "turn_on", switch)

    assert error.value.translation_key == "shutting_down"
    assert box.commands == []


async def test_reload_does_not_forget_an_ignition(
    hass: HomeAssistant, entry, coordinator, box: FakeBox, clock: FakeClock, switch: str
) -> None:
    """The reload button, a reconfigure or a new address all set the entry up again."""
    box.on_command = None  # the box reports "off" a little longer
    await call(hass, "switch", "turn_on", switch)
    clock.advance(4)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(switch).state == "on"

    await call(hass, "switch", "turn_on", switch)
    assert box.commands == ["1A"]


async def test_reload_does_not_forget_the_wait_after_a_shutdown(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "switch", "turn_off", switch)
    fire.off()
    await poll(hass, coordinator)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "switch", "turn_on", switch)
    assert error.value.translation_key == "shutting_down"
    assert box.commands == ["10"]


async def test_ignition_that_takes_several_attempts(
    hass: HomeAssistant,
    entry,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    """Measured: the pilot held on a later attempt, with "off" reported in between.

    That "off" must not allow another ignite, nor drop what waits for the fire.
    """
    aux = entity_id(hass, entry, "switch", "AuxOnOff")
    await call(hass, "switch", "turn_on", switch)
    await call(hass, "switch", "turn_on", aux)
    set_room(hass, "22.0")
    await call(hass, "climate", "set_temperature", CLIMATE, temperature=21)

    for link, igniting, pilot, output in (
        (True, True, False, 0x00),
        (False, True, False, 0x00),
        (True, False, True, 0xFF),
        (False, False, True, 0xFF),
        (True, False, False, 0x00),  # the pilot went out; the receiver tries again
        (True, True, False, 0x00),
        (True, False, True, 0xFF),
    ):
        clock.advance(10)
        fire.set(link=link, igniting=igniting, pilot=pilot, output=output)
        await poll(hass, coordinator)
        assert hass.states.get(status).state == "igniting"
        await call(hass, "switch", "turn_on", switch)
    assert box.commands == ["1A"]
    assert hass.states.get(CLIMATE).state == "heat"

    clock.advance(61)
    await poll(hass, coordinator)

    # Lit: the secondary burner is set, and the thermostat finds the room warm.
    assert box.commands == ["1A", "2001", "1600"]
    assert hass.states.get(CLIMATE).state == "heat"


# --- Off is never dropped ----------------------------------------------------------------


async def test_refused_off_is_not_passed_off_as_done(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    """The box answers with a status frame and a refusal."""
    fire.lit(12)
    await settled(hass, coordinator, clock)
    box.script["10"] = [framed(box.status), framed(NO_RECEIVER)]

    with pytest.raises(HomeAssistantError) as error:
        await call(hass, "switch", "turn_off", switch)
    assert error.value.translation_key == "no_receiver"

    # It is owed, and sent again after the next poll.
    del box.script["10"]
    await poll(hass, coordinator)
    assert box.commands == ["10", "10", "10"]
    assert hass.states.get(switch).state == "off"


async def test_off_during_an_ignition_is_sent_until_it_is_taken(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    """Changed your mind within the first minute: the receiver refuses commands then."""
    await call(hass, "switch", "turn_on", switch)
    box.script["10"] = [framed(NO_RECEIVER)]

    await call(hass, "switch", "turn_off", switch)  # queued; no error for what is expected
    assert hass.states.get(switch).state == "off"
    assert hass.states.get(status).state == "igniting"
    refused = box.commands.count("10")
    assert refused >= 1

    # While the receiver is out of reach nothing is thrown at it.
    fire.set(link=False)
    clock.advance(10)
    await poll(hass, coordinator)
    assert box.commands.count("10") == refused

    # The fire lights after all; the first poll that shows the link sends the off.
    del box.script["10"]
    fire.lit(12)
    fire.set(link=True)
    clock.advance(10)
    await poll(hass, coordinator)
    assert box.commands[-1] == "10"
    assert hass.states.get(status).state == "shutting_down"

    fire.off()
    await poll(hass, coordinator)
    sent = len(box.commands)
    await poll(hass, coordinator)
    assert len(box.commands) == sent  # obeyed: nothing more is sent
    assert hass.states.get(status).state == "off"


async def test_off_that_is_never_taken_is_given_up_loudly(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    box.script["10"] = [framed(NO_RECEIVER)]
    with pytest.raises(HomeAssistantError):
        await call(hass, "switch", "turn_off", switch)

    clock.advance(301)
    with caplog.at_level(logging.ERROR):
        await poll(hass, coordinator)

    assert "did not take the command to turn off" in caplog.text
    # The switch shows the truth again.
    assert hass.states.get(switch).state == "on"


async def test_off_works_while_everything_else_is_unavailable(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    """Home Assistant does not pass commands on to unavailable entities.

    A "turn off after four hours" automation must not depend on the last poll.
    """
    fire.lit(12)
    await settled(hass, coordinator, clock)

    # The receiver bit has read clear for a long time, with the fire burning.
    fire.set(link=False)
    await poll(hass, coordinator)
    clock.advance(46)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == STATE_UNAVAILABLE
    assert hass.states.get(switch).state == STATE_UNKNOWN

    await call(hass, "switch", "turn_off", switch)
    assert box.commands == ["10"]


async def test_off_after_a_failed_poll(
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
    box.fail_connects = 2
    await poll(hass, coordinator)
    assert hass.states.get(status).state == STATE_UNAVAILABLE

    await call(hass, "switch", "turn_off", switch)
    assert box.commands == ["10"]


async def test_off_to_a_box_that_cannot_be_reached_is_sent_when_it_is_back(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    box.fail_connects = 99

    with pytest.raises(HomeAssistantError) as error:
        await call(hass, "switch", "turn_off", switch)
    assert error.value.translation_key == "cannot_reach"
    assert box.commands == []

    box.fail_connects = 0
    clock.advance(30)
    await poll(hass, coordinator)
    assert box.commands == ["10"]


async def test_switch_does_not_read_on_again_during_the_shutdown(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    status: str,
) -> None:
    """The polls only catch frames without the receiver link until it is out."""
    fire.lit(12)
    await settled(hass, coordinator, clock)
    box.on_command = None
    await call(hass, "switch", "turn_off", switch)

    fire.set(link=False, pilot=True, shutting_down=True, output=0)
    for _ in range(3):
        clock.advance(10)
        await poll(hass, coordinator)
        assert hass.states.get(switch).state == "off"
        assert hass.states.get(status).state == "shutting_down"

    fire.set(link=True, pilot=False, shutting_down=False)
    clock.advance(5)
    await poll(hass, coordinator)
    assert hass.states.get(status).state == "off"


# --- Nothing else during an ignition or a shutdown ----------------------------------------


async def test_light_and_modes_wait_for_the_fire_too(
    hass: HomeAssistant,
    entry,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
) -> None:
    """An automation "when the fireplace turns on, switch on its light"."""
    light = entity_id(hass, entry, "light", "Light")
    await call(hass, "switch", "turn_on", switch)

    await call(hass, "light", "turn_on", light, brightness=255)
    await call(hass, "climate", "set_hvac_mode", CLIMATE, hvac_mode="off")
    assert box.commands == ["1A"]
    assert hass.states.get(light).state == "on"

    fire.lit(12)
    clock.advance(61)
    await poll(hass, coordinator)
    assert box.commands == ["1A", "30FEFB", "B0"]


async def test_flame_command_does_not_land_behind_an_off(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    number: str,
) -> None:
    """The off is on the wire when an automation lowers the flame."""
    fire.lit(12)
    await settled(hass, coordinator, clock)
    started, release = threading.Event(), threading.Event()

    def slow_off() -> list[bytes]:
        started.set()
        release.wait(5)
        fire._on_command("10")
        return [framed(ack("10"))]

    box.script["10"] = slow_off
    off = hass.async_create_task(
        hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    )
    await hass.async_add_executor_job(started.wait, 5)
    flame = hass.async_create_task(
        hass.services.async_call(
            "number", "set_value", {"entity_id": number, "value": 4}, blocking=True
        )
    )
    await asyncio.sleep(0.2)
    release.set()
    await off
    with pytest.raises(ServiceValidationError) as error:
        await flame
    await hass.async_block_till_done(wait_background_tasks=True)

    assert error.value.translation_key == "shutting_down"
    assert box.commands == ["10"]


async def test_flame_asked_for_while_the_ignite_is_on_its_way_waits(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    switch: str,
    number: str,
) -> None:
    """"Turn on" and "flame 4" from one automation, in parallel."""
    started, release = threading.Event(), threading.Event()

    def slow_ignite() -> list[bytes]:
        started.set()
        release.wait(5)
        fire._on_command("1A")
        return [framed(ack("1A"))]

    box.script["1A"] = slow_ignite
    on = hass.async_create_task(
        hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    )
    await hass.async_add_executor_job(started.wait, 5)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": 4}, blocking=True
    )
    release.set()
    await on
    assert box.commands == ["1A"]

    fire.lit(12)
    clock.advance(61)
    await poll(hass, coordinator)
    assert box.commands == ["1A", "16A2"]


# --- The thermostat ---------------------------------------------------------------------


async def test_thermostat_sends_nothing_into_a_lost_link(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
) -> None:
    """Someone turns the fire off with the handset; the box's frames are unreliable."""
    fire.lit(1)
    await settled(hass, coordinator, clock)
    set_room(hass, "20.5")
    await call(hass, "climate", "set_temperature", CLIMATE, temperature=21)

    fire.set(link=False, shutting_down=True)
    set_room(hass, "19.0")
    clock.advance(121)
    await poll(hass, coordinator)

    assert box.commands == []
    assert hass.states.get(CLIMATE).state == "off"


async def test_thermostat_steps_back_for_a_mode_chosen_on_the_handset(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
) -> None:
    """Two regulators on one flame would fight."""
    fire.lit(1)
    await settled(hass, coordinator, clock)
    set_room(hass, "20.5")
    await call(hass, "climate", "set_temperature", CLIMATE, temperature=21)

    for _ in range(3):
        fire.set(mode="2", output=0xD0)  # eco, set on the handset
        clock.advance(121)
        await poll(hass, coordinator)

    assert box.commands == []
    assert hass.states.get(CLIMATE).state == "off"


async def test_sensor_that_stopped_reporting_is_not_heated_on(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    box: FakeBox,
    clock: FakeClock,
    freezer,
) -> None:
    """Its battery died: Home Assistant keeps showing the last value for ever."""
    fire.lit(1)
    await settled(hass, coordinator, clock)
    set_room(hass, "19.0")
    await call(hass, "climate", "set_temperature", CLIMATE, temperature=21)
    assert box.commands == ["16FF"]

    freezer.tick(timedelta(minutes=61))
    await poll(hass, coordinator)
    assert hass.states.get(CLIMATE).attributes["current_temperature"] is None

    clock.advance(301)
    await poll(hass, coordinator)
    assert box.commands == ["16FF", "1600"]

    # The same value reported again is a reading again.
    set_room(hass, "19.0")
    await poll(hass, coordinator)
    assert hass.states.get(CLIMATE).attributes["current_temperature"] == 19.0


async def test_thermostat_is_restored_in_celsius_whatever_the_display_unit(
    hass: HomeAssistant, entry, with_sensor, fire: FakeFireplace, box: FakeBox
) -> None:
    """On an installation that shows Fahrenheit the entity's state holds 72."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    mock_restore_cache_with_extra_data(
        hass,
        [(State(CLIMATE, "heat", {"temperature": 72}), {"target": 22.0, "active": True})],
    )
    fire.lit(12)
    set_room(hass, "19.0")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert coordinator.thermostat.target == 22.0
    assert coordinator.thermostat.active
    assert hass.states.get(CLIMATE).state == "heat"


async def test_target_survives_a_stop_with_the_fireplace_unreachable(
    hass: HomeAssistant, entry, with_sensor, fire: FakeFireplace
) -> None:
    mock_restore_cache_with_extra_data(
        hass, [(State(CLIMATE, STATE_UNAVAILABLE), {"target": 23.5, "active": False})]
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.thermostat.target == 23.5
    assert hass.states.get(CLIMATE).state == "off"


async def test_thermostat_memory_is_what_gets_stored(
    hass: HomeAssistant,
    with_sensor,
    coordinator,
    fire: FakeFireplace,
    clock: FakeClock,
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    await call(hass, "climate", "set_temperature", CLIMATE, temperature=22.5)

    entity = hass.data["climate"].get_entity(CLIMATE)
    assert entity.extra_restore_state_data.as_dict() == {"target": 22.5, "active": True}


# --- Setup, removal, diagnostics -----------------------------------------------------------


async def test_reconfigure_does_not_put_two_entries_on_one_address(
    hass: HomeAssistant, network: Network
) -> None:
    """Modules that ignore the search are only known by their address."""
    FakeFireplace(network.add(HOST, mac=None))
    entries = []
    for name, host in (("First", HOST), ("Second", "192.168.1.60")):
        entry = MockConfigEntry(
            domain=DOMAIN, title=name, unique_id=host, data={CONF_NAME: name, CONF_HOST: host}
        )
        entry.add_to_hass(hass)
        entries.append(entry)
    first, second = entries

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": second.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "address_in_use"}
    assert second.data[CONF_HOST] == "192.168.1.60"
    assert first.unique_id != second.unique_id


async def test_repair_goes_with_the_entry(
    hass: HomeAssistant, entry, coordinator, fire: FakeFireplace, clock: FakeClock
) -> None:
    fire.lit(12)
    await settled(hass, coordinator, clock)
    fire.set(link=False)
    await poll(hass, coordinator)
    clock.advance(46)
    await poll(hass, coordinator)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"receiver_lost_{entry.entry_id}") is not None

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get_issue(DOMAIN, f"receiver_lost_{entry.entry_id}") is None
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_diagnostics_keep_the_raw_reply_back_without_a_known_mac(
    hass: HomeAssistant, network: Network
) -> None:
    """The reply holds the MAC address, which cannot be taken out unknown."""
    box = network.add(HOST, mac=None)
    box.device_info = "005400000000" + "0500233CAABBCC1602" + "5A38382E70313331"
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=HOST, data={CONF_NAME: NAME, CONF_HOST: HOST}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["device_info"] == WITHHELD
