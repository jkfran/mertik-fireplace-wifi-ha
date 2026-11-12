"""Setting the integration up, moving with the module, and what older versions left."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.mertik import async_remove_config_entry_device
from custom_components.mertik.const import CONF_MAC, CONF_MODEL, DOMAIN

from .conftest import HOST, MAC, MODEL, NAME, Network, entity_id, fireplace_device
from .fakes import FakeFireplace

# Unique ID keys of the entities, by platform. The first five existed before 2.0
# and must never change: the unique ID is what keeps a user's entity IDs,
# history and automations attached.
LEGACY_KEYS = {
    ("switch", "OnOff"),
    ("switch", "AuxOnOff"),
    ("number", "FlameHeight"),
    ("light", "Light"),
    ("sensor", "AmbientTemperature"),
    ("climate", "Thermostat"),
}
NEW_KEYS = {
    ("sensor", "Status"),
    ("sensor", "FanLevel"),
    ("sensor", "IPAddress"),
    ("binary_sensor", "PilotFlame"),
    ("binary_sensor", "Igniting"),
    ("binary_sensor", "ShuttingDown"),
    ("binary_sensor", "ReceiverConnection"),
    ("binary_sensor", "RemoteConnection"),
    ("binary_sensor", "Fault"),
    ("binary_sensor", "Fan"),
    ("select", "Mode"),
}
DISABLED_BY_DEFAULT = {
    ("sensor", "FanLevel"),
    ("sensor", "IPAddress"),
    ("binary_sensor", "Igniting"),
    ("binary_sensor", "ShuttingDown"),
    ("binary_sensor", "Fault"),
    ("binary_sensor", "Fan"),
}


async def test_setup_creates_the_entities(hass: HomeAssistant, entry, coordinator) -> None:
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    found = {
        (entity.domain, entity.unique_id.removeprefix(f"{entry.entry_id}-"))
        for entity in entities
    }
    assert found == LEGACY_KEYS | NEW_KEYS

    disabled = {
        (entity.domain, entity.unique_id.removeprefix(f"{entry.entry_id}-"))
        for entity in entities
        if entity.disabled_by is not None
    }
    assert disabled == DISABLED_BY_DEFAULT


async def test_entity_ids_and_names(hass: HomeAssistant, entry, coordinator) -> None:
    """Entities are named after the device; the main switch carries its name."""
    expected = {
        ("switch", "OnOff"): ("switch.fireplace", "Fireplace"),
        ("switch", "AuxOnOff"): (
            "switch.fireplace_secondary_burner",
            "Fireplace Secondary burner",
        ),
        ("number", "FlameHeight"): (
            "number.fireplace_flame_height",
            "Fireplace Flame Height",
        ),
        ("light", "Light"): ("light.fireplace_light", "Fireplace Light"),
        ("sensor", "AmbientTemperature"): (
            "sensor.fireplace_ambient_temperature",
            "Fireplace Ambient Temperature",
        ),
        ("climate", "Thermostat"): (
            "climate.fireplace_thermostat",
            "Fireplace Thermostat",
        ),
        ("sensor", "Status"): ("sensor.fireplace_status", "Fireplace Status"),
        ("select", "Mode"): ("select.fireplace_mode", "Fireplace Mode"),
        ("binary_sensor", "PilotFlame"): (
            "binary_sensor.fireplace_pilot_flame",
            "Fireplace Pilot flame",
        ),
        ("binary_sensor", "ReceiverConnection"): (
            "binary_sensor.fireplace_receiver",
            "Fireplace Receiver",
        ),
        ("binary_sensor", "RemoteConnection"): (
            "binary_sensor.fireplace_remote",
            "Fireplace Remote",
        ),
    }
    for (platform, key), (expected_id, expected_name) in expected.items():
        found = entity_id(hass, entry, platform, key)
        assert found == expected_id
        assert hass.states.get(found).name == expected_name


async def test_entities_from_version_1_keep_their_entity_ids(
    hass: HomeAssistant, entry, fire: FakeFireplace
) -> None:
    """An upgrade attaches to the entities a 1.x install registered."""
    registry = er.async_get(hass)
    old_ids = {
        ("switch", "OnOff"): "switch.fireplace",
        ("switch", "AuxOnOff"): "switch.fireplace_aux",
        ("number", "FlameHeight"): "number.fireplace_flame_height",
        ("light", "Light"): "light.fireplace_light",
        ("sensor", "AmbientTemperature"): "sensor.fireplace_ambient_temperature",
    }
    for (platform, key), old_id in old_ids.items():
        registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{entry.entry_id}-{key}",
            config_entry=entry,
            suggested_object_id=old_id.split(".", 1)[1],
        )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for (platform, key), old_id in old_ids.items():
        assert entity_id(hass, entry, platform, key) == old_id
        assert hass.states.get(old_id) is not None


async def test_device(hass: HomeAssistant, entry, coordinator) -> None:
    device = fireplace_device(hass, entry)
    assert device is not None
    assert device.name == NAME
    assert device.manufacturer == "Mertik Maxitrol"
    assert device.model == MODEL
    assert (dr.CONNECTION_NETWORK_MAC, MAC) in device.connections


async def test_setup_retries_while_the_fireplace_is_unreachable(
    hass: HomeAssistant, entry, network: Network
) -> None:
    # Nothing answers at the address, and discovery finds nothing either.
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_follows_the_module_to_a_new_address(
    hass: HomeAssistant, entry, network: Network, fire: FakeFireplace
) -> None:
    """The stored address is dead, but discovery finds the same MAC elsewhere."""
    network.move(HOST, "192.168.1.150")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_HOST] == "192.168.1.150"
    assert entry.runtime_data.mertik.ip == "192.168.1.150"
    assert entry.unique_id == MAC


async def test_setup_does_not_take_over_another_fireplace(
    hass: HomeAssistant, entry, network: Network
) -> None:
    """A module with a different MAC is not this entry's fireplace."""
    network.add("192.168.1.150", mac="00:23:3c:11:22:33")

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.data[CONF_HOST] == HOST


async def test_entry_from_version_1_is_identified_by_mac(
    hass: HomeAssistant, network: Network
) -> None:
    """Entries made before 2.0 have the IP address as unique ID and no MAC."""
    network.add(HOST)
    old = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id=HOST,
        data={CONF_NAME: NAME, CONF_HOST: HOST},
    )
    old.add_to_hass(hass)

    assert await hass.config_entries.async_setup(old.entry_id)
    await hass.async_block_till_done()

    assert old.unique_id == MAC
    assert old.data == {
        CONF_NAME: NAME,
        CONF_HOST: HOST,
        CONF_MAC: MAC,
        CONF_MODEL: MODEL,
    }
    device = fireplace_device(hass, old)
    assert (dr.CONNECTION_NETWORK_MAC, MAC) in device.connections


async def test_entry_keeps_its_identity_when_discovery_is_silent(
    hass: HomeAssistant, network: Network
) -> None:
    """A module that does not answer the UDP query still works, by address."""
    network.add(HOST, mac=None)
    old = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id=HOST,
        data={CONF_NAME: NAME, CONF_HOST: HOST},
    )
    old.add_to_hass(hass)

    assert await hass.config_entries.async_setup(old.entry_id)
    await hass.async_block_till_done()

    assert old.state is ConfigEntryState.LOADED
    assert old.unique_id == HOST
    assert old.data == {CONF_NAME: NAME, CONF_HOST: HOST}


async def test_two_entries_never_share_a_unique_id(
    hass: HomeAssistant, entry, network: Network, fire: FakeFireplace
) -> None:
    """A second, older entry for the same module keeps its own unique ID."""
    duplicate = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicate",
        unique_id=HOST,
        data={CONF_NAME: "Duplicate", CONF_HOST: HOST},
    )
    duplicate.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.unique_id == MAC
    assert duplicate.state is ConfigEntryState.LOADED
    assert duplicate.unique_id == HOST
    assert duplicate.data[CONF_MAC] == MAC


async def test_unload(hass: HomeAssistant, entry, coordinator) -> None:
    switch = entity_id(hass, entry, "switch", "OnOff")
    assert hass.states.get(switch).state != STATE_UNAVAILABLE

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(switch).state == STATE_UNAVAILABLE


async def test_reload(hass: HomeAssistant, entry, coordinator, box) -> None:
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not coordinator
    # Every exchange closed its connection.
    assert box.open_connections == 0


async def test_only_stale_devices_can_be_removed(
    hass: HomeAssistant, entry, coordinator
) -> None:
    registry = dr.async_get(hass)
    fireplace = fireplace_device(hass, entry)
    stale = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "something-older")}
    )

    assert not await async_remove_config_entry_device(hass, entry, fireplace)
    assert await async_remove_config_entry_device(hass, entry, stale)
