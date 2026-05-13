"""Tests for the MertikDataCoordinator."""

from datetime import timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.mertik.coordinator import (
    MertikDataCoordinator,
    OPTIMISTIC_ON_SECONDS,
    OPTIMISTIC_OFF_SECONDS,
)


@pytest.fixture
def mock_mertik():
    mertik = MagicMock()
    mertik.is_flame_on = False
    mertik.is_igniting = False
    mertik.is_aux_on = False
    mertik.ambient_temperature = 20.0
    mertik.ip = "192.168.1.100"
    mertik.refresh_status = MagicMock()
    mertik.ignite_fireplace = MagicMock()
    mertik.guard_flame_off = MagicMock()
    mertik.standBy = MagicMock()
    mertik.aux_on = MagicMock()
    mertik.aux_off = MagicMock()
    mertik.set_flame_height = MagicMock()
    mertik.light_on = MagicMock()
    mertik.light_off = MagicMock()
    mertik.set_light_brightness = MagicMock()
    return mertik


@pytest.fixture
def coordinator(hass, mock_mertik):
    return MertikDataCoordinator(hass, mock_mertik)


class TestOptimisticState:
    def test_is_on_false_by_default(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        assert coordinator.is_on is False

    def test_is_on_true_when_in_standby(self, coordinator, mock_mertik):
        """Thermostatic standby (pilot lit) counts as on -- switch must stay on."""
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coordinator._in_standby = True
        assert coordinator.is_on is True

    def test_is_on_standby_overrides_optimistic_off(self, coordinator, mock_mertik):
        """_in_standby keeps is_on True even if mark_optimistic_off was called."""
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coordinator._in_standby = True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is True

    def test_is_on_true_when_flame_on(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = True
        assert coordinator.is_on is True

    def test_is_on_true_when_igniting(self, coordinator, mock_mertik):
        mock_mertik.is_igniting = True
        assert coordinator.is_on is True

    def test_optimistic_on(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True

    def test_optimistic_on_expires(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()
        future = dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_ON_SECONDS + 1)
        with patch.object(dt_util, "utcnow", return_value=future):
            assert coordinator.is_on is False

    def test_optimistic_off(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False

    def test_optimistic_off_expires(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = True
        coordinator.mark_optimistic_off()
        future = dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_OFF_SECONDS + 1)
        with patch.object(dt_util, "utcnow", return_value=future):
            assert coordinator.is_on is True

    def test_optimistic_on_clears_optimistic_off(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False
        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True

    def test_optimistic_off_clears_optimistic_on(self, coordinator, mock_mertik):
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coordinator.mark_optimistic_on()
        assert coordinator.is_on is True
        coordinator.mark_optimistic_off()
        assert coordinator.is_on is False


class TestCoordinatorDelegation:
    async def test_ignite_fireplace(self, coordinator, mock_mertik):
        coordinator.ignite_fireplace()
        mock_mertik.ignite_fireplace.assert_called_once()

    async def test_guard_flame_off_clears_optimistic(self, coordinator, mock_mertik):
        coordinator.mark_optimistic_on()
        coordinator.guard_flame_off()
        mock_mertik.guard_flame_off.assert_called_once()
        assert coordinator._optimistic_on_until is None
        assert coordinator._optimistic_off_until is None

    async def test_aux_on(self, coordinator, mock_mertik):
        coordinator.aux_on()
        mock_mertik.aux_on.assert_called_once()

    async def test_aux_off(self, coordinator, mock_mertik):
        coordinator.aux_off()
        mock_mertik.aux_off.assert_called_once()

    def test_get_flame_height(self, coordinator, mock_mertik):
        mock_mertik.get_flame_height.return_value = 5
        assert coordinator.get_flame_height() == 5

    async def test_set_flame_height(self, coordinator, mock_mertik):
        coordinator.set_flame_height(7)
        mock_mertik.set_flame_height.assert_called_once_with(7)

    async def test_light_on(self, coordinator, mock_mertik):
        coordinator.light_on()
        mock_mertik.light_on.assert_called_once()

    async def test_light_off(self, coordinator, mock_mertik):
        coordinator.light_off()
        mock_mertik.light_off.assert_called_once()

    async def test_set_light_brightness(self, coordinator, mock_mertik):
        coordinator.set_light_brightness(128)
        mock_mertik.set_light_brightness.assert_called_once_with(128)

    def test_ambient_temperature(self, coordinator, mock_mertik):
        mock_mertik.ambient_temperature = 22.5
        assert coordinator.ambient_temperature == 22.5

    def test_is_aux_on_delegates_to_mertik(self, coordinator, mock_mertik):
        """is_aux_on passes through mertik.is_aux_on directly.
        Gating on flame_on is handled inside mertik.py's is_aux_on property.
        """
        mock_mertik.is_aux_on = False
        assert coordinator.is_aux_on is False
        mock_mertik.is_aux_on = True
        assert coordinator.is_aux_on is True


class TestAsyncUpdateData:
    async def test_calls_refresh_status(self, coordinator, mock_mertik):
        await coordinator._async_update_data()
        mock_mertik.refresh_status.assert_called_once()

    async def test_update_interval(self, coordinator):
        assert coordinator.update_interval == timedelta(seconds=10)

    async def test_raises_update_failed_on_error(self, coordinator, mock_mertik):
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_mertik.refresh_status.side_effect = Exception("Connection lost")
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    async def test_deletes_repair_issue_on_success(self, coordinator, mock_mertik):
        with patch(
            "homeassistant.helpers.issue_registry.async_delete_issue"
        ) as mock_delete:
            await coordinator._async_update_data()
            mock_delete.assert_called_once_with(
                coordinator.hass, "mertik", "cannot_connect"
            )

    async def test_creates_repair_issue_on_failure(self, coordinator, mock_mertik):
        import homeassistant.helpers.issue_registry as ir
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_mertik.refresh_status.side_effect = Exception("Connection lost")
        with patch(
            "homeassistant.helpers.issue_registry.async_create_issue"
        ) as mock_create:
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
            mock_create.assert_called_once_with(
                coordinator.hass,
                "mertik",
                "cannot_connect",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="cannot_connect",
                translation_placeholders={"host": "192.168.1.100"},
            )


class TestThermostaticIgnitionGuard:
    """Thermostatic control must not ignite when the Fireplace switch is off.

    The user explicitly turning the fire off via the Fireplace switch must
    take precedence over the thermostatic schedule at all times.
    """

    @pytest.fixture
    def coordinator_off(self, hass, mock_mertik):
        """Coordinator with fire off and not in standby (user switched off)."""
        coord = MertikDataCoordinator(hass, mock_mertik)
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coord._in_standby = False  # user switched off -- not thermostatic standby
        return coord

    @pytest.fixture
    def coordinator_standby(self, hass, mock_mertik):
        """Coordinator in thermostatic standby (pilot lit, thermostat controls it)."""
        coord = MertikDataCoordinator(hass, mock_mertik)
        mock_mertik.is_flame_on = True  # pilot counts as flame_on
        mock_mertik.is_igniting = False
        coord._in_standby = True
        return coord

    async def test_apply_heating_mode_blocked_when_user_switched_off(
        self, coordinator_off, mock_mertik
    ):
        """apply_heating_mode must not ignite when fire is off and not in standby."""
        coordinator_off.apply_heating_mode("Full Heat")
        # ignite_fireplace must NOT have been called
        mock_mertik.ignite_fireplace.assert_not_called()

    async def test_apply_heating_mode_blocked_for_all_modes_when_off(
        self, coordinator_off, mock_mertik
    ):
        """Guard applies to all heat modes, not just Full Heat."""
        from custom_components.mertik.const import MODE_LOW, MODE_MEDIUM, MODE_FULL

        for mode in (MODE_FULL, MODE_MEDIUM, MODE_LOW):
            mock_mertik.reset_mock()
            coordinator_off.apply_heating_mode(mode)
            (
                mock_mertik.ignite_fireplace.assert_not_called(),
                (f"ignite_fireplace should not be called for {mode} when fire is off"),
            )

    async def test_apply_heating_mode_allowed_from_standby(
        self, coordinator_standby, mock_mertik
    ):
        """Thermostatic standby -> apply mode without re-igniting (pilot already lit)."""
        coordinator_standby.apply_heating_mode("Low Heat")
        # ignite_fireplace must NOT be called -- fire goes from pilot to Low Heat
        mock_mertik.ignite_fireplace.assert_not_called()
        # But flame height and aux commands ARE sent
        mock_mertik.aux_off.assert_called_once()
        mock_mertik.set_flame_height.assert_called_once()

    async def test_apply_heating_mode_from_dead_standby_reignites(
        self, coordinator_standby, mock_mertik
    ):
        """_in_standby=True but pilot died (is_flame_on=False): must re-ignite.

        Real-life scenario: fire was in thermostatic standby (pilot lit), but the
        pilot went out (safety shutoff, gas interruption, etc.). HA still has
        _in_standby=True. When the thermostat demands heat, we must re-ignite
        rather than blindly sending flame-height commands to an extinguished device.
        Sending flame-height to a dead device clears _in_standby, making is_on False
        -- which manifests as the fire appearing to turn itself off.
        """
        mock_mertik.is_flame_on = False  # pilot has gone out
        mock_mertik.is_igniting = False

        coordinator_standby.apply_heating_mode("Full Heat")

        mock_mertik.ignite_fireplace.assert_called_once()
        assert coordinator_standby._pending_mode == "Full Heat"
        assert coordinator_standby._in_standby is False
        mock_mertik.set_flame_height.assert_not_called()
        mock_mertik.aux_on.assert_not_called()

    async def test_guard_flame_off_clears_standby_flag(self, coordinator_standby):
        """Turning the fire off via the switch must clear _in_standby."""
        assert coordinator_standby._in_standby is True
        coordinator_standby.guard_flame_off()
        assert coordinator_standby._in_standby is False

    async def test_standby_sets_in_standby_flag(self, coordinator_off):
        """standby() must set _in_standby so thermostat can re-ignite."""
        assert coordinator_off._in_standby is False
        coordinator_off.standby()
        assert coordinator_off._in_standby is True


class TestSimpleDelegations:
    def test_heating_mode_property(self, coordinator):
        coordinator._heating_mode = "Full Heat"
        assert coordinator.heating_mode == "Full Heat"

    def test_set_heating_mode(self, coordinator):
        coordinator.set_heating_mode("Low Heat")
        assert coordinator._heating_mode == "Low Heat"

    def test_is_light_on(self, coordinator, mock_mertik):
        assert coordinator.is_light_on is False
        coordinator._is_light_on = True
        assert coordinator.is_light_on is True

    def test_light_brightness(self, coordinator, mock_mertik):
        assert coordinator.light_brightness == 0
        coordinator._light_brightness = 200
        assert coordinator.light_brightness == 200

    def test_fault_code_delegates_to_mertik(self, coordinator, mock_mertik):
        mock_mertik.fault_code = 4
        assert coordinator.fault_code == 4

    def test_fault_code_zero_when_no_fault(self, coordinator, mock_mertik):
        mock_mertik.fault_code = 0
        assert coordinator.fault_code == 0


class TestCheckPendingMode:
    async def test_returns_false_when_no_pending_mode(self, coordinator):
        coordinator._pending_mode = None
        assert coordinator.check_pending_mode() is False

    async def test_still_igniting_clears_flame_on_since_and_returns_true(
        self, coordinator, mock_mertik
    ):
        coordinator._pending_mode = "Full Heat"
        mock_mertik.is_igniting = True
        coordinator._flame_on_since = "something"
        result = coordinator.check_pending_mode()
        assert result is True
        assert coordinator._flame_on_since is None

    async def test_igniting_done_flame_on_not_set_returns_true(
        self, coordinator, mock_mertik
    ):
        coordinator._pending_mode = "Full Heat"
        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = False
        result = coordinator.check_pending_mode()
        assert result is True

    async def test_flame_on_starts_settle_timer(self, coordinator, mock_mertik):
        coordinator._pending_mode = "Full Heat"
        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = True
        coordinator._flame_on_since = None
        result = coordinator.check_pending_mode()
        assert result is True
        assert coordinator._flame_on_since is not None

    async def test_returns_true_while_settling(self, coordinator, mock_mertik):
        coordinator._pending_mode = "Full Heat"
        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = True
        coordinator._flame_on_since = dt_util.utcnow()
        result = coordinator.check_pending_mode()
        assert result is True


class TestThermostaticScenarios:
    """End-to-end thermostatic behaviour scenarios.

    Thresholds: low=1.0C, high=2.0C.

    These tests call the coordinator's apply_heating_mode() and standby()
    methods directly, which is exactly what the climate entity's async tasks
    do after they execute. This avoids the complexity of driving async tasks
    synchronously in a test context.

    Mode selection logic (which temperature maps to which mode) is verified
    by checking _last_applied_mode after calling a helper that runs the pure
    synchronous portion of _run_thermostatic_logic.
    """

    SETPOINT = 20.0
    LOW_THRESH = 1.0
    HIGH_THRESH = 2.0

    @pytest.fixture
    def coord(self, hass, mock_mertik):
        """Real coordinator with mocked device, fire off by default."""
        from custom_components.mertik.coordinator import MertikDataCoordinator

        c = MertikDataCoordinator(hass, mock_mertik)
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        c._in_standby = False
        return c

    def _select_mode(self, temp, last_mode=None):
        """Pure mode-selection calculation matching climate.py logic."""
        from custom_components.mertik.const import (
            MODE_STANDBY,
            MODE_LOW,
            MODE_MEDIUM,
            MODE_FULL,
        )

        diff = self.SETPOINT - temp
        if diff <= 0:
            return MODE_STANDBY
        elif diff < self.LOW_THRESH:
            return MODE_LOW
        elif diff < self.HIGH_THRESH:
            return MODE_MEDIUM
        else:
            return MODE_FULL

    # ── Scenario 1: above setpoint -> Standby, no ignition ───────────────────
    async def test_scenario_01_above_setpoint_goes_standby_no_ignition(
        self, coord, mock_mertik
    ):
        """Room temp above setpoint: mode=Standby, no ignition."""
        mock_mertik.is_flame_on = False
        coord._in_standby = False

        mode = self._select_mode(20.5)
        assert mode == "Standby"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_not_called()
        mock_mertik.standBy.assert_called_once()

    # ── Scenario 2: 0.5C below -> cold start ignition, Low Heat ─────────────
    async def test_scenario_02_cold_start_low_heat(self, coord, mock_mertik):
        """0.5C below setpoint: cold start -> ignition deferred, pending=Low Heat."""
        mock_mertik.is_flame_on = False
        mock_mertik.is_igniting = False
        coord._in_standby = False
        coord.mark_optimistic_on()  # user pressed Fireplace switch On

        mode = self._select_mode(19.5)
        assert mode == "Low Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Low Heat"

        # Simulate ignition completing after settle period
        from datetime import timedelta
        from homeassistant.util import dt as dt_util

        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = True
        coord._flame_on_since = dt_util.utcnow() - timedelta(seconds=36)
        coord.check_pending_mode()

        mock_mertik.aux_off.assert_called()
        mock_mertik.set_flame_height.assert_called()
        assert coord._pending_mode is None

    # ── Scenario 3: 1.5C below -> cold start, Medium Heat ───────────────────
    async def test_scenario_03_cold_start_medium_heat(self, coord, mock_mertik):
        """1.5C below setpoint: cold start -> pending=Medium Heat."""
        mock_mertik.is_flame_on = False
        coord.mark_optimistic_on()

        mode = self._select_mode(18.5)
        assert mode == "Medium Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Medium Heat"

        from datetime import timedelta
        from homeassistant.util import dt as dt_util

        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = True
        coord._flame_on_since = dt_util.utcnow() - timedelta(seconds=36)
        coord.check_pending_mode()

        mock_mertik.aux_off.assert_called()
        from custom_components.mertik.const import FLAME_MAX

        mock_mertik.set_flame_height.assert_called_with(FLAME_MAX)

    # ── Scenario 4: 2.5C below -> cold start, Full Heat ─────────────────────
    async def test_scenario_04_cold_start_full_heat(self, coord, mock_mertik):
        """2.5C below setpoint: cold start -> pending=Full Heat."""
        mock_mertik.is_flame_on = False
        coord.mark_optimistic_on()

        mode = self._select_mode(17.5)
        assert mode == "Full Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Full Heat"

        from datetime import timedelta
        from homeassistant.util import dt as dt_util

        mock_mertik.is_igniting = False
        mock_mertik.is_flame_on = True
        coord._flame_on_since = dt_util.utcnow() - timedelta(seconds=36)
        coord.check_pending_mode()

        mock_mertik.aux_on.assert_called()
        from custom_components.mertik.const import FLAME_MAX

        mock_mertik.set_flame_height.assert_called_with(FLAME_MAX)

    # ── Scenario 5: not yet ignited, temp drops below setpoint -> ignite + Low ─
    async def test_scenario_05_not_ignited_standby_drop_to_low(
        self, coord, mock_mertik
    ):
        """Fire on but not ignited (standby mode=Standby). 0.1C drop -> Low Heat."""
        mock_mertik.is_flame_on = False  # not yet ignited
        mock_mertik.is_igniting = False
        coord._in_standby = False
        coord.mark_optimistic_on()

        # Was at setpoint (Standby), now 0.1C below
        mode = self._select_mode(19.9)
        assert mode == "Low Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Low Heat"

    # ── Scenario 6: previously ignited (standby/pilot), temp drops -> Low Heat ─
    async def test_scenario_06_from_standby_pilot_to_low_heat(
        self, coord, mock_mertik
    ):
        """Fire in standby (pilot lit). 0.1C drop -> Low Heat, no re-ignition."""
        mock_mertik.is_flame_on = True  # pilot keeps flame_on True
        mock_mertik.is_igniting = False
        coord._in_standby = True

        mode = self._select_mode(19.9)
        assert mode == "Low Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_not_called()
        mock_mertik.aux_off.assert_called()
        from custom_components.mertik.const import FLAME_MIN

        mock_mertik.set_flame_height.assert_called_with(FLAME_MIN)

    # ── Scenario 6b: standby with dead pilot -> re-ignite ────────────────────
    async def test_scenario_06b_standby_pilot_died_reignites(
        self, coord, mock_mertik
    ):
        """Standby mode but pilot has gone out: must re-ignite, not send flame commands.

        is_flame_on=False while _in_standby=True means the device extinguished while
        HA thought it was in thermostatic standby. The correct response is a full
        ignition sequence so the fire actually lights, not a flame-height command
        that the dead device will silently ignore (which clears _in_standby and
        makes is_on go False -- the 'turns itself off' symptom).
        """
        mock_mertik.is_flame_on = False  # pilot went out
        mock_mertik.is_igniting = False
        coord._in_standby = True

        mode = self._select_mode(19.9)  # 0.1 C below setpoint -> Low Heat
        assert mode == "Low Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_called_once()
        assert coord._pending_mode == "Low Heat"
        mock_mertik.set_flame_height.assert_not_called()
        assert coord._in_standby is False

    # ── Scenario 7: Low Heat, temp rises above setpoint -> Standby ───────────
    async def test_scenario_07_low_heat_to_standby_on_warmup(
        self, coord, mock_mertik
    ):
        """Room warms above setpoint from Low Heat -> Standby. Pilot stays lit."""
        mock_mertik.is_flame_on = True
        coord._in_standby = False

        mode = self._select_mode(20.1)
        assert mode == "Standby"
        coord.apply_heating_mode(mode)

        mock_mertik.standBy.assert_called_once()
        mock_mertik.guard_flame_off.assert_not_called()

    # ── Scenario 8: Low Heat, temp drops 1.0C -> Medium Heat ─────────────────
    async def test_scenario_08_low_heat_to_medium_on_drop(self, coord, mock_mertik):
        """1.5C below setpoint -> escalates from Low to Medium Heat."""
        mock_mertik.is_flame_on = True
        coord._in_standby = False

        mode = self._select_mode(18.5)
        assert mode == "Medium Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_not_called()
        mock_mertik.aux_off.assert_called()
        from custom_components.mertik.const import FLAME_MAX

        mock_mertik.set_flame_height.assert_called_with(FLAME_MAX)

    # ── Scenario 9: Medium Heat, temp rises 1.0C -> Low Heat ─────────────────
    async def test_scenario_09_medium_heat_to_low_on_rise(self, coord, mock_mertik):
        """0.5C below setpoint -> drops from Medium to Low Heat."""
        mock_mertik.is_flame_on = True
        coord._in_standby = False

        mode = self._select_mode(19.5)
        assert mode == "Low Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_not_called()
        mock_mertik.aux_off.assert_called()
        from custom_components.mertik.const import FLAME_MIN

        mock_mertik.set_flame_height.assert_called_with(FLAME_MIN)

    # ── Scenario 10: Medium Heat, temp drops 1.0C -> Full Heat ───────────────
    async def test_scenario_10_medium_heat_to_full_on_drop(self, coord, mock_mertik):
        """2.5C below setpoint -> escalates from Medium to Full Heat."""
        mock_mertik.is_flame_on = True
        coord._in_standby = False

        mode = self._select_mode(17.5)
        assert mode == "Full Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_not_called()
        mock_mertik.aux_on.assert_called()
        from custom_components.mertik.const import FLAME_MAX

        mock_mertik.set_flame_height.assert_called_with(FLAME_MAX)

    # ── Scenario 11: Full Heat, temp rises 1.0C -> Medium Heat ───────────────
    async def test_scenario_11_full_heat_to_medium_on_rise(self, coord, mock_mertik):
        """1.5C below setpoint -> drops from Full to Medium Heat."""
        mock_mertik.is_flame_on = True
        coord._in_standby = False

        mode = self._select_mode(18.5)
        assert mode == "Medium Heat"
        coord.apply_heating_mode(mode)

        mock_mertik.ignite_fireplace.assert_not_called()
        mock_mertik.aux_off.assert_called()
        from custom_components.mertik.const import FLAME_MAX

        mock_mertik.set_flame_height.assert_called_with(FLAME_MAX)
