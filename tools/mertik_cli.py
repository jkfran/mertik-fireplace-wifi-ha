#!/usr/bin/env python3
"""Look at a Mertik Maxitrol WiFi module from the command line.

    python tools/mertik_cli.py discover
    python tools/mertik_cli.py status 192.168.1.50
    python tools/mertik_cli.py watch 192.168.1.50

It only reads: it finds modules, asks for the status and prints it. It has no
command that changes anything on the fireplace. The output of "watch" while a
fire is lit, burns and is put out is what is needed to check PROTOCOL.md
against a fireplace nobody has measured yet.

Needs Python 3.10 or newer and nothing else: Home Assistant does not have to be
installed.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import time

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "mertik"


def _load(name: str):
    """Load one module of the integration without importing Home Assistant."""
    spec = importlib.util.spec_from_file_location(f"mertik_{name}", COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


protocol = _load("mertik")
discovery = _load("discovery")

WORD_BITS = (
    (0x8000, "receiver"),
    (0x0200, "handset"),
    (0x0100, "shutting-down"),
    (0x0080, "pilot"),
    (0x0040, "fan"),
    (0x0010, "igniting"),
    (0x0008, "aux"),
    (0x0004, "light"),
    (0x0002, "fault"),
    (0x0001, "module"),
)


def describe(fireplace) -> str:
    """One line with everything a status frame says."""
    status = fireplace.status
    if status is None:
        return "no status"
    bits = " ".join(name for mask, name in WORD_BITS if status.word & mask)
    room = "none" if status.room_temperature is None else f"{status.room_temperature:.1f}"
    return (
        f"state={fireplace.state} flame={fireplace.flame_height} "
        f"output={status.burner_output:02X} word={status.word:04X} [{bits}] "
        f"mode={status.mode or status.mode_character} light={status.light_level:02X} "
        f"fan={status.fan_level} flags={status.flags:02X} room={room} "
        f"target={status.target_temperature}"
    )


def cmd_discover(args: argparse.Namespace) -> int:
    modules = discovery.discover(args.timeout)
    for module in modules:
        print(f"{module.host}  {module.name}  {module.mac}")
    if not modules:
        print("No module answered. The search does not cross subnets.", file=sys.stderr)
    return 0 if modules else 1


def cmd_status(args: argparse.Namespace) -> int:
    fireplace = protocol.Mertik(args.host)
    print(describe(fireplace))
    print("frame:", fireplace.last_frame)
    info = fireplace.read_device_info()
    print("device info:", info if info else "no answer")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    fireplace = protocol.Mertik(args.host, refresh=False)
    last = None
    print(f"Watching {args.host} every {args.interval:g} s; Ctrl-C stops.", file=sys.stderr)
    try:
        while True:
            try:
                fireplace.refresh_status()
                frame = fireplace.last_frame
                line = describe(fireplace)
            except protocol.MertikError as err:
                frame = None
                line = f"error: {err}"
            # The end of a frame changes from poll to poll (see PROTOCOL.md), so
            # what counts as a change is the decoded line.
            if args.all or line != last:
                stamp = datetime.now().strftime("%H:%M:%S")
                print(f"{stamp}  {line}", flush=True)
                if args.frames and frame:
                    print(f"          {frame}", flush=True)
                last = line
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    discover = commands.add_parser("discover", help="find WiFi modules on this network")
    discover.add_argument("--timeout", type=float, default=3.0, help="seconds to listen")
    discover.set_defaults(run=cmd_discover)

    status = commands.add_parser("status", help="print the status of one fireplace")
    status.add_argument("host", help="IP address of the WiFi module")
    status.set_defaults(run=cmd_status)

    watch = commands.add_parser("watch", help="print the status whenever it changes")
    watch.add_argument("host", help="IP address of the WiFi module")
    watch.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
    watch.add_argument("--all", action="store_true", help="print every poll, not only changes")
    watch.add_argument("--frames", action="store_true", help="print the raw frame as well")
    watch.set_defaults(run=cmd_watch)

    args = parser.parse_args()
    try:
        return args.run(args)
    except protocol.MertikError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
