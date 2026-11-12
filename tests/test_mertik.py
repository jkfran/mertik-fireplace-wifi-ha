"""Tests for the wire protocol (custom_components/mertik/mertik.py)."""

from __future__ import annotations

import threading

import pytest

from custom_components.mertik import mertik as proto
from custom_components.mertik.mertik import (
    Mertik,
    MertikConnectionError,
    MertikReceiverError,
    Status,
    brightness_for_light_level,
    build_request,
    flame_step_for_output,
    light_level_for_brightness,
    reply_id,
    split_frames,
)

from .fakes import (
    NO_RECEIVER,
    REAL_FRAME_OFF,
    REPLY_HEADER,
    FakeBox,
    FakeClock,
    ack,
    framed,
    status_frame,
)

PREFIX = "0233303330333033303830"  # STX + request header, as hex

# Receiver state words used below.
OFF = 0x8003
PILOT = 0x8083
IGNITING = 0x8013
SHUTTING_DOWN = 0x8183


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def box(clock: FakeClock) -> FakeBox:
    return FakeBox(clock)


@pytest.fixture
def fire(box: FakeBox, clock: FakeClock) -> Mertik:
    return Mertik("192.0.2.10", connect=box.connect, clock=clock, sleep=clock.sleep)


def lit(box: FakeBox, fire: Mertik, clock: FakeClock, output: int = 0xFF, **fields) -> None:
    """Put the fake fireplace in a settled burning state."""
    box.status = status_frame(output=output, word=fields.pop("word", PILOT), **fields)
    fire.refresh_status()
    clock.advance(proto.IGNITION_SETTLE + 1)


class TestRequests:
    """The bytes sent must stay exactly what earlier versions sent."""

    @pytest.mark.parametrize(
        ("command", "line_feed", "expected"),
        [
            (proto.CMD_STATUS, False, "303303"),
            (proto.CMD_DEVICE_INFO, False, "303103"),
            (proto.CMD_IGNITE, False, "314103"),
            (proto.CMD_OFF, False, "313003"),
            (proto.CMD_STANDBY, False, "3136303003"),
            (proto.CMD_AUX_ON, True, "32303031030a"),
            (proto.CMD_AUX_OFF, True, "32303030030a"),
            (proto.CMD_LIGHT_ON, False, "3330303103"),
            (proto.CMD_LIGHT_OFF, False, "3330303003"),
            (proto.CMD_MANUAL, False, "423003"),
            (proto.CMD_ECO_ON, False, "4233303103"),
            (proto.CMD_THERMOSTAT_ON, False, "4232303103"),
        ],
    )
    def test_command_bytes(self, command, line_feed, expected):
        assert build_request(command, line_feed=line_feed) == bytes.fromhex(PREFIX + expected)

    def test_prefix_constant_matches_header(self):
        assert build_request("")[:-1] == bytes.fromhex(proto.COMMAND_PREFIX)

    def test_flame_steps_as_sent_before(self):
        legacy = ["3830", "3842", "3937", "4132", "4145", "4239",
                  "4335", "4430", "4443", "4537", "4633", "4646"]
        sent = [f"{output:02X}".encode("ascii").hex() for output in proto.FLAME_STEP_OUTPUTS]
        assert sent == legacy


class TestFraming:
    def test_complete_frames(self):
        assert split_frames("\x02AAA\x03\x02BBB\x03") == (["AAA", "BBB"], "")

    def test_partial_frame_is_kept(self):
        assert split_frames("\x02AAA\x03\x02BB") == (["AAA"], "\x02BB")

    def test_bytes_before_stx_are_dropped(self):
        assert split_frames("noise\x02AAA\x03") == (["AAA"], "")

    def test_nothing_framed(self):
        assert split_frames("noise") == ([], "")

    def test_reply_id(self):
        assert reply_id(REPLY_HEADER + "1A") == "1A"
        assert reply_id("3030303000" + "E101") == "E1"
        assert reply_id("garbage") is None
        assert reply_id(REPLY_HEADER) is None


class TestStatusParsing:
    def test_frame_from_a_real_fireplace(self):
        """Captured from a fireplace that is off, with no handset reading."""
        status = Status.parse(REAL_FRAME_OFF)
        assert status.state == proto.STATE_OFF
        assert status.word == 0x8003
        assert status.burner_output == 0
        assert status.receiver_connected is True
        assert status.pilot_on is False
        assert status.igniting is False
        assert status.shutting_down is False
        assert status.aux_on is False
        assert status.light_on is False
        assert status.mode == proto.MODE_MANUAL
        assert status.room_temperature is None
        assert status.target_temperature == 20.0
        assert status.name is None

    def test_frame_with_the_other_prefix_and_a_name(self):
        """The example from the Gazco measurements: lit at low heat, light on."""
        frame = (
            "303030300003C68080C5AA04000000E100C8"
            + "4C6976696E6720526F6F6D20" + "FF" * 20
        )
        status = Status.parse(frame)
        assert status.state == proto.STATE_ON
        assert status.burner_output == 0x80
        assert status.light_on is True
        assert status.light_level == 0xAA
        assert status.aux_on is False
        assert status.fan_level == 4
        assert status.room_temperature == 22.5
        assert status.target_temperature == 20.0
        assert status.name == "Living Room"

    def test_not_a_status_frame(self):
        assert Status.parse(REPLY_HEADER + "1A") is None
        assert Status.parse("") is None

    def test_too_short(self):
        assert Status.parse(REAL_FRAME_OFF[:30]) is None

    def test_damaged_frame(self):
        assert Status.parse(REAL_FRAME_OFF[:14] + "ZZ" + REAL_FRAME_OFF[16:]) is None

    def test_room_temperature_above_25_5(self):
        """The field is 16 bits: 0x0104 is 26.0 C."""
        assert Status.parse(status_frame(room=0x0104)).room_temperature == 26.0

    def test_no_handset_placeholder(self):
        assert Status.parse(status_frame(room="0666")).room_temperature is None

    def test_unreadable_temperatures(self):
        status = Status.parse(status_frame(room="ZZZZ", target="ZZZZ"))
        assert status.room_temperature is None
        assert status.target_temperature is None

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [("0", "manual"), ("1", "thermostat"), ("2", "eco"), ("3", None)],
    )
    def test_mode(self, mode, expected):
        assert Status.parse(status_frame(mode=mode)).mode == expected

    @pytest.mark.parametrize(
        ("output", "word", "expected"),
        [
            (0x00, 0x820A, "off"),
            (0xFF, 0x8003, "off"),            # output left over, pilot out
            (0x00, 0x821A, "igniting"),
            (0xFF, 0x8213, "igniting"),       # failed ignition
            (0x00, 0x808D, "standby"),
            (0x20, 0x808D, "standby"),
            (0x69, 0x828A, "on"),             # low phase of the flame wave
            (0x80, 0x80C5, "on"),
            (0xFF, 0x828A, "on"),
            (0x8D, 0x838A, "shutting_down"),
            (0x00, 0x81C7, "shutting_down"),
        ],
    )
    def test_state(self, output, word, expected):
        assert Status.parse(status_frame(output=output, word=word)).state == expected

    def test_status_word_bits(self):
        status = Status.parse(status_frame(word=0x8000 | 0x0200 | 0x0040 | 0x0008 | 0x0004))
        assert status.handset_bit and status.fan_on and status.aux_on and status.light_on
        assert not status.faulted
        assert Status.parse(status_frame(word=0x8002)).faulted

    def test_top_bit_clear_keeps_the_other_bits_in_place(self):
        """A word like 001B must not shift: igniting and aux stay where they are."""
        status = Status.parse(status_frame(word=0x001B))
        assert status.receiver_connected is False
        assert status.igniting is True
        assert status.aux_on is True
        assert status.light_on is False


class TestFlameAndLightScales:
    def test_every_step_reads_back_as_itself(self):
        steps = [flame_step_for_output(output) for output in proto.FLAME_STEP_OUTPUTS]
        assert steps == list(range(1, 13))

    @pytest.mark.parametrize(
        ("output", "step"),
        [(0x00, 0), (0x20, 0), (0x40, 0), (0x41, 1), (0x69, 1), (0x7E, 1), (0x84, 1),
         (0x86, 2), (0xEB, 10), (0xFE, 12)],
    )
    def test_in_between_outputs(self, output, step):
        assert flame_step_for_output(output) == step

    def test_light_levels_sent(self):
        assert light_level_for_brightness(1) == 0x77
        assert light_level_for_brightness(255) == 0xFB
        assert 0x77 < light_level_for_brightness(128) < 0xFB
        assert light_level_for_brightness(0) == 0x77
        assert light_level_for_brightness(999) == 0xFB

    def test_light_levels_never_dark(self):
        """0x63 and 0x66 leave the light dark on some fires."""
        assert min(light_level_for_brightness(b) for b in range(1, 256)) >= 0x77

    def test_brightness_read_back_stays_in_range(self):
        assert brightness_for_light_level(0xFF) == 255
        assert brightness_for_light_level(0xFB) == 255
        assert brightness_for_light_level(0x63) == 1
        assert brightness_for_light_level(0x00) == 1

    def test_brightness_round_trip(self):
        for brightness in (1, 64, 128, 200, 255):
            level = light_level_for_brightness(brightness)
            assert abs(brightness_for_light_level(level) - brightness) <= 1


class TestStatusPoll:
    def test_reads_status_on_creation(self, fire, box):
        assert box.requests == ["03"]
        assert fire.state == "off"
        assert fire.status.word == 0x8003

    def test_one_connection_per_request(self, fire, box):
        fire.refresh_status()
        fire.refresh_status()
        assert box.connections == 3
        assert box.open_connections == 0

    def test_no_initial_refresh_when_asked(self, box, clock):
        fire = Mertik("192.0.2.10", connect=box.connect, clock=clock, sleep=clock.sleep, refresh=False)
        assert box.requests == []
        assert fire.state is None
        assert fire.flame_height == 0
        assert fire.is_on is False
        assert fire.ambient_temperature is None

    def test_newest_status_frame_wins(self, fire, box):
        old = status_frame(output=0x80, word=PILOT)
        new = status_frame(output=0xFF, word=PILOT)
        box.script["03"] = [framed(old, new)]
        fire.refresh_status()
        assert fire.burner_output == 0xFF

    def test_frame_split_across_reads(self, fire, box):
        data = framed(status_frame(output=0xC5, word=PILOT))
        box.script["03"] = [data[:20], data[20:70], data[70:]]
        fire.refresh_status()
        assert fire.burner_output == 0xC5

    def test_noise_and_other_frames_are_skipped(self, fire, box):
        box.script["03"] = [b"\x00junk" + framed(ack("30", "01AA"), status_frame(output=0x97, word=PILOT))]
        fire.refresh_status()
        assert fire.burner_output == 0x97

    def test_no_answer_is_retried_once(self, fire, box, clock):
        replies = [[], [framed(status_frame(output=0x80, word=PILOT))]]
        box.script["03"] = lambda: replies.pop(0)
        fire.refresh_status()
        assert box.requests.count("03") == 3  # creation + two attempts
        assert fire.burner_output == 0x80

    def test_no_answer_twice_raises(self, fire, box):
        box.silent = True
        with pytest.raises(MertikConnectionError):
            fire.refresh_status()

    def test_connection_refused_is_retried_once(self, fire, box, clock):
        box.fail_connects = 1
        fire.refresh_status()
        assert proto.RETRY_DELAY in clock.sleeps

    def test_connection_refused_twice_raises(self, fire, box):
        box.fail_connects = 2
        with pytest.raises(MertikConnectionError):
            fire.refresh_status()

    def test_creation_fails_when_unreachable(self, box, clock):
        box.fail_connects = 2
        with pytest.raises(MertikConnectionError):
            Mertik("192.0.2.10", connect=box.connect, clock=clock, sleep=clock.sleep)

    def test_connection_is_closed_after_an_error(self, fire, box):
        box.fail_sends = 2
        with pytest.raises(MertikConnectionError):
            fire.refresh_status()
        assert box.open_connections == 0


class TestCommands:
    def test_ignite(self, fire, box):
        fire.ignite_fireplace()
        assert box.commands == ["1A"]

    def test_off(self, fire, box):
        fire.guard_flame_off()
        assert box.commands == ["10"]

    @pytest.mark.parametrize("step", range(1, 13))
    def test_flame_height(self, fire, box, step):
        fire.set_flame_height(step)
        assert box.commands == [f"16{proto.FLAME_STEP_OUTPUTS[step - 1]:02X}"]

    def test_flame_height_zero_is_standby(self, fire, box):
        fire.set_flame_height(0)
        assert box.commands == ["1600"]

    def test_standby(self, fire, box):
        fire.standBy()
        assert box.commands == ["1600"]

    @pytest.mark.parametrize("step", [-1, 13, 99])
    def test_flame_height_out_of_range(self, fire, box, step):
        with pytest.raises(ValueError):
            fire.set_flame_height(step)
        assert box.commands == []

    def test_aux_commands_end_with_a_line_feed(self, fire, box):
        fire.aux_on()
        fire.aux_off()
        assert box.commands == ["2001", "2000"]
        assert all(raw.endswith(b"\x03\n") for raw in box.raw_requests[-2:])

    def test_light(self, fire, box):
        fire.light_on()
        fire.light_off()
        fire.set_light_brightness(255)
        fire.set_light_brightness(1)
        assert box.commands == ["3001", "3000", "30FEFB", "30FE77"]

    def test_modes(self, fire, box):
        fire.set_manual()
        fire.set_eco()
        assert box.commands == ["B0", "B301"]

    @pytest.mark.parametrize(
        ("temperature", "sent"),
        [(5, "0032"), (20, "00C8"), (20.5, "00CD"), (21.5, "00D7"), (36, "0168"),
         (1, "0032"), (50, "0168")],
    )
    def test_thermostat(self, fire, box, temperature, sent):
        fire.set_thermostat(temperature)
        assert box.commands == ["B201", f"B2FD{sent}"]

    def test_commands_do_not_poll_by_themselves(self, fire, box):
        fire.set_flame_height(6)
        assert box.requests == ["03", "16B9"]


class TestAcknowledgements:
    def test_acknowledged_command_returns_at_once(self, fire, box, clock):
        before = clock.now
        fire.light_on()
        assert clock.now == before

    def test_acknowledgement_after_a_status_frame(self, fire, box):
        box.script["3001"] = [framed(status_frame()), framed(ack("30", "01AA"))]
        fire.light_on()
        assert box.commands == ["3001"]

    def test_status_frame_counts_when_the_box_sends_no_acknowledgement(self, fire, box, clock):
        box.acknowledge = False
        box.status = status_frame(output=0x80, word=PILOT)
        before = clock.now
        fire.set_flame_height(1)
        assert box.commands == ["1680"]
        # It waited a little for an acknowledgement, not the full timeout.
        assert clock.now - before == pytest.approx(proto.ACK_AFTER_STATUS)
        assert fire.burner_output == 0x80

    def test_unanswered_command_is_sent_again(self, fire, box):
        replies = [[], [framed(ack("30"))]]
        box.script["3001"] = lambda: replies.pop(0)
        fire.light_on()
        assert box.commands == ["3001", "3001"]

    def test_unanswered_twice_raises(self, fire, box):
        box.script["3001"] = []
        with pytest.raises(MertikConnectionError):
            fire.light_on()
        assert box.commands == ["3001", "3001"]

    def test_ignite_is_never_sent_twice(self, fire, box):
        box.script["1A"] = []
        with pytest.raises(MertikConnectionError):
            fire.ignite_fireplace()
        assert box.commands == ["1A"]

    def test_ignite_is_retried_when_it_could_not_be_delivered(self, fire, box):
        box.fail_connects = 1
        fire.ignite_fireplace()
        assert box.commands == ["1A"]

    def test_ignite_not_resent_after_a_failed_send(self, fire, box):
        """A send error may still have delivered the command."""
        box.fail_sends = 1
        fire.ignite_fireplace()
        assert box.commands == ["1A"]

    def test_no_receiver_is_retried_then_raises(self, fire, box, clock):
        box.script["2001"] = [framed(NO_RECEIVER)]
        with pytest.raises(MertikReceiverError):
            fire.aux_on()
        assert box.commands == ["2001", "2001"]
        assert proto.COMMAND_GAP in clock.sleeps

    def test_no_receiver_then_accepted(self, fire, box):
        replies = [[framed(NO_RECEIVER)], [framed(ack("20"))]]
        box.script["2001"] = lambda: replies.pop(0)
        fire.aux_on()
        assert box.commands == ["2001", "2001"]

    def test_ignite_refused_by_a_missing_receiver(self, fire, box):
        box.script["1A"] = [framed(NO_RECEIVER)]
        with pytest.raises(MertikReceiverError):
            fire.ignite_fireplace()
        assert box.commands == ["1A"]


class TestPacing:
    def test_gap_between_commands(self, fire, box, clock):
        fire.light_on()
        clock.advance(0.5)
        fire.light_off()
        assert clock.sleeps == [pytest.approx(proto.COMMAND_GAP - 0.5)]

    def test_no_wait_when_enough_time_passed(self, fire, box, clock):
        fire.light_on()
        clock.advance(proto.COMMAND_GAP + 0.1)
        fire.light_off()
        assert clock.sleeps == []

    def test_status_polls_do_not_wait(self, fire, box, clock):
        fire.light_on()
        fire.refresh_status()
        assert clock.sleeps == []

    def test_gap_counts_from_a_failed_command_too(self, fire, box, clock):
        box.script["3001"] = []
        with pytest.raises(MertikConnectionError):
            fire.light_on()
        del box.script["3001"]
        sleeps_before = len(clock.sleeps)
        fire.light_on()
        assert clock.sleeps[sleeps_before:] == [pytest.approx(proto.COMMAND_GAP)]

    def test_aux_waits_for_the_valve(self, fire, box, clock):
        fire.set_flame_height(12)
        clock.advance(3)
        fire.aux_on()
        assert clock.sleeps == [pytest.approx(proto.VALVE_SETTLE - 3)]

    def test_other_commands_do_not_wait_for_the_valve(self, fire, box, clock):
        fire.set_flame_height(12)
        clock.advance(3)
        fire.light_on()
        assert clock.sleeps == []

    def test_thermostat_commands_are_spaced(self, fire, box, clock):
        fire.set_thermostat(21)
        assert clock.sleeps == [pytest.approx(proto.COMMAND_GAP)]

    def test_poll_from_another_thread_waits_for_the_thermostat_sequence(self, fire, box, clock):
        poll = threading.Thread(target=fire.refresh_status)
        original_sleep = clock.sleep

        def sleep_and_poll(seconds):
            original_sleep(seconds)
            if not poll.is_alive() and poll.ident is None:
                poll.start()
                poll.join(timeout=0.2)

        fire._sleep = sleep_and_poll
        fire.set_thermostat(21.5)
        poll.join(timeout=2)
        assert not poll.is_alive()
        assert box.requests[1:] == ["B201", "B2FD00D7", "03"]


class TestStateTracking:
    def test_burning(self, fire, box, clock):
        lit(box, fire, clock, output=0xB9)
        assert fire.state == "on"
        assert fire.is_on and fire.is_pilot_on and fire.is_burning
        assert fire.flame_height == 6
        assert fire.get_flame_height() == 6

    def test_standby(self, fire, box, clock):
        lit(box, fire, clock, output=0x00)
        assert fire.state == "standby"
        assert fire.is_on and fire.is_pilot_on
        assert not fire.is_burning
        assert fire.flame_height == 0

    def test_cold_fireplace_with_a_full_burner_reading_is_off(self, fire, box):
        box.status = status_frame(output=0xFF, word=OFF)
        fire.refresh_status()
        assert fire.state == "off"
        assert not fire.is_on
        assert fire.flame_height == 0

    def test_low_modulated_flame_counts_as_burning(self, fire, box, clock):
        lit(box, fire, clock, output=0x69)
        assert fire.state == "on"
        assert fire.flame_height == 1

    def test_aux_and_light(self, fire, box, clock):
        lit(box, fire, clock, word=PILOT | 0x0008 | 0x0004, light=0xFB)
        assert fire.is_aux_on
        assert fire.is_light_on
        assert fire.light_brightness == 255

    def test_light_level_is_ignored_while_the_light_is_off(self, fire, box, clock):
        lit(box, fire, clock, light=0xAA)
        assert not fire.is_light_on
        assert fire.light_brightness == 0

    def test_full_light_level_from_the_app_stays_in_range(self, fire, box, clock):
        lit(box, fire, clock, word=PILOT | 0x0004, light=0xFF)
        assert fire.light_brightness == 255

    def test_modes_and_temperatures(self, fire, box, clock):
        lit(box, fire, clock, mode="1", room=0x00E1, target=0x00D7)
        assert fire.mode == "thermostat"
        assert fire.is_thermostat_mode
        assert fire.ambient_temperature == 22.5
        assert fire.target_temperature == 21.5
        assert fire.handset_connected is True

    def test_no_handset(self, fire):
        assert fire.ambient_temperature is None
        assert fire.handset_connected is False

    def test_fan(self, fire, box, clock):
        lit(box, fire, clock, word=PILOT | 0x0040, fan=3)
        assert fire.fan_level == 3
        assert fire.is_fan_on

    def test_fault_stored(self, fire, box, clock):
        # The real frame has the bit set: a fireplace without a handset (F44).
        assert fire.is_faulted is True
        lit(box, fire, clock, word=0x8081)
        assert fire.is_faulted is False

    def test_name(self, fire, box, clock):
        lit(box, fire, clock, name="Living Room")
        assert fire.name == "Living Room"


class TestIgnition:
    def test_counts_as_igniting_right_after_the_command(self, fire, box, clock):
        """The box still reports "off" for a moment after an ignite command."""
        fire.ignite_fireplace()
        fire.refresh_status()
        assert fire.state == "igniting"
        assert fire.is_on

    def test_gives_up_when_the_fire_stays_off(self, fire, box, clock):
        fire.ignite_fireplace()
        clock.advance(proto.IGNITE_GRACE + 1)
        fire.refresh_status()
        assert fire.state == "off"

    def test_a_lit_fire_settles_before_it_counts_as_on(self, fire, box, clock):
        fire.ignite_fireplace()
        box.status = status_frame(word=IGNITING)
        fire.refresh_status()
        assert fire.state == "igniting"
        clock.advance(10)
        box.status = status_frame(output=0xFF, word=PILOT)
        fire.refresh_status()
        assert fire.state == "igniting"
        assert fire.flame_height == 0
        clock.advance(proto.IGNITION_SETTLE)
        fire.refresh_status()
        assert fire.state == "on"
        assert fire.flame_height == 12

    def test_frames_without_the_receiver_link_keep_it_igniting(self, fire, box, clock):
        box.status = status_frame(word=0x821A)
        fire.refresh_status()
        clock.advance(10)
        box.status = status_frame(word=0x021A)
        fire.refresh_status()
        assert fire.state == "igniting"
        clock.advance(10)
        box.status = status_frame(output=0xFF, word=0x028A)
        fire.refresh_status()
        assert fire.state == "igniting"

    def test_failed_attempt_reads_off_again(self, fire, box, clock):
        """Measured: igniting, link lost, "on" for a moment, then off."""
        for word, output in ((0x821A, 0), (0x021A, 0), (0x828A, 255), (0x028A, 255)):
            box.status = status_frame(output=output, word=word)
            fire.refresh_status()
            assert fire.state == "igniting"
            clock.advance(10)
        box.status = status_frame(word=0x820A)
        fire.refresh_status()
        assert fire.state == "off"

    def test_ignition_started_elsewhere_is_seen(self, fire, box, clock):
        box.status = status_frame(word=IGNITING)
        fire.refresh_status()
        assert fire.state == "igniting"
        assert fire.is_on


class TestShutdown:
    def test_counts_as_shutting_down_right_after_the_command(self, fire, box, clock):
        lit(box, fire, clock)
        fire.guard_flame_off()
        fire.refresh_status()  # the box still reports it burning
        assert fire.state == "shutting_down"
        assert not fire.is_on

    def test_follows_the_box_after_the_grace(self, fire, box, clock):
        lit(box, fire, clock)
        fire.guard_flame_off()
        clock.advance(proto.OFF_GRACE + 1)
        fire.refresh_status()
        assert fire.state == "on"

    def test_measured_sequence(self, fire, box, clock):
        lit(box, fire, clock, output=0x80, word=0x80C7)
        for output, word, expected in (
            (0x00, 0x81C7, "shutting_down"),
            (0x00, 0x01C7, "shutting_down"),  # link bit clear: last state stays
            (0x00, 0x804B, "off"),
        ):
            box.status = status_frame(output=output, word=word)
            fire.refresh_status()
            assert fire.state == expected
            clock.advance(10)

    def test_off_cancels_a_pending_ignition(self, fire, box, clock):
        fire.ignite_fireplace()
        clock.advance(3)
        fire.guard_flame_off()
        fire.refresh_status()
        assert fire.state == "off"


class TestReceiverLink:
    def test_values_are_kept_while_the_link_is_down(self, fire, box, clock):
        lit(box, fire, clock, output=0xB9)
        box.status = status_frame(output=0x00, word=0x0000)
        fire.refresh_status()
        assert fire.state == "on"
        assert fire.flame_height == 6
        assert fire.receiver_connected is False
        assert fire.receiver_lost is False
        assert fire.last_frame == box.status

    def test_link_counts_as_lost_after_a_while(self, fire, box, clock):
        lit(box, fire, clock)
        box.status = status_frame(word=0x0000)
        fire.refresh_status()
        clock.advance(proto.RECEIVER_LOST_AFTER + 1)
        fire.refresh_status()
        assert fire.receiver_lost is True

    def test_link_restored(self, fire, box, clock):
        lit(box, fire, clock)
        box.status = status_frame(word=0x0000)
        fire.refresh_status()
        clock.advance(proto.RECEIVER_LOST_AFTER + 1)
        box.status = status_frame(output=0x80, word=PILOT)
        fire.refresh_status()
        assert fire.receiver_lost is False
        assert fire.receiver_connected is True
        assert fire.flame_height == 1

    def test_box_that_never_sets_the_link_bit_is_not_judged_on_it(self, box, clock):
        box.status = status_frame(output=0x80, word=0x0080)
        fire = Mertik("192.0.2.10", connect=box.connect, clock=clock, sleep=clock.sleep)
        assert fire.state == "on"
        assert fire.receiver_connected is True

    def test_no_receiver_reply_to_a_poll(self, fire, box, clock):
        box.no_receiver = True
        fire.refresh_status()  # an answer, even if not the one hoped for
        assert fire.receiver_connected is False
        assert fire.receiver_lost is False
        assert fire.state == "off"  # last known
        clock.advance(proto.RECEIVER_LOST_AFTER + 1)
        assert fire.receiver_lost is True

    def test_status_clears_no_receiver(self, fire, box, clock):
        box.no_receiver = True
        fire.refresh_status()
        clock.advance(proto.RECEIVER_LOST_AFTER + 1)
        box.no_receiver = False
        fire.refresh_status()
        assert fire.receiver_lost is False
        assert fire.receiver_connected is True

    def test_unknown_before_any_answer(self, box, clock):
        fire = Mertik("192.0.2.10", connect=box.connect, clock=clock, sleep=clock.sleep, refresh=False)
        assert fire.receiver_connected is None
        assert fire.handset_connected is None


class TestDeviceInfo:
    def test_reply_is_kept(self, fire, box):
        assert fire.device_info is None
        assert fire.read_device_info().startswith("B6R-H8TV4P")
        assert fire.device_info.startswith("B6R-H8TV4P")
        assert box.requests[-1] == "01"

    def test_status_frames_arriving_meanwhile_are_used(self, fire, box):
        box.script["01"] = [framed(status_frame(output=0x80, word=PILOT), REPLY_HEADER + "01" + "ABCD")]
        assert fire.read_device_info() == "ABCD"
        assert fire.burner_output == 0x80

    def test_unanswered_is_not_an_error(self, fire, box):
        box.script["01"] = []
        assert fire.read_device_info() is None
