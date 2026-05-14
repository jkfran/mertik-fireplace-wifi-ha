"""Integration tests using the full HA setup flow.

These tests follow the HA integration testing guidelines:
- MockConfigEntry for config entry setup
- hass.config_entries for entry lifecycle
- hass.states for entity state assertions
- hass.services for service call interactions
- device_registry and entity_registry for structural assertions
- ConfigEntry.state for setup/unload lifecycle assertions
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mertik.const import DOMAIN

ENTRY_DATA = {"name": "My Fireplace", "host": "192.168.1.100"}

# (platform, unique-id suffix) for every entity the integration creates
ALL_ENTITIES = [
    ("switch", "-OnOff"),
    ("switch", "-AuxOnOff"),
    ("number", "-FlameHeight"),
    ("select", "-HeatingMode"),
    ("climate", "-Thermostat"),
    ("sensor", "-AmbientTemperature"),
    ("sensor", "-FaultCode"),
    ("light", "-Light"),
]


def _make_mock_device() -> MagicMock:
    """Return a MagicMock Mertik device with boolean defaults."""
    device = MagicMock()
    device.ip = "192.168.1.100"
    device.is_flame_on = False
    device.is_igniting = False
    device.is_aux_on = False
    device.is_handset_connected = True
    device.fault_code = 0
    device.ambient_temperature = 21.5
    device.get_flame_height.return_value = 0
    device.close = AsyncMock()
    return device


@pytest.fixture
def mock_device() -> MagicMock:
    return _make_mock_device()


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant,
    mock_device: MagicMock,
    enable_custom_integrations: None,
) -> MockConfigEntry:
    """A MockConfigEntry with all platforms fully set up in hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="My Fireplace",
        data=ENTRY_DATA,
        options={},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.mertik.Mertik.async_connect", return_value=mock_device):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _entity_id(
    hass: HomeAssistant, platform: str, entry: MockConfigEntry, suffix: str
) -> str | None:
    """Return the entity_id for a given platform and unique-id suffix."""
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, entry.entry_id + suffix
    )


# ---------------------------------------------------------------------------
# Config entry lifecycle
# ---------------------------------------------------------------------------


class TestConfigEntryState:
    async def test_entry_loaded_after_setup(
        self, loaded_entry: MockConfigEntry
    ) -> None:
        assert loaded_entry.state == ConfigEntryState.LOADED

    async def test_entry_not_loaded_after_unload(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        await hass.config_entries.async_unload(loaded_entry.entry_id)
        await hass.async_block_till_done()
        assert loaded_entry.state == ConfigEntryState.NOT_LOADED

    async def test_entry_setup_retry_on_connection_failure(
        self, hass: HomeAssistant, enable_custom_integrations: None
    ) -> None:
        entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
        entry.add_to_hass(hass)
        with patch(
            "custom_components.mertik.Mertik.async_connect",
            side_effect=OSError("Connection refused"),
        ):
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        assert entry.state == ConfigEntryState.SETUP_RETRY


# ---------------------------------------------------------------------------
# Device registry
# ---------------------------------------------------------------------------


class TestDeviceRegistry:
    async def test_single_device_created(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        devices = dr.async_get(hass).devices.get_devices_for_config_entry_id(
            loaded_entry.entry_id
        )
        assert len(devices) == 1

    async def test_device_identifiers(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        device = dr.async_get(hass).async_get_device(
            identifiers={(DOMAIN, loaded_entry.entry_id)}
        )
        assert device is not None

    async def test_device_manufacturer(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        device = dr.async_get(hass).async_get_device(
            identifiers={(DOMAIN, loaded_entry.entry_id)}
        )
        assert device is not None
        assert device.manufacturer == "Mertik Maxitrol"

    async def test_device_name(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        device = dr.async_get(hass).async_get_device(
            identifiers={(DOMAIN, loaded_entry.entry_id)}
        )
        assert device is not None
        assert device.name == "My Fireplace"


# ---------------------------------------------------------------------------
# Entity registry
# ---------------------------------------------------------------------------


class TestEntityRegistry:
    @pytest.mark.parametrize("platform,suffix", ALL_ENTITIES)
    async def test_entity_registered(
        self,
        hass: HomeAssistant,
        loaded_entry: MockConfigEntry,
        platform: str,
        suffix: str,
    ) -> None:
        entity_id = _entity_id(hass, platform, loaded_entry, suffix)
        assert entity_id is not None, f"{platform}{suffix} missing from entity registry"

    async def test_all_entities_belong_to_single_device(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        registry = er.async_get(hass)
        device_id = dr.async_get(hass).async_get_device(
            identifiers={(DOMAIN, loaded_entry.entry_id)}
        ).id
        for platform, suffix in ALL_ENTITIES:
            eid = _entity_id(hass, platform, loaded_entry, suffix)
            entry = registry.async_get(eid)
            assert entry is not None
            assert entry.device_id == device_id, f"{platform}{suffix} wrong device"


# ---------------------------------------------------------------------------
# State machine — initial states after setup
# ---------------------------------------------------------------------------


class TestStateMachine:
    async def test_fireplace_switch_off(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        state = hass.states.get(_entity_id(hass, "switch", loaded_entry, "-OnOff"))
        assert state is not None
        assert state.state == "off"

    async def test_aux_switch_off(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        state = hass.states.get(_entity_id(hass, "switch", loaded_entry, "-AuxOnOff"))
        assert state is not None
        assert state.state == "off"

    async def test_thermostat_off(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        state = hass.states.get(_entity_id(hass, "climate", loaded_entry, "-Thermostat"))
        assert state is not None
        assert state.state == "off"

    async def test_ambient_temperature_sensor(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        state = hass.states.get(
            _entity_id(hass, "sensor", loaded_entry, "-AmbientTemperature")
        )
        assert state is not None
        assert state.state == "21.5"

    async def test_fault_code_no_fault(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        state = hass.states.get(_entity_id(hass, "sensor", loaded_entry, "-FaultCode"))
        assert state is not None
        assert state.state == "none"

    async def test_heating_mode_default_standby(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        state = hass.states.get(_entity_id(hass, "select", loaded_entry, "-HeatingMode"))
        assert state is not None
        assert state.state == "Standby"


# ---------------------------------------------------------------------------
# Service calls — assert state via hass.states after each call
# ---------------------------------------------------------------------------


class TestServiceCalls:
    async def test_turn_on_switch_via_service(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        entity_id = _entity_id(hass, "switch", loaded_entry, "-OnOff")
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "on"

    async def test_turn_off_switch_via_service(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        entity_id = _entity_id(hass, "switch", loaded_entry, "-OnOff")
        # Turn on first so the off transition is meaningful
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
        await hass.async_block_till_done()
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "off"

    async def test_select_heating_mode_via_service(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        entity_id = _entity_id(hass, "select", loaded_entry, "-HeatingMode")
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": "Full Heat"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "Full Heat"

    async def test_set_thermostat_temperature_via_service(
        self, hass: HomeAssistant, loaded_entry: MockConfigEntry
    ) -> None:
        entity_id = _entity_id(hass, "climate", loaded_entry, "-Thermostat")
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": 22.0},
            blocking=True,
        )
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.attributes["temperature"] == 22.0
