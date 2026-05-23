#!/usr/bin/env python3
"""
Serial MitM relay — RP360XP / Nexus
Relay transparent entre ttyGS0 (PC) et ttyACM0 (RP360XP)
avec logging horodaté, marqueurs annotés, reconnexion automatique.
"""

import serial
import threading
import sys
import os
import time
from datetime import datetime

# --- Configuration ---
PORT_PC    = "/dev/ttyGS0"   # gadget vers le PC
PORT_DEV   = "/dev/ttyACM0"  # RP360XP
BAUDRATE   = 115200
LOG_FILE   = "capture.log"
# ---------------------

log_lock  = threading.Lock()
log_fp    = None
byte_count = {"pc": 0, "dev": 0}  # compteurs cumulatifs par direction


def open_log():
    global log_fp
    log_fp = open(LOG_FILE, "a", buffering=1)


def log_event(msg):
    ts = datetime.now().strftime("%Y/%m/%d %H:%M:%S.%f")
    line = f"# [{ts}] {msg}\n"
    with log_lock:
        sys.stdout.write(line)
        sys.stdout.flush()
        if log_fp:
            log_fp.write(line)
            log_fp.flush()


def log_data(direction, data):
    """Format socat-like : header + hex/ASCII sur 16 octets par ligne."""
    ts = datetime.now().strftime("%Y/%m/%d %H:%M:%S.%f")
    arrow = ">" if direction == "pc" else "<"

    with log_lock:
        start = byte_count[direction]
        byte_count[direction] += len(data)
        end = byte_count[direction] - 1

        header = f"{arrow} {ts}  length={len(data)} from={start} to={end}\n"
        sys.stdout.write(header)
        if log_fp:
            log_fp.write(header)

        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_part   = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            line = f" {hex_part:<47}  {ascii_part}\n"
            sys.stdout.write(line)
            if log_fp:
                log_fp.write(line)

        sys.stdout.write("--\n")
        if log_fp:
            log_fp.write("--\n")

        sys.stdout.flush()
        if log_fp:
            log_fp.flush()


def relay_thread(src, dst, direction, stop_event):
    """Lit src, écrit dans dst, logue."""
    while not stop_event.is_set():
        try:
            data = src.read(4096)
            if data:
                log_data(direction, data)
                dst.write(data)
                dst.flush()
        except Exception:
            stop_event.set()
            break


def marker_thread(stop_event):
    """Attend Entrée, demande un texte, insère un marqueur dans le log."""
    while not stop_event.is_set():
        try:
            input()  # bloque jusqu'à Entrée
            if stop_event.is_set():
                break
            sys.stdout.write("Marqueur > ")
            sys.stdout.flush()
            text = input().strip()
            if text:
                log_event(f"MARKER: {text}")
        except EOFError:
            break


def open_port(path, baudrate, label, stop_event):
    """Tente d'ouvrir un port série, réessaie silencieusement."""
    while not stop_event.is_set():
        try:
            port = serial.Serial(path, baudrate, timeout=0.1)
            log_event(f"CONNECT {label} ({path})")
            return port
        except Exception:
            time.sleep(1)
    return None


def run():
    open_log()
    log_event(f"START relay {PORT_PC} <-> {PORT_DEV} @ {BAUDRATE} baud")
    log_event(f"Log: {os.path.abspath(LOG_FILE)}")
    log_event("Appuie sur Entrée pour insérer un marqueur.")

    stop_event = threading.Event()

    # Thread marqueurs (tourne toujours)
    t_marker = threading.Thread(target=marker_thread, args=(stop_event,), daemon=True)
    t_marker.start()

    try:
        while True:
            stop_event.clear()

            pc_port  = open_port(PORT_PC,  BAUDRATE, "PC",     stop_event)
            dev_port = open_port(PORT_DEV, BAUDRATE, "RP360X", stop_event)

            if pc_port is None or dev_port is None:
                break

            t1 = threading.Thread(target=relay_thread, args=(pc_port,  dev_port, "pc",  stop_event), daemon=True)
            t2 = threading.Thread(target=relay_thread, args=(dev_port, pc_port,  "dev", stop_event), daemon=True)
            t1.start()
            t2.start()

            # Attend qu'un thread signale une erreur
            stop_event.wait()

            log_event("DISCONNECT — tentative de reconnexion...")
            try: pc_port.close()
            except Exception: pass
            try: dev_port.close()
            except Exception: pass

            t1.join(timeout=2)
            t2.join(timeout=2)

            time.sleep(2)

    except KeyboardInterrupt:
        log_event("STOP (Ctrl+C)")
        stop_event.set()
    finally:
        if log_fp:
            log_fp.close()


if __name__ == "__main__":
    run()
