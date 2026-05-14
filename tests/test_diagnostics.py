"""Tests for diagnostics."""

from unittest.mock import MagicMock

import pytest

from custom_components.mertik.diagnostics import async_get_config_entry_diagnostics


@pytest.fixture
def mock_entry(mock_coordinator):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"name": "My Fireplace", "host": "192.168.1.100"}
    entry.options = {"low_threshold": 1.0, "high_threshold": 2.0}
    entry.runtime_data = mock_coordinator
    return entry


async def test_diagnostics_redacts_host(hass, mock_entry, mock_coordinator):
    mock_coordinator.is_on = True
    mock_coordinator.is_aux_on = False
    mock_coordinator.ambient_temperature = 21.5
    mock_coordinator.heating_mode = "Thermostatic"
    mock_coordinator.get_flame_height.return_value = 4
    mock_coordinator.is_light_on = False
    mock_coordinator._in_standby = False
    mock_coordinator._pending_mode = None

    result = await async_get_config_entry_diagnostics(hass, mock_entry)

    assert result["entry_data"]["host"] == "**REDACTED**"
    assert result["entry_data"]["name"] == "My Fireplace"


async def test_diagnostics_includes_coordinator_state(
    hass, mock_entry, mock_coordinator
):
    mock_coordinator.is_on = True
    mock_coordinator.is_aux_on = True
    mock_coordinator.ambient_temperature = 22.0
    mock_coordinator.heating_mode = "Full Heat"
    mock_coordinator.get_flame_height.return_value = 8
    mock_coordinator.is_light_on = True
    mock_coordinator._in_standby = False
    mock_coordinator._pending_mode = "Full Heat"

    result = await async_get_config_entry_diagnostics(hass, mock_entry)

    coord = result["coordinator"]
    assert coord["is_on"] is True
    assert coord["is_aux_on"] is True
    assert coord["ambient_temperature"] == 22.0
    assert coord["heating_mode"] == "Full Heat"
    assert coord["flame_height"] == 8
    assert coord["is_light_on"] is True
    assert coord["in_standby"] is False
    assert coord["pending_mode"] == "Full Heat"


async def test_diagnostics_includes_options(hass, mock_entry):
    result = await async_get_config_entry_diagnostics(hass, mock_entry)

    assert result["options"] == {"low_threshold": 1.0, "high_threshold": 2.0}
