#!/usr/bin/env python3
"""Step-by-step diagnostic script for the RP360XP.

Run from the rp360xp/ directory:
    python scripts/diagnose.py [--port /dev/ttyACM0] [--step N]

Steps:
  1  Find port and open serial
  2  Handshake (STATE / VERSION / sbs / SYNC)
  3  Read active preset name
  4  Read first 5 user preset names
  5  Read full active preset structure
"""

import argparse
import logging
import sys
import time

sys.path.insert(0, str(__file__).replace("/scripts/diagnose.py", ""))

from rp360xp.transport import Transport, TransportError
from rp360xp.protocol import Protocol, ProtocolError, TimeoutError
from rp360xp.model import Preset

# ------------------------------------------------------------------ logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("diagnose")

# ------------------------------------------------------------------ steps

def step1_find_port(port_arg):
    log.info("=== STEP 1: Find port ===")
    if port_arg:
        port = port_arg
        log.info("Port forced by argument: %s", port)
    else:
        port = Transport.find_port()
        if port is None:
            log.error("Device not found — check USB connection")
            sys.exit(1)
        log.info("Found device at: %s", port)
    return port


def step2_handshake(transport, protocol):
    log.info("=== STEP 2: Handshake ===")

    log.info("  → STATE")
    r = protocol.send_command("rp", path="STATE")
    log.info("  ← STATE response: %r", r)

    log.info("  → VERSION")
    r = protocol.send_command("rp", path="VERSION")
    log.info("  ← VERSION response: %r", r)

    log.info("  → sbs=1")
    r = protocol.send_command("sbs", value=1)
    log.info("  ← sbs response: %r", r)

    log.info("  → system/SYNC")
    r = protocol.send_command("rp", path="system/SYNC")
    log.info("  ← SYNC response: %r", r)

    log.info("Handshake complete")


def step3_active_preset_name(protocol):
    log.info("=== STEP 3: Active preset name ===")
    r = protocol.send_command("rp", path="system/LAST PRES")
    log.info("  Last preset index: %r", r)

    r = protocol.send_command("rp", path="system/PRESETDIRTY")
    log.info("  Preset dirty: %r", r)


def step4_user_preset_names(protocol, count=5):
    log.info("=== STEP 4: First %d user preset names ===", count)
    for i in range(count):
        try:
            r = protocol.send_command("rp", path=f"banks/user/{i}/name")
            log.info("  Preset %d: %r", i + 1, r)
        except TimeoutError:
            log.warning("  Preset %d: timeout", i + 1)


def step5_active_preset(protocol):
    log.info("=== STEP 5: Full active preset ===")
    data = protocol.send_command("rc", path="preset")
    log.info("  Raw response type: %s", type(data))
    log.info("  Raw response: %r", data)

    if isinstance(data, dict):
        blob = data.get("preset", data)
    else:
        blob = data

    try:
        preset = Preset.from_json(blob)
        log.info("  Preset name : %r", preset.name)
        log.info("  Level       : %s", preset.prs_levl)
        log.info("  Slots       : %s", list(preset.slots.keys()))
        for idx, slot in preset.slots.items():
            log.info("    [%d] %-20s  enabled=%s  params=%s",
                     idx, slot.model, slot.enable, list(slot.params.keys()))
    except Exception as exc:
        log.error("  Could not parse preset: %s", exc)

# ------------------------------------------------------------------ main

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None)
    parser.add_argument("--step", type=int, default=5,
                        help="Run steps 1..N (default: all)")
    args = parser.parse_args()

    port = step1_find_port(args.port)
    if args.step < 2:
        return

    transport = Transport()
    try:
        transport.connect(port)
    except TransportError as exc:
        log.error("Could not connect: %s", exc)
        sys.exit(1)

    protocol = Protocol(transport)

    try:
        if args.step >= 2:
            step2_handshake(transport, protocol)
        if args.step >= 3:
            step3_active_preset_name(protocol)
        if args.step >= 4:
            step4_user_preset_names(protocol)
        if args.step >= 5:
            step5_active_preset(protocol)
    except TimeoutError as exc:
        log.error("TIMEOUT: %s", exc)
    except ProtocolError as exc:
        log.error("PROTOCOL ERROR: %s", exc)
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        transport.disconnect()


if __name__ == "__main__":
    main()
