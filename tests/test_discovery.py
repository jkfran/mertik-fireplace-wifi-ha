"""Finding WiFi modules with the UDP query (against a fake socket)."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from custom_components.mertik.discovery import (
    QUERY,
    QUERY_PORT,
    REPLY_PORT,
    Module,
    discover,
    discover_host,
    format_mac,
    parse_reply,
)

# What a real module answers, 30 bytes: a 24-byte name field filled up with FF
# in front of the name, then the MAC address.
MAC_BYTES = bytes.fromhex("00233c005ab1")
REPLY = b"\xff" * 13 + b"mmWiFiBoxV2" + MAC_BYTES


class FakeSocket:
    """A UDP socket whose replies are scripted."""

    def __init__(
        self,
        replies: list[tuple[bytes, str]] | None = None,
        *,
        bind_error: bool = False,
        send_error: bool = False,
    ) -> None:
        self.replies = list(replies or [])
        self.bind_error = bind_error
        self.send_error = send_error
        self.bound: tuple[str, int] | None = None
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def setsockopt(self, *args) -> None:
        pass

    def settimeout(self, timeout: float) -> None:
        pass

    def bind(self, address: tuple[str, int]) -> None:
        if self.bind_error:
            raise OSError("Address already in use")
        self.bound = address

    def sendto(self, data: bytes, address: tuple[str, int]) -> None:
        self.sent.append((data, address))
        if self.send_error:
            raise OSError("Network is unreachable")

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        if self.replies:
            data, host = self.replies.pop(0)
            return data, (host, QUERY_PORT)
        time.sleep(0.005)
        raise TimeoutError

    def close(self) -> None:
        self.closed = True


def test_format_mac() -> None:
    assert format_mac(MAC_BYTES) == "00:23:3c:00:5a:b1"


def test_parse_reply() -> None:
    assert parse_reply(REPLY, "192.168.1.4") == Module(
        host="192.168.1.4", name="mmWiFiBoxV2", mac="00:23:3c:00:5a:b1"
    )


def test_parse_reply_accepts_other_paddings() -> None:
    """Other module versions may pad the name differently, or not at all."""
    for reply in (
        b"mmWiFiBoxV2" + b"\xff" * 5 + MAC_BYTES,
        b"mmWiFiBox" + b"\x00" * 7 + MAC_BYTES,
        b"mmWiFiBoxV3" + MAC_BYTES,
    ):
        module = parse_reply(reply, "192.168.1.4")
        assert module is not None
        assert module.name.startswith("mmWiFiBox")
        assert module.mac == "00:23:3c:00:5a:b1"


def test_parse_reply_rejects_what_is_not_a_module() -> None:
    assert parse_reply(b"", "192.168.1.4") is None
    assert parse_reply(MAC_BYTES, "192.168.1.4") is None  # no name
    assert parse_reply(b"\xff" * 24 + MAC_BYTES, "192.168.1.4") is None  # only padding
    assert parse_reply(b"\xff" * 22 + b"mm" + MAC_BYTES, "192.168.1.4") is None
    assert parse_reply(b"\x00\x00\x00\xf7" + bytes(20) + MAC_BYTES, "192.168.1.4") is None
    assert parse_reply(b"two words" + b"\xff" * 15 + MAC_BYTES, "192.168.1.4") is None
    assert parse_reply(b"x" * 200 + MAC_BYTES, "192.168.1.4") is None


def test_discover() -> None:
    sock = FakeSocket([(REPLY, "192.168.1.4")])

    found = discover(0.05, socket_factory=lambda: sock)

    assert found == [Module(host="192.168.1.4", name="mmWiFiBoxV2", mac="00:23:3c:00:5a:b1")]
    # The query goes out as a broadcast; the answer always comes to port 30719.
    assert sock.sent[0] == (QUERY, ("255.255.255.255", QUERY_PORT))
    assert sock.bound == ("", REPLY_PORT)
    assert sock.closed


def test_discover_lists_each_module_once_sorted_by_address() -> None:
    other = b"\xff" * 13 + b"mmWiFiBoxV2" + bytes.fromhex("00233c111111")
    sock = FakeSocket(
        [
            (other, "192.168.1.9"),
            (REPLY, "192.168.1.4"),
            (REPLY, "192.168.1.4"),  # the query is repeated, so are the answers
            (b"\x00\x00\x00\xf7" + bytes(26), "192.168.1.7"),  # some other device
        ]
    )

    found = discover(0.05, socket_factory=lambda: sock)

    assert [module.host for module in found] == ["192.168.1.4", "192.168.1.9"]


def test_discover_finds_nothing() -> None:
    sock = FakeSocket()
    assert discover(0.05, socket_factory=lambda: sock) == []
    assert sock.closed


def test_discover_stops_as_soon_as_the_wanted_host_answers() -> None:
    sock = FakeSocket([(REPLY, "192.168.1.4")])

    started = time.monotonic()
    found = discover(30.0, ("192.168.1.4",), host="192.168.1.4", socket_factory=lambda: sock)

    assert time.monotonic() - started < 5
    assert [module.host for module in found] == ["192.168.1.4"]
    assert sock.sent == [(QUERY, ("192.168.1.4", QUERY_PORT))]


def test_discover_survives_a_busy_reply_port() -> None:
    """Another program holds the port: the search finds nothing, without an error."""
    sock = FakeSocket([(REPLY, "192.168.1.4")], bind_error=True)
    assert discover(0.05, socket_factory=lambda: sock) == []
    assert sock.closed


def test_discover_survives_a_network_without_broadcast() -> None:
    sock = FakeSocket([(REPLY, "192.168.1.4")], send_error=True)
    assert len(discover(0.05, socket_factory=lambda: sock)) == 1


def test_discover_survives_a_target_that_is_not_an_address() -> None:
    """A typo like "192.168..1.4" fails before anything is sent, with a ValueError."""

    class PickySocket(FakeSocket):
        def sendto(self, data: bytes, address: tuple[str, int]) -> None:
            raise UnicodeError("label empty or too long")

    # Asked through the search itself, which sends to whatever it is given:
    assert discover(0.05, ("192.168..1.4",), socket_factory=PickySocket) == []


def test_discover_host_looks_a_name_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """The answer comes from an IP address; the name it was asked by is kept."""
    monkeypatch.setattr(socket, "gethostbyname", lambda name: "192.168.1.4")
    sock = FakeSocket([(REPLY, "192.168.1.4")])

    module = discover_host("fireplace.lan", 0.05, socket_factory=lambda: sock)

    assert module == Module(host="fireplace.lan", name="mmWiFiBoxV2", mac="00:23:3c:00:5a:b1")
    assert sock.sent == [(QUERY, ("192.168.1.4", QUERY_PORT))]


def test_discover_host_with_a_name_that_does_not_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(name: str) -> str:
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "gethostbyname", fail)
    assert discover_host("fireplace.lan", 0.05, socket_factory=FakeSocket) is None

    def not_a_name(name: str) -> str:
        raise UnicodeError("label empty or too long")

    monkeypatch.setattr(socket, "gethostbyname", not_a_name)
    assert discover_host("192.168..1.4", 0.05, socket_factory=FakeSocket) is None


def test_discover_survives_having_no_socket() -> None:
    def no_socket():
        raise OSError("Too many open files")

    assert discover(0.05, socket_factory=no_socket) == []


def test_searches_take_turns() -> None:
    """Answers come to one port, so two searches must not listen at once."""
    listening = 0
    most = 0

    class CountingSocket(FakeSocket):
        def bind(self, address: tuple[str, int]) -> None:
            nonlocal listening, most
            listening += 1
            most = max(most, listening)

        def close(self) -> None:
            nonlocal listening
            listening -= 1

    threads = [
        threading.Thread(target=discover, args=(0.05,), kwargs={"socket_factory": CountingSocket})
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert most == 1


def test_discover_host() -> None:
    sock = FakeSocket([(REPLY, "192.168.1.4")])
    assert discover_host("192.168.1.4", 0.05, socket_factory=lambda: sock) == Module(
        host="192.168.1.4", name="mmWiFiBoxV2", mac="00:23:3c:00:5a:b1"
    )

    # An answer from elsewhere is not the host asked about.
    sock = FakeSocket([(REPLY, "192.168.1.9")])
    assert discover_host("192.168.1.4", 0.05, socket_factory=lambda: sock) is None

    assert discover_host("192.168.1.4", 0.05, socket_factory=FakeSocket) is None
