"""Setting up a fireplace, changing its address, following it, and the options."""

from __future__ import annotations

from dataclasses import dataclass

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import (
    SOURCE_DHCP,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mertik.const import (
    CONF_MAC,
    CONF_MODEL,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
)

from .conftest import HOST, MAC, MODEL, NAME, Network

try:
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
except ImportError:  # Home Assistant before 2025.2 keeps it inside the dhcp integration

    @dataclass
    class DhcpServiceInfo:  # type: ignore[no-redef]
        """What the dhcp integration hands to a flow."""

        ip: str
        hostname: str
        macaddress: str


OTHER_HOST = "192.168.1.150"
OTHER_MAC = "00:23:3c:11:22:33"


async def start_user_flow(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def start_reconfigure_flow(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )


def version_1_entry(hass: HomeAssistant) -> MockConfigEntry:
    """An entry as versions before 2.0 made it: known by its address only."""
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=HOST, data={CONF_NAME: NAME, CONF_HOST: HOST}
    )
    entry.add_to_hass(hass)
    return entry


# --- Setting up ------------------------------------------------------------------------


async def test_user_flow_with_a_module_found(hass: HomeAssistant, network: Network) -> None:
    network.add(HOST)

    result = await start_user_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    assert result["description_placeholders"] == {"found": HOST}
    # The module found is filled in already.
    assert result["data_schema"]({CONF_NAME: NAME}) == {CONF_NAME: NAME, CONF_HOST: HOST}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Living room fire", CONF_HOST: HOST}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living room fire"
    assert result["data"] == {
        CONF_NAME: "Living room fire",
        CONF_HOST: HOST,
        CONF_MAC: MAC,
        CONF_MODEL: MODEL,
    }
    entry = result["result"]
    assert entry.unique_id == MAC
    assert entry.state is ConfigEntryState.LOADED


async def test_user_flow_with_nothing_found_takes_a_typed_address(
    hass: HomeAssistant, network: Network
) -> None:
    """A module that ignores the UDP query is set up by its address alone."""
    network.add(HOST, mac=None)

    result = await start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"found": "-"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: NAME, CONF_HOST: f" {HOST} "}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_NAME: NAME, CONF_HOST: HOST}
    assert result["result"].unique_id == HOST


async def test_user_flow_asks_a_typed_address_for_its_identity(
    hass: HomeAssistant, network: Network
) -> None:
    """The broadcast did not get through (another subnet), the direct query does."""
    network.add(HOST)
    network.broadcast_works = False

    result = await start_user_flow(hass)
    assert result["description_placeholders"] == {"found": "-"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: NAME, CONF_HOST: HOST}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MAC] == MAC
    assert result["result"].unique_id == MAC


async def test_user_flow_cannot_connect(hass: HomeAssistant, network: Network) -> None:
    result = await start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Stove", CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    # What was typed is kept.
    assert result["data_schema"]({}) == {CONF_NAME: "Stove", CONF_HOST: HOST}

    network.add(HOST)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Stove", CONF_HOST: HOST}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_suggests_the_module_not_set_up_yet(
    hass: HomeAssistant, entry, coordinator, network: Network
) -> None:
    network.add(OTHER_HOST, mac=OTHER_MAC)

    result = await start_user_flow(hass)

    assert result["description_placeholders"] == {"found": f"{HOST}, {OTHER_HOST}"}
    assert result["data_schema"]({CONF_NAME: NAME})[CONF_HOST] == OTHER_HOST

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Second fire", CONF_HOST: OTHER_HOST}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == OTHER_MAC


async def test_user_flow_does_not_add_a_fireplace_twice(
    hass: HomeAssistant, entry, coordinator
) -> None:
    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Again", CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_recognises_a_configured_fireplace_at_a_new_address(
    hass: HomeAssistant, entry, coordinator, network: Network
) -> None:
    """Same MAC address elsewhere: it is the same fireplace, which has moved."""
    network.move(HOST, OTHER_HOST)

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Again", CONF_HOST: OTHER_HOST}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == OTHER_HOST
    assert entry.runtime_data.mertik.ip == OTHER_HOST


async def test_user_flow_does_not_duplicate_a_version_1_entry(
    hass: HomeAssistant, network: Network
) -> None:
    """Before its first start on 2.0 such an entry is only known by its address."""
    network.add(HOST)
    version_1_entry(hass)

    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Again", CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --- Changing the address ------------------------------------------------------------


async def test_reconfigure_to_a_new_address(
    hass: HomeAssistant, entry, coordinator, network: Network
) -> None:
    network.move(HOST, OTHER_HOST)

    result = await start_reconfigure_flow(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"] == {"current": HOST, "found": OTHER_HOST}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: OTHER_HOST}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {
        CONF_NAME: NAME,
        CONF_HOST: OTHER_HOST,
        CONF_MAC: MAC,
        CONF_MODEL: MODEL,
    }
    assert entry.unique_id == MAC
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.mertik.ip == OTHER_HOST


async def test_reconfigure_refuses_another_fireplace(
    hass: HomeAssistant, entry, coordinator, network: Network
) -> None:
    network.add(OTHER_HOST, mac=OTHER_MAC)

    result = await start_reconfigure_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: OTHER_HOST}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_device"}
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure_cannot_connect(
    hass: HomeAssistant, entry, coordinator
) -> None:
    result = await start_reconfigure_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.77"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert result["data_schema"]({}) == {CONF_HOST: "192.168.1.77"}
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure_gives_a_version_1_entry_its_identity(
    hass: HomeAssistant, network: Network
) -> None:
    """The module moved before the entry ever learned its MAC address."""
    network.add(OTHER_HOST)
    entry = version_1_entry(hass)

    result = await start_reconfigure_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: OTHER_HOST}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == MAC
    assert entry.data[CONF_HOST] == OTHER_HOST
    assert entry.data[CONF_MAC] == MAC


async def test_reconfigure_of_an_entry_known_by_address_only(
    hass: HomeAssistant, network: Network
) -> None:
    network.add(OTHER_HOST, mac=None)
    entry = version_1_entry(hass)

    result = await start_reconfigure_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: OTHER_HOST}
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == OTHER_HOST
    assert entry.data == {CONF_NAME: NAME, CONF_HOST: OTHER_HOST}


async def test_reconfigure_does_not_point_two_entries_at_one_fireplace(
    hass: HomeAssistant, entry, coordinator, network: Network
) -> None:
    """A version 1 entry cannot take the address of a fireplace set up already."""
    old = MockConfigEntry(
        domain=DOMAIN,
        title="Old",
        unique_id="192.168.1.60",
        data={CONF_NAME: "Old", CONF_HOST: "192.168.1.60"},
    )
    old.add_to_hass(hass)

    result = await start_reconfigure_flow(hass, old)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_device"}
    assert old.unique_id == "192.168.1.60"


# --- Following the module --------------------------------------------------------------


async def test_dhcp_moves_a_known_fireplace_to_its_new_address(
    hass: HomeAssistant, entry, coordinator, network: Network
) -> None:
    network.move(HOST, OTHER_HOST)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip=OTHER_HOST, hostname="mmwifibox", macaddress=MAC.replace(":", "")
        ),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == OTHER_HOST
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.mertik.ip == OTHER_HOST


async def test_dhcp_does_not_offer_unknown_devices(
    hass: HomeAssistant, entry, coordinator
) -> None:
    """Only addresses of fireplaces already set up are followed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip=OTHER_HOST, hostname="something", macaddress=OTHER_MAC.replace(":", "")
        ),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_configured"
    assert entry.data[CONF_HOST] == HOST
    assert not hass.config_entries.flow.async_progress()


# --- Options ---------------------------------------------------------------------------


async def test_options_set_and_clear_the_temperature_sensor(
    hass: HomeAssistant, entry, coordinator
) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TEMPERATURE_SENSOR: "sensor.room"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_TEMPERATURE_SENSOR: "sensor.room"}
    assert coordinator.temperature_sensor == "sensor.room"

    # The form comes back with the sensor filled in; emptying the field removes it.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    key = next(iter(result["data_schema"].schema))
    assert key.description == {"suggested_value": "sensor.room"}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {}
    assert coordinator.temperature_sensor is None
