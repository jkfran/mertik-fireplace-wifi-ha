"""The texts: every language complete, and every key the code uses present."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

COMPONENT = Path(__file__).parent.parent / "custom_components" / "mertik"
STRINGS = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
LANGUAGES = sorted(path.stem for path in (COMPONENT / "translations").glob("*.json"))


def flatten(node: dict, prefix: str = "") -> dict[str, str]:
    """Turn nested texts into {"a.b.c": text}."""
    flat: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten(value, path))
        else:
            flat[path] = value
    return flat


def load(language: str) -> dict[str, str]:
    path = COMPONENT / "translations" / f"{language}.json"
    return flatten(json.loads(path.read_text(encoding="utf-8")))


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


def test_languages() -> None:
    assert LANGUAGES == ["da", "en", "es", "fr", "nl"]


def test_english_is_strings_json() -> None:
    assert load("en") == flatten(STRINGS)


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_is_complete(language: str) -> None:
    reference = flatten(STRINGS)
    translation = load(language)

    assert set(translation) == set(reference)
    for key, text in translation.items():
        assert text.strip(), key
        assert placeholders(text) == placeholders(reference[key]), key


async def test_every_entity_has_a_name_and_states(
    hass: HomeAssistant, entry, coordinator
) -> None:
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 17
    for entity in entities:
        if entity.translation_key == "fireplace":
            continue  # the main switch carries the device's name
        texts = STRINGS["entity"][entity.domain][entity.translation_key]
        assert texts["name"]

    assert set(STRINGS["entity"]["sensor"]["status"]["state"]) == {
        "off",
        "standby",
        "igniting",
        "on",
        "shutting_down",
    }
    assert set(STRINGS["entity"]["select"]["mode"]["state"]) == {
        "manual",
        "thermostat",
        "eco",
    }


def test_every_error_the_code_raises_has_a_text() -> None:
    source = "".join(
        path.read_text(encoding="utf-8") for path in COMPONENT.glob("*.py")
    )
    used = set(re.findall(r'translation_key="(\w+)"', source))
    texts = set(STRINGS["exceptions"]) | set(STRINGS["issues"])

    raised = {
        "fireplace_off",
        "shutting_down",
        "no_receiver",
        "cannot_reach",
        "wrong_device",
        "receiver_lost",
    }
    assert raised <= used
    assert raised == texts

    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    for reason in re.findall(r'async_abort\(reason="(\w+)"\)', flow):
        assert reason in STRINGS["config"]["abort"]
    for error in re.findall(r'errors\["base"\] = "(\w+)"', flow):
        assert error in STRINGS["config"]["error"]


def test_icons_belong_to_entities() -> None:
    icons = json.loads((COMPONENT / "icons.json").read_text(encoding="utf-8"))
    for platform, entities in icons["entity"].items():
        for key, icon in entities.items():
            assert icon["default"].startswith("mdi:")
            for state_icon in icon.get("state", {}).values():
                assert state_icon.startswith("mdi:")
            if (platform, key) == ("switch", "fireplace"):
                continue
            assert key in STRINGS["entity"][platform], f"{platform}.{key}"


def test_manifest() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "mertik"
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []
    # Lets Home Assistant tell us when a known module shows up at a new address.
    assert manifest["dhcp"] == [{"registered_devices": True}]
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
