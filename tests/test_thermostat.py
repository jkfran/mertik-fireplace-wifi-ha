"""The regulating logic of the Home Assistant thermostat (no Home Assistant needed)."""

from __future__ import annotations

import pytest

from custom_components.mertik.thermostat import (
    FLAME_HEIGHT,
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_STANDBY,
    MIN_CHANGE_INTERVAL,
    SENSOR_GRACE,
    ThermostatState,
    level_for,
    wanted_level,
)


def test_levels_map_to_flame_heights() -> None:
    assert FLAME_HEIGHT == {LEVEL_STANDBY: 0, LEVEL_LOW: 1, LEVEL_HIGH: 12}


@pytest.mark.parametrize(
    ("burning", "flame_height", "level"),
    [
        (False, 0, LEVEL_STANDBY),
        (False, 12, LEVEL_STANDBY),  # not burning, whatever the number says
        (True, 0, LEVEL_STANDBY),
        (True, 1, LEVEL_LOW),
        (True, 6, LEVEL_LOW),
        (True, 7, LEVEL_HIGH),
        (True, 12, LEVEL_HIGH),
    ],
)
def test_level_for(burning: bool, flame_height: int, level: str) -> None:
    assert level_for(burning, flame_height) == level


@pytest.mark.parametrize(
    ("room", "current", "wanted"),
    [
        # Target is 20. Well above it: the pilot, from anywhere.
        (20.3, LEVEL_HIGH, LEVEL_STANDBY),
        (20.3, LEVEL_LOW, LEVEL_STANDBY),
        (21.0, LEVEL_STANDBY, LEVEL_STANDBY),
        # Close to it: nothing lights up, and a low flame keeps burning.
        (20.2, LEVEL_STANDBY, LEVEL_STANDBY),
        (19.8, LEVEL_STANDBY, LEVEL_STANDBY),
        (20.2, LEVEL_LOW, LEVEL_LOW),
        (19.8, LEVEL_LOW, LEVEL_LOW),
        # Below it: a low flame from the pilot.
        (19.7, LEVEL_STANDBY, LEVEL_LOW),
        (19.1, LEVEL_STANDBY, LEVEL_LOW),
        (19.1, LEVEL_LOW, LEVEL_LOW),
        # A degree or more below it: the full flame.
        (19.0, LEVEL_STANDBY, LEVEL_HIGH),
        (19.0, LEVEL_LOW, LEVEL_HIGH),
        (15.0, LEVEL_HIGH, LEVEL_HIGH),
        # The full flame is held until half a degree short of the target.
        (19.4, LEVEL_HIGH, LEVEL_HIGH),
        (19.5, LEVEL_HIGH, LEVEL_LOW),
        (20.0, LEVEL_HIGH, LEVEL_LOW),
    ],
)
def test_wanted_level(room: float, current: str, wanted: str) -> None:
    assert wanted_level(20.0, room, current) == wanted


def test_inactive_thermostat_decides_nothing() -> None:
    state = ThermostatState(active=False, target=20.0)
    assert state.decide(now=0.0, room=10.0, burning=False, flame_height=0) is None


def test_no_decision_when_the_flame_is_already_right() -> None:
    state = ThermostatState(active=True, target=20.0)
    assert state.decide(now=0.0, room=18.0, burning=True, flame_height=12) is None
    assert state.decide(now=0.0, room=21.0, burning=False, flame_height=0) is None


def test_changes_are_spaced() -> None:
    state = ThermostatState(active=True, target=20.0)
    assert state.decide(now=0.0, room=21.0, burning=True, flame_height=12) == LEVEL_STANDBY
    state.last_change = 0.0

    # The room cools right away, but the flame has just been changed.
    late = MIN_CHANGE_INTERVAL - 1
    assert state.decide(now=late, room=18.0, burning=False, flame_height=0) is None
    assert (
        state.decide(now=MIN_CHANGE_INTERVAL, room=18.0, burning=False, flame_height=0)
        == LEVEL_HIGH
    )


def test_sensor_gap_is_tolerated_for_a_while() -> None:
    state = ThermostatState(active=True, target=20.0)

    assert state.decide(now=0.0, room=None, burning=True, flame_height=12) is None
    assert state.decide(now=SENSOR_GRACE - 1, room=None, burning=True, flame_height=12) is None
    assert not state.sensor_lost

    # A reading in between starts the count again.
    assert state.decide(now=SENSOR_GRACE, room=18.0, burning=True, flame_height=12) is None
    assert state.decide(now=SENSOR_GRACE + 1, room=None, burning=True, flame_height=12) is None
    assert (
        state.decide(now=2 * SENSOR_GRACE, room=None, burning=True, flame_height=12) is None
    )


def test_lost_sensor_means_the_pilot_whatever_the_interval() -> None:
    state = ThermostatState(active=True, target=20.0, last_change=SENSOR_GRACE - 1)
    state.decide(now=0.0, room=None, burning=True, flame_height=12)

    decision = state.decide(now=SENSOR_GRACE, room=None, burning=True, flame_height=12)

    assert decision == LEVEL_STANDBY
    assert state.sensor_lost
    # Already on the pilot: nothing more to do, and no heating blind.
    assert state.decide(now=SENSOR_GRACE + 60, room=None, burning=False, flame_height=0) is None


def test_pilot_command_for_a_lost_sensor_is_repeated_sparingly() -> None:
    """The fireplace reports its flame for a while after the command."""
    state = ThermostatState(active=True, target=20.0)
    state.decide(now=0.0, room=None, burning=True, flame_height=12)
    assert state.decide(now=SENSOR_GRACE, room=None, burning=True, flame_height=12) == LEVEL_STANDBY
    state.last_change = SENSOR_GRACE  # set by whoever sends the command

    assert state.decide(now=SENSOR_GRACE + 10, room=None, burning=True, flame_height=12) is None
    # Still a flame after the interval: the command did not take, so once more.
    later = SENSOR_GRACE + MIN_CHANGE_INTERVAL
    assert state.decide(now=later, room=None, burning=True, flame_height=12) == LEVEL_STANDBY


def test_sensor_coming_back_clears_the_lost_flag() -> None:
    state = ThermostatState(active=True, target=20.0)
    state.decide(now=0.0, room=None, burning=False, flame_height=0)
    state.decide(now=SENSOR_GRACE, room=None, burning=False, flame_height=0)
    assert state.sensor_lost

    assert state.decide(now=SENSOR_GRACE + 1, room=18.0, burning=False, flame_height=0) == LEVEL_HIGH
    assert not state.sensor_lost
