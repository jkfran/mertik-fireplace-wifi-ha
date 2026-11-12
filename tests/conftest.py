"""Fixtures: a scripted fireplace instead of the network.

Nothing here opens a socket. The fireplace is a FakeBox, time is a FakeClock
(waiting costs nothing), and discovery answers from a list.
"""

from __future__ import annotations

from collections.abc import Generator
from functools import partial
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.mertik.const import CONF_MAC, CONF_MODEL, DOMAIN
from custom_components.mertik.coordinator import MertikDataCoordinator
from custom_components.mertik.discovery import Module
from custom_components.mertik.mertik import Mertik

from .fakes import FakeBox, FakeClock, FakeFireplace

HOST = "192.168.1.100"
MAC = "00:23:3c:aa:bb:cc"
MODEL = "mmWiFiBoxV2"
NAME = "Fireplace"


class Network:
    """The fake network: a box per address, and the modules discovery finds."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.boxes: dict[str, FakeBox] = {}
        self.modules: dict[str, Module] = {}
        # False: modules only answer when asked at their own address.
        self.broadcast_works = True

    def add(
        self, host: str = HOST, mac: str | None = MAC, name: str = MODEL
    ) -> FakeBox:
        """Put a fireplace on the network. With mac None it ignores discovery."""
        box = FakeBox(self.clock)
        self.boxes[host] = box
        if mac is not None:
            self.modules[host] = Module(host=host, name=name, mac=mac)
        return box

    def move(self, old: str, new: str) -> None:
        """Give a fireplace another address."""
        self.boxes[new] = self.boxes.pop(old)
        if old in self.modules:
            module = self.modules.pop(old)
            self.modules[new] = Module(host=new, name=module.name, mac=module.mac)

    def swap(self, first: str, second: str) -> None:
        """Two fireplaces come back from a router restart with each other's address."""
        self.boxes[first], self.boxes[second] = self.boxes[second], self.boxes[first]
        one, two = self.modules.get(first), self.modules.get(second)
        for host, module in ((first, two), (second, one)):
            if module is None:
                self.modules.pop(host, None)
            else:
                self.modules[host] = Module(host=host, name=module.name, mac=module.mac)

    def connect(self, host: str, port: int, timeout: float):
        if ".." in host:
            # What Python does with an address like "192.168..1.4".
            raise UnicodeError("label empty or too long")
        if host not in self.boxes:
            raise OSError("No route to host")
        return self.boxes[host].connect(host, port, timeout)

    def discover(self, *args, **kwargs) -> list[Module]:
        if not self.broadcast_works:
            return []
        return sorted(self.modules.values(), key=lambda module: module.host)

    def discover_host(self, host: str, *args, **kwargs) -> Module | None:
        return self.modules.get(host)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration under test."""
    return


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def network(clock: FakeClock) -> Generator[Network]:
    """Route the integration's connections and searches to the fake network."""
    net = Network(clock)

    def make_mertik(ip: str, **kwargs) -> Mertik:
        return Mertik(ip, connect=net.connect, clock=clock, sleep=clock.sleep, **kwargs)

    with (
        patch("custom_components.mertik.Mertik", new=make_mertik),
        patch("custom_components.mertik.config_flow.Mertik", new=make_mertik),
        patch(
            "custom_components.mertik.MertikDataCoordinator",
            new=partial(MertikDataCoordinator, clock=clock),
        ),
        patch("custom_components.mertik.discover", new=net.discover),
        patch("custom_components.mertik.discover_host", new=net.discover_host),
        patch("custom_components.mertik.coordinator.discover_host", new=net.discover_host),
        patch("custom_components.mertik.config_flow.discover", new=net.discover),
        patch("custom_components.mertik.config_flow.discover_host", new=net.discover_host),
    ):
        yield net


@pytest.fixture
def box(network: Network) -> FakeBox:
    """The WiFi box of the fireplace the config entry points at."""
    return network.add(HOST)


@pytest.fixture
def fire(box: FakeBox) -> FakeFireplace:
    """That fireplace: off, linked to its receiver, no handset."""
    return FakeFireplace(box)


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry as version 2 makes it."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id=MAC,
        data={CONF_NAME: NAME, CONF_HOST: HOST, CONF_MAC: MAC, CONF_MODEL: MODEL},
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
async def coordinator(
    hass: HomeAssistant, entry: MockConfigEntry, fire: FakeFireplace
) -> MertikDataCoordinator:
    """The integration set up against the fake fireplace."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def poll(hass: HomeAssistant, coordinator: MertikDataCoordinator) -> None:
    """Poll the fireplace now and let everything that follows from it finish."""
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str) -> str:
    """The entity ID behind one of the integration's unique ID keys."""
    found = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}-{key}"
    )
    assert found is not None, f"no {platform} entity with key {key}"
    return found


async def call(hass: HomeAssistant, domain: str, service: str, target: str, **data) -> None:
    """Call an entity service and let its effects settle."""
    await hass.services.async_call(
        domain, service, {"entity_id": target, **data}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)


def fireplace_device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry | None:
    """The device of an entry's fireplace."""
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if (DOMAIN, entry.entry_id) in device.identifiers:
            return device
    return None
