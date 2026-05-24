"""Unit tests for transport framing — no hardware required."""

import sys
sys.path.insert(0, str(__file__).replace("/tests/test_transport.py", ""))

from rp360xp.transport import (
    Transport, _checksum, _verify_checksum, CHAN_CMD, CHAN_DATA, CHAN_HACK
)


# ------------------------------------------------------------------ checksum

def test_checksum_state_cmd():
    # Captured packet: ["rp",0,"STATE"]
    pkt = bytes.fromhex("5516004300000000" "5b227270222c302c225354415445225d" + "7c")
    assert _verify_checksum(pkt)

def test_checksum_host_ack():
    pkt = bytes.fromhex("55060002000000 42 b6".replace(" ", ""))
    assert _verify_checksum(pkt)

def test_checksum_device_ack():
    pkt = bytes.fromhex("5506004100000043 76".replace(" ", ""))
    assert _verify_checksum(pkt)

def test_checksum_version_cmd():
    pkt = bytes.fromhex("55180043000100005b227270222c312c2256455253494f4e225d d3".replace(" ", ""))
    assert _verify_checksum(pkt)

def test_checksum_sbs_cmd():
    pkt = bytes.fromhex("5514004300020000 5b2273627322 2c322c22222c315d 38".replace(" ", ""))
    assert _verify_checksum(pkt)


# ------------------------------------------------------------------ build_small

def test_build_small_roundtrip():
    payload = b'["rp",0,"STATE"]'
    pkt = Transport._build_small(CHAN_CMD, 0, payload)
    assert pkt[0] == 0x55
    assert pkt[1] != 0x00               # small packet marker
    assert _verify_checksum(pkt)
    # LEN = total - 3
    pkt_len = pkt[1] | (pkt[2] << 8)
    assert pkt_len == len(pkt) - 3

def test_build_small_matches_capture():
    # Verify our builder produces the exact captured STATE packet
    payload = b'["rp",0,"STATE"]'
    pkt = Transport._build_small(CHAN_CMD, 0, payload)
    expected = bytes.fromhex("5516004300000000 5b227270222c302c225354415445225d 7c".replace(" ", ""))
    assert pkt == expected


# ------------------------------------------------------------------ build_ack

def test_build_ack_matches_capture():
    # Captured host ACK for device SEQ=0: 55 06 00 02 00 00 00 42 b6
    ack = Transport._build_ack(0)
    expected = bytes.fromhex("55060002000000 42 b6".replace(" ", ""))
    assert ack == expected

def test_build_ack_seq_107():
    # Captured: 55 06 00 02 00 6b 00 42 4b  (ACK for device SEQ=0x006b=107)
    ack = Transport._build_ack(107)
    expected = bytes.fromhex("55060002006b0042 4b".replace(" ", ""))
    assert ack == expected


# ------------------------------------------------------------------ parse_buffer

class _FakeTransport(Transport):
    """Transport subclass with stubbed serial port for testing the parser."""
    def __init__(self):
        super().__init__()
        self._acks_sent = []

    def _write(self, data: bytes) -> None:
        self._acks_sent.append(data)

    def feed(self, data: bytes):
        self._buf.extend(data)
        self._parse_buffer()


def test_parse_small_packet():
    t = _FakeTransport()
    # Feed the STATE response from capture session_03
    state_response = bytes.fromhex(
        "55 13 00 42 00 00 00 00"
        "5b227270 72222c302c302c305d 47".replace(" ", "")
    )
    t.feed(state_response)
    pkt = t._rx_queue.get_nowait()
    assert pkt.chan == CHAN_DATA
    assert pkt.seq == 0
    assert pkt.payload == b'["rpr",0,0,0]'

def test_parse_small_packet_auto_ack():
    t = _FakeTransport()
    state_response = bytes.fromhex(
        "5513004200000000"
        "5b22727072222c302c302c305d47"
    )
    t.feed(state_response)
    # Should have sent one ACK for SEQ=0
    assert len(t._acks_sent) == 1
    assert _verify_checksum(t._acks_sent[0])
    assert t._acks_sent[0] == Transport._build_ack(0)

def test_parse_drops_stray_bytes():
    t = _FakeTransport()
    # Leading garbage before valid packet
    garbage = bytes([0x01, 0x02, 0xAB])
    state_response = bytes.fromhex("5513004200000000 5b22727072222c302c302c305d 47".replace(" ", ""))
    t.feed(garbage + state_response)
    pkt = t._rx_queue.get_nowait()
    assert pkt.payload == b'["rpr",0,0,0]'

def test_parse_two_consecutive_packets():
    t = _FakeTransport()
    p1 = bytes.fromhex("5513004200000000 5b22727072222c302c302c305d 47".replace(" ", ""))
    p2 = Transport._build_small(CHAN_CMD, 1, b'["rp",1,"VERSION"]')
    # p2 is host→device (CHAN_CMD) so it won't be put on rx_queue
    # Let's use another DATA packet instead
    p2 = bytes.fromhex(
        "551a004200010000"
        "5b22727072222c312c312c31363937333832345d c5".replace(" ", "")
    )
    t.feed(p1 + p2)
    assert t._rx_queue.qsize() == 2

def test_parse_large_packet():
    t = _FakeTransport()
    # Build a synthetic large packet with a known payload
    payload = b'X' * 100
    pkt_len = 6 + len(payload)   # PAD+CHAN+SEQ+UNK1+UNK2 = 6 bytes overhead (no cksum in LEN)
    raw = bytes([
        0x55,
        0x00, (pkt_len >> 8) & 0xFF, pkt_len & 0xFF,  # 3-byte BE LEN
        0x00,       # PAD
        CHAN_DATA,  # CHAN
        0x12, 0x34, # SEQ = 0x1234 (BE: HI first)
        0x00, 0x00, # UNK
    ]) + payload
    raw += bytes([_checksum(raw)])
    t.feed(raw)
    pkt = t._rx_queue.get_nowait()
    assert pkt.chan == CHAN_DATA
    assert pkt.seq == 0x1234
    assert pkt.payload == payload
