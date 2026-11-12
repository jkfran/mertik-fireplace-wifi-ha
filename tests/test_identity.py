"""An address is not an identity: never control the fireplace that got ours.

Routers deal addresses out again. In a house with two fireplaces the entry of
one can end up pointing at the other. The MAC address of the WiFi module tells
them apart.
"""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.mertik.const import CONF_MAC, DOMAIN

from .conftest import HOST, MAC, NAME, Network, call, entity_id, poll
from .fakes import FakeBox, FakeClock, FakeFireplace

OTHER_HOST = "192.168.1.150"
OTHER_MAC = "00:23:3c:11:22:33"


@pytest.fixture
def other(network: Network) -> FakeBox:
    """A second fireplace in the house, which Home Assistant has no entry for."""
    return network.add(OTHER_HOST, mac=OTHER_MAC)


async def test_setup_refuses_an_address_another_fireplace_has(
    hass: HomeAssistant, entry, network: Network
) -> None:
    stranger = network.add(HOST, mac=OTHER_MAC)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    # The entry stays what it was: it does not become the other fireplace.
    assert entry.data[CONF_MAC] == MAC
    assert entry.unique_id == MAC
    assert stranger.commands == []


async def test_setup_finds_the_fireplace_after_an_address_swap(
    hass: HomeAssistant, entry, network: Network, box: FakeBox, other: FakeBox
) -> None:
    network.swap(HOST, OTHER_HOST)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_HOST] == OTHER_HOST
    assert entry.data[CONF_MAC] == MAC
    assert entry.runtime_data.mertik.ip == OTHER_HOST


async def test_ignition_is_refused_when_another_fireplace_has_the_address(
    hass: HomeAssistant,
    entry,
    coordinator,
    network: Network,
    box: FakeBox,
    other: FakeBox,
) -> None:
    """The swap happened a moment ago; no poll has seen it yet."""
    switch = entity_id(hass, entry, "switch", "OnOff")
    network.swap(HOST, OTHER_HOST)

    with pytest.raises(HomeAssistantError) as error:
        await call(hass, "switch", "turn_on", switch)

    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == "wrong_device"
    assert other.commands == []
    assert box.commands == []

    # The entry is set up again and has found its fireplace at the new address.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_HOST] == OTHER_HOST

    await call(hass, "switch", "turn_on", switch)
    assert box.commands == ["1A"]
    assert other.commands == []


async def test_swap_is_noticed_when_the_connection_returns(
    hass: HomeAssistant,
    entry,
    coordinator,
    network: Network,
    box: FakeBox,
    other: FakeBox,
) -> None:
    """A router restart: everything drops, and comes back with other addresses."""
    switch = entity_id(hass, entry, "switch", "OnOff")
    box.fail_connects = 2
    await poll(hass, coordinator)
    assert hass.states.get(switch).state == STATE_UNKNOWN

    network.swap(HOST, OTHER_HOST)
    FakeFireplace(other).lit(12)  # the other fireplace happens to be burning
    await poll(hass, coordinator)
    await hass.async_block_till_done(wait_background_tasks=True)

    # Its state was never shown as this fireplace's.
    assert entry.data[CONF_HOST] == OTHER_HOST
    assert entry.runtime_data.mertik.ip == OTHER_HOST
    assert hass.states.get(switch).state == "off"
    assert other.commands == []


async def test_swap_without_an_outage_is_noticed_within_minutes(
    hass: HomeAssistant,
    entry,
    coordinator,
    network: Network,
    other: FakeBox,
    clock: FakeClock,
) -> None:
    network.swap(HOST, OTHER_HOST)

    clock.advance(301)
    await poll(hass, coordinator)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.data[CONF_HOST] == OTHER_HOST
    assert entry.runtime_data is not coordinator


async def test_fireplace_gone_for_good_leaves_the_entry_waiting(
    hass: HomeAssistant,
    entry,
    coordinator,
    network: Network,
    clock: FakeClock,
) -> None:
    """Its address went to another fireplace and it is nowhere to be found."""
    switch = entity_id(hass, entry, "switch", "OnOff")
    stranger = network.add(HOST, mac=OTHER_MAC)

    clock.advance(301)
    await poll(hass, coordinator)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.states.get(switch).state == STATE_UNAVAILABLE
    assert entry.data[CONF_HOST] == HOST
    assert stranger.commands == []


async def test_module_that_does_not_answer_the_question_is_trusted(
    hass: HomeAssistant, entry, coordinator, network: Network, box: FakeBox
) -> None:
    """A lost UDP answer must not keep anyone from using their fireplace."""
    del network.modules[HOST]

    await call(hass, "switch", "turn_on", entity_id(hass, entry, "switch", "OnOff"))

    assert box.commands == ["1A"]
    assert entry.state is ConfigEntryState.LOADED


async def test_entry_without_a_mac_address_works_by_address(
    hass: HomeAssistant, network: Network, clock: FakeClock
) -> None:
    """Modules that ignore discovery are used as before 2.0."""
    box = network.add(HOST, mac=None)
    old = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=HOST, data={CONF_NAME: NAME, CONF_HOST: HOST}
    )
    old.add_to_hass(hass)
    assert await hass.config_entries.async_setup(old.entry_id)
    await hass.async_block_till_done()

    clock.advance(301)
    await poll(hass, old.runtime_data)
    await call(hass, "switch", "turn_on", entity_id(hass, old, "switch", "OnOff"))

    assert box.commands == ["1A"]
    assert old.state is ConfigEntryState.LOADED
