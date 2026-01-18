from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .mertik import Mertik


_LOGGER = logging.getLogger(__name__)
OPTIMISTIC_ON_SECONDS = 20
OPTIMISTIC_OFF_SECONDS = 20


class MertikDataCoordinator(DataUpdateCoordinator):
    """Mertik custom coordinator."""

    def __init__(self, hass, mertik):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Mertik",
            update_interval=timedelta(seconds=10),
        )
        self.mertik = mertik
        self._optimistic_on_until = None
        self._optimistic_off_until = None

    @property
    def is_on(self) -> bool:
        now = dt_util.utcnow()
        if self._optimistic_off_until is not None and now < self._optimistic_off_until:
            return False
        if self.mertik.is_on or self.mertik.is_igniting:
            return True
        if self._optimistic_on_until is None:
            return False
        return now < self._optimistic_on_until

    def mark_optimistic_on(self) -> None:
        self._optimistic_off_until = None
        self._optimistic_on_until = dt_util.utcnow() + timedelta(
            seconds=OPTIMISTIC_ON_SECONDS
        )

    def mark_optimistic_off(self) -> None:
        self._optimistic_on_until = None
        self._optimistic_off_until = dt_util.utcnow() + timedelta(
            seconds=OPTIMISTIC_OFF_SECONDS
        )

    def ignite_fireplace(self):
        self.mertik.ignite_fireplace()

    def guard_flame_off(self):
        self._optimistic_on_until = None
        self._optimistic_off_until = None
        self.mertik.guard_flame_off()

    @property
    def is_aux_on(self) -> bool:
        return self.mertik.is_on and self.mertik.is_aux_on

    def aux_on(self):
        self.mertik.aux_on()

    def aux_off(self):
        self.mertik.aux_off()

    def get_flame_height(self) -> int:
        """Getting flame via Mertik Module"""
        return self.mertik.get_flame_height()

    def set_flame_height(self, flame_height) -> None:
        """Setting flame via Mertik Module"""
        self.mertik.set_flame_height(flame_height)

    @property
    def ambient_temperature(self) -> float:
        return self.mertik.ambient_temperature

    @property
    def is_light_on(self) -> bool:
        return self.mertik.is_light_on

    def light_on(self):
        self.mertik.light_on()

    def light_off(self):
        self.mertik.light_off()

    def set_light_brightness(self, brightness) -> None:
        self.mertik.set_light_brightness(brightness)

    @property
    def light_brightness(self) -> int:
        return self.mertik.light_brightness

    async def _async_update_data(self):
        self.mertik.refresh_status()
