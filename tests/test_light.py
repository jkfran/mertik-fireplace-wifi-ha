"""The fireplace light."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from .conftest import call, entity_id, poll
from .fakes import FakeBox, FakeFireplace


@pytest.fixture
def light(hass: HomeAssistant, entry, coordinator) -> str:
    return entity_id(hass, entry, "light", "Light")


async def test_on_and_off(
    hass: HomeAssistant, fire: FakeFireplace, box: FakeBox, light: str
) -> None:
    """The light works with the fire off."""
    fire.set(light_level=0xFB)
    assert hass.states.get(light).state == "off"

    await call(hass, "light", "turn_on", light)
    assert box.commands == ["3001"]
    state = hass.states.get(light)
    assert state.state == "on"
    assert state.attributes["brightness"] == 255

    await call(hass, "light", "turn_off", light)
    assert box.commands == ["3001", "3000"]
    assert hass.states.get(light).state == "off"


@pytest.mark.parametrize(
    ("brightness", "command"),
    # Levels below 0x77 leave the light dark on some fireplaces, so the whole
    # brightness range is spread over 0x77-0xFB.
    [(1, "30FE77"), (128, "30FEB9"), (255, "30FEFB")],
)
async def test_brightness(
    hass: HomeAssistant, box: FakeBox, light: str, brightness: int, command: str
) -> None:
    await call(hass, "light", "turn_on", light, brightness=brightness)

    assert box.commands == [command]
    state = hass.states.get(light)
    assert state.state == "on"
    assert state.attributes["brightness"] == brightness


async def test_light_is_switched_on_if_setting_the_level_did_not(
    hass: HomeAssistant, fire: FakeFireplace, box: FakeBox, light: str
) -> None:
    fire.level_lights = False

    await call(hass, "light", "turn_on", light, brightness=255)

    assert box.commands == ["30FEFB", "3001"]
    assert hass.states.get(light).state == "on"


@pytest.mark.parametrize(
    ("level", "brightness"),
    [(0x77, 1), (0xFB, 255), (0xFF, 255), (0x63, 1), (0x00, 1)],
)
async def test_reported_level_stays_within_the_brightness_range(
    hass: HomeAssistant,
    coordinator,
    fire: FakeFireplace,
    light: str,
    level: int,
    brightness: int,
) -> None:
    """Handsets set levels outside the range this integration sends."""
    fire.set(light=True, light_level=level)
    await poll(hass, coordinator)

    assert hass.states.get(light).attributes["brightness"] == brightness


async def test_changing_brightness_of_a_lit_light_sends_only_the_level(
    hass: HomeAssistant, coordinator, fire: FakeFireplace, box: FakeBox, light: str
) -> None:
    fire.set(light=True, light_level=0xFB)
    await poll(hass, coordinator)

    await call(hass, "light", "turn_on", light, brightness=1)

    assert box.commands == ["30FE77"]
