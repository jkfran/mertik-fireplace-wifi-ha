"""Thermostat regulated by Home Assistant on any temperature sensor.

The fireplace has a thermostat mode of its own, but it only works with the
handset's temperature sensor. This one works with any sensor: Home Assistant
moves the flame between three levels as the room temperature moves around the
target.

It only ever does what the flame-height control does. It never ignites the
fireplace and never puts the pilot out: with the room warm enough it turns the
main burner down to the pilot, and back up from there when heat is needed.
"""

from __future__ import annotations

from dataclasses import dataclass

LEVEL_STANDBY = "standby"  # pilot only
LEVEL_LOW = "low"
LEVEL_HIGH = "high"

FLAME_HEIGHT = {LEVEL_STANDBY: 0, LEVEL_LOW: 1, LEVEL_HIGH: 12}

# Room this far above the target: down to the pilot. This far below: heat.
HYSTERESIS = 0.3
# Room this far below the target or more: full flame.
HIGH_ABOVE = 1.0
# Back from full to low flame once the room is within this of the target.
HIGH_RELEASE = 0.5
# The flame is changed at most this often.
MIN_CHANGE_INTERVAL = 120.0
# A sensor that stops reporting is tolerated this long, then the flame goes down
# to the pilot.
SENSOR_GRACE = 300.0
# Flame steps at or above this count as the high level when taking over.
HIGH_FROM_STEP = 7

DEFAULT_TARGET_TEMPERATURE = 20.0


def level_for(state_is_burning: bool, flame_height: int) -> str:
    """Return the level the fireplace is at now."""
    if not state_is_burning or flame_height <= 0:
        return LEVEL_STANDBY
    return LEVEL_HIGH if flame_height >= HIGH_FROM_STEP else LEVEL_LOW


def wanted_level(target: float, room: float, current: str) -> str:
    """Return the level the thermostat wants, given the level it is at."""
    gap = target - room
    if gap <= -HYSTERESIS:
        return LEVEL_STANDBY
    if current == LEVEL_STANDBY:
        if gap >= HIGH_ABOVE:
            return LEVEL_HIGH
        return LEVEL_LOW if gap >= HYSTERESIS else LEVEL_STANDBY
    if current == LEVEL_HIGH:
        return LEVEL_HIGH if gap > HIGH_RELEASE else LEVEL_LOW
    return LEVEL_HIGH if gap >= HIGH_ABOVE else LEVEL_LOW


@dataclass
class ThermostatState:
    """What the thermostat remembers between polls."""

    active: bool = False
    target: float = DEFAULT_TARGET_TEMPERATURE
    last_change: float | None = None
    sensor_missing_since: float | None = None
    sensor_lost: bool = False

    def decide(
        self,
        *,
        now: float,
        room: float | None,
        burning: bool,
        flame_height: int,
    ) -> str | None:
        """Return the level to switch to now, or None to leave the flame alone."""
        if not self.active:
            return None
        current = level_for(burning, flame_height)

        if room is None:
            if self.sensor_missing_since is None:
                self.sensor_missing_since = now
            if now - self.sensor_missing_since < SENSOR_GRACE:
                return None
            # Not knowing the room temperature, heating blind is the wrong side
            # to err on: down to the pilot at once, whatever the change interval
            # says. Only a repeat of that command waits for the interval, while
            # the fireplace still reports a flame.
            repeat = self.sensor_lost
            self.sensor_lost = True
            if current == LEVEL_STANDBY:
                return None
            if (
                repeat
                and self.last_change is not None
                and now - self.last_change < MIN_CHANGE_INTERVAL
            ):
                return None
            return LEVEL_STANDBY
        self.sensor_missing_since = None
        self.sensor_lost = False

        wanted = wanted_level(self.target, room, current)
        if wanted == current:
            return None
        if self.last_change is not None and now - self.last_change < MIN_CHANGE_INTERVAL:
            return None
        return wanted
