"""JSON protocol layer for the RP360XP.

Sits on top of Transport. Handles:
- Sequence ID counter (independent from transport SEQ)
- JSON encoding/decoding
- Request/response matching
- Reassembly of fragmented responses (multiple transport packets → one JSON message)
- Routing of notifications (np, cm) to registered handlers
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Optional

from .transport import Transport, Packet, CHAN_DATA, CHAN_DACK

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 3.0   # seconds


class ProtocolError(Exception):
    pass


class TimeoutError(ProtocolError):
    pass


class NackError(ProtocolError):
    pass


class Protocol:
    def __init__(self, transport: Transport):
        self._transport = transport
        self._cmd_id = 0
        self._cmd_lock = threading.Lock()    # serialises outgoing commands
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._recv_buf = bytearray()
        self._notification_handlers: list[Callable] = []
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True
        )
        self._dispatch_thread.start()

    # ------------------------------------------------------------------ public

    def on_notification(self, handler: Callable[[list], None]) -> None:
        """Register a callback for unsolicited device messages (np, cm)."""
        self._notification_handlers.append(handler)

    def send_command(
        self,
        cmd: str,
        path: str = "",
        value: Any = None,
        timeout: float = DEFAULT_TIMEOUT,
        on_progress: Any = None,
    ) -> Any:
        """Send a command and return the response value (blocks until reply or timeout).

        on_progress(done, total) is forwarded to the transport layer and called
        after each transport fragment is acknowledged by the device.
        """
        with self._cmd_lock:
            host_id = self._next_id()
            payload = _encode(cmd, host_id, path, value)
            log.debug("→ [%s] id=%d  path=%r  value=%r", cmd, host_id, path, value)

            pending = _Pending()
            with self._pending_lock:
                self._pending[host_id] = pending

            self._transport.send(payload, on_progress=on_progress)

            if not pending.event.wait(timeout):
                with self._pending_lock:
                    self._pending.pop(host_id, None)
                raise TimeoutError(f"[{cmd}] id={host_id} timed out after {timeout}s")

            with self._pending_lock:
                self._pending.pop(host_id, None)

            if pending.error:
                raise pending.error
            return pending.response

    # --------------------------------------------------------------- internals

    def _next_id(self) -> int:
        i = self._cmd_id
        self._cmd_id = (self._cmd_id + 1) & 0xFFFF
        return i

    def _dispatch_loop(self) -> None:
        while True:
            pkt = self._transport.recv(timeout=1.0)
            if pkt is None:
                continue
            if pkt.chan != CHAN_DATA:
                continue
            self._recv_buf.extend(pkt.payload)
            self._try_dispatch()

    def _try_dispatch(self) -> None:
        """Extract and dispatch all complete JSON messages from the accumulation buffer.

        The device may concatenate several JSON messages in a single transport
        packet (e.g. three consecutive np notifications).  json.loads() rejects
        such a string; json.JSONDecoder.raw_decode() lets us peel them off one
        by one and leave any trailing incomplete fragment in the buffer.
        """
        try:
            text = self._recv_buf.decode("utf-8")
        except UnicodeDecodeError:
            return   # wait for more bytes
        decoder = json.JSONDecoder()
        pos = 0
        while pos < len(text):
            # skip whitespace between messages
            while pos < len(text) and text[pos] in " \t\n\r":
                pos += 1
            if pos >= len(text):
                break
            try:
                msg, end = decoder.raw_decode(text, pos)
            except json.JSONDecodeError:
                break   # incomplete — wait for more fragments
            self._handle_message(msg)
            pos = end
        self._recv_buf = bytearray(text[pos:].encode("utf-8"))

    def _handle_message(self, msg: list) -> None:
        if not isinstance(msg, list) or not msg:
            log.warning("Unexpected message format: %r", msg)
            return

        cmd = msg[0]
        log.debug("← %r", msg)

        # ---- notification / device-initiated ----
        # np  = notify property change
        # cm  = change message (preset selection / save confirmation)
        # ndc = notify delete collection (slot deleted)
        # nsc = notify set collection order (chain reordered)
        # nac = notify add collection (slot added)
        if cmd in ("np", "cm", "ndc", "nsc", "nac"):
            for h in self._notification_handlers:
                try:
                    h(msg)
                except Exception:
                    log.exception("Notification handler raised")
            return

        # ---- ack ----
        if cmd == "ack":
            # ["ack", id_device, id_host]
            host_id = msg[2] if len(msg) > 2 else None
            self._resolve(host_id, response=None)
            return

        # ---- nack ----
        if cmd == "nack":
            # ["nack", id_device, id_host, error_code]
            host_id = msg[2] if len(msg) > 2 else None
            error_code = msg[3] if len(msg) > 3 else None
            self._resolve(host_id, error=NackError(f"nack from device (code {error_code})"))
            return

        # ---- command response (e.g. "rpr", "rcr", "sscr", …) ----
        if isinstance(cmd, str) and cmd.endswith("r") and len(msg) >= 3:
            host_id = msg[2]
            value = msg[3] if len(msg) > 3 else None
            self._resolve(host_id, response=value)
            return

        log.warning("Unrecognised message: %r", msg)

    def _resolve(self, host_id: Optional[int], *, response: Any = None,
                 error: Optional[Exception] = None) -> None:
        if host_id is None:
            return
        with self._pending_lock:
            pending = self._pending.get(host_id)
        if pending:
            pending.response = response
            pending.error = error
            pending.event.set()
        else:
            log.debug("Response for unknown id=%s (already timed out?)", host_id)


class _Pending:
    __slots__ = ("event", "response", "error")

    def __init__(self):
        self.event = threading.Event()
        self.response: Any = None
        self.error: Optional[Exception] = None


# ------------------------------------------------------------------ helpers

def _encode(cmd: str, host_id: int, path: str, value: Any) -> bytes:
    """Encode a JSON command array as UTF-8 bytes."""
    parts: list = [cmd, host_id, path]
    if value is not None:
        parts.append(value)
    return json.dumps(parts, separators=(",", ":")).encode("utf-8")
