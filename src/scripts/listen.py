#!/usr/bin/env python3
"""Real-time listener for RP360XP device notifications.

Performs a full Nexus-compatible startup sequence, then prints a human-readable
translation of every message the device sends until Ctrl-C.

Usage:
    python scripts/listen.py [--port /dev/ttyACM0]
"""

import argparse
import logging
import signal
import sys
import time

sys.path.insert(0, str(__file__).replace("/scripts/listen.py", ""))

from rp360xp.device import Device, NUM_PRESETS, BANK_USER
from rp360xp.effects_db import EffectsDB
from rp360xp.protocol import ProtocolError, TimeoutError
from rp360xp.transport import TransportError

# ------------------------------------------------------------------ logging

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s.%(msecs)03d  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)

# ------------------------------------------------------------------ helpers

db = EffectsDB()


def _decode_last_pres(raw: int) -> tuple[str, int]:
    """Return (bank_label, 1-based slot) from the LAST PRES raw value.

    The device encodes: 0-98 = user (0-based), 100-198 = factory (0-based).
    """
    if raw >= 100:
        return "factory", raw - 100 + 1
    return "user", raw + 1


def _slot_label(slot_idx: int, preset) -> str:
    """Return 'Slot N (CategoryName)' if preset is available."""
    if preset and slot_idx in preset.slots:
        address = preset.slots[slot_idx].model.split(".")[-1]
        effect = db.by_address(address)
        if effect:
            return f"slot {slot_idx} ({effect['category']} · {effect['displayName']})"
    return f"slot {slot_idx}"


def translate(msg: list, preset=None) -> str:
    """Turn a raw notification message into a human-readable string."""
    if not msg:
        return repr(msg)

    cmd = msg[0]

    # ---- np : notification of a property change sent by the device
    if cmd == "np":
        # Expected: ["np", seq, path, value]
        if len(msg) >= 4:
            path, value = msg[2], msg[3]

            # preset/fxc/N/ENABLE
            if "/fxc/" in path and path.endswith("/ENABLE"):
                parts = path.split("/")
                try:
                    n = int(parts[parts.index("fxc") + 1])
                    state = "enabled" if value else "disabled"
                    return f"Effect {_slot_label(n, preset)} → {state}"
                except (ValueError, IndexError):
                    pass

            # preset/fxc/N/fx/PARAM
            if "/fxc/" in path and "/fx/" in path:
                parts = path.split("/")
                try:
                    n = int(parts[parts.index("fxc") + 1])
                    param = parts[-1]
                    return f"Param change on {_slot_label(n, preset)}: {param} = {value}"
                except (ValueError, IndexError):
                    pass

            # preset/fxc/N/PARAM  (flat slot like VOLUME)
            if "/fxc/" in path:
                parts = path.split("/")
                try:
                    n = int(parts[parts.index("fxc") + 1])
                    param = parts[-1]
                    return f"Param change on {_slot_label(n, preset)}: {param} = {value}"
                except (ValueError, IndexError):
                    pass

            # preset/PRS LEVL
            if path.endswith("PRS LEVL"):
                return f"Preset level → {value}"

            # preset/name
            if path.endswith("/name") or path == "preset/name":
                return f"Preset renamed → \"{value}\""

        return f"np  {msg[1:] if len(msg) > 1 else ''}"

    # ---- cm : control / preset-change message from the device
    if cmd == "cm":
        # Expected: ["cm", seq, path, value] or similar
        if len(msg) >= 3:
            path = msg[2] if len(msg) > 2 else ""
            value = msg[3] if len(msg) > 3 else None

            if "banks/user" in str(path):
                try:
                    idx = int(str(path).split("/")[-1]) + 1
                    return f"Preset changed → user #{idx}"
                except (ValueError, IndexError):
                    pass

            if "banks/factory" in str(path):
                try:
                    idx = int(str(path).split("/")[-1]) + 1
                    return f"Preset changed → factory #{idx}"
                except (ValueError, IndexError):
                    pass

        return f"cm  {msg[1:]}"

    # ---- fallback
    return f"[{cmd}] {msg[1:]}"


# ------------------------------------------------------------------ main

def _ts() -> str:
    return time.strftime("%H:%M:%S")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None)
    parser.add_argument("--skip-names", action="store_true",
                        help="Skip the slow preset-name retrieval")
    args = parser.parse_args()

    dev = Device(port=args.port)
    preset_state = [None]   # mutable ref for use inside closure

    def on_notification(msg: list) -> None:
        human = translate(msg, preset_state[0])
        print(f"  {_ts()}  {human}")
        print(f"           raw: {msg}")
        # Reload preset after a bank change so slot labels stay accurate
        if msg and msg[0] == "cm":
            try:
                preset_state[0] = dev.get_active_preset()
            except Exception:
                pass

    dev.on_notification(on_notification)

    # -- connect + full startup sequence
    print("Connecting…")
    try:
        dev.connect()
    except TransportError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    print("Handshake OK")

    # Fetch current preset for richer notification labels
    try:
        preset_state[0] = dev.get_active_preset()
        last_raw = dev.last_preset_index()
        dirty = dev.is_preset_dirty()
        dirty_marker = " *" if dirty else ""
        bank_label, slot_1 = _decode_last_pres(last_raw)
        print(f"Active preset: {bank_label} #{slot_1} \"{preset_state[0].name}\"{dirty_marker}")
    except Exception as exc:
        print(f"Warning: could not read active preset: {exc}")

    # Fetch all user preset names (slow, like Nexus does)
    if not args.skip_names:
        print(f"Reading user preset names… ", end="", flush=True)
        names = []
        for i in range(NUM_PRESETS):
            try:
                n = dev._protocol.send_command("rp", path=f"banks/{BANK_USER}/{i}/name")
                names.append((i + 1, n))
            except Exception:
                names.append((i + 1, None))
        filled = sum(1 for _, n in names if n)
        print(f"{filled} presets found")

    print("\nListening — press Ctrl-C to quit\n")

    # -- listen loop
    def _shutdown(sig, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    # -- clean disconnect
    print("\nDisconnecting…")
    dev.disconnect()
    print("Done.")


if __name__ == "__main__":
    main()
