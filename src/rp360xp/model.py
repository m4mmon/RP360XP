"""Data model for RP360XP presets."""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# Fields we know how to handle in a Ctrl dict.  Anything else triggers a warning.
_CTRL_KNOWN = frozenset({"LNK", "MIN", "MAX", "SPEED", "WAVEFORM"})

# LFO waveform index → name
LFO_WAVEFORMS = {0: "TRIANGLE", 1: "SINE", 2: "SQUARE"}


@dataclass
class Ctrl:
    """Binding of a hardware control (expression pedal, footswitch, LFO) to a parameter."""
    lnk: str = ""
    # None means not present in the device JSON (omitted for ENABLE-type stomp controls)
    min: Optional[int] = None
    max: Optional[int] = None
    # lfo1-specific fields (None for all other controllers)
    speed: Optional[int] = None       # 0-185  (0.05 Hz … 10 Hz)
    waveform: Optional[int] = None    # 0=TRIANGLE  1=SINE  2=SQUARE
    # Passthrough bucket for any field we don't model yet
    _extra: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict) -> Ctrl:
        extra = {}
        for k in data:
            if k not in _CTRL_KNOWN:
                log.warning(
                    "Ctrl: unexpected field %r = %r — preserved but not modelled; "
                    "consider updating _CTRL_KNOWN", k, data[k]
                )
                extra[k] = data[k]
        return cls(
            lnk=data.get("LNK", ""),
            min=data.get("MIN"),
            max=data.get("MAX"),
            speed=data.get("SPEED"),
            waveform=data.get("WAVEFORM"),
            _extra=extra,
        )

    def to_json(self) -> dict:
        if not self.lnk:
            return {}
        d: dict = {"LNK": self.lnk}
        if self.min is not None:
            d["MIN"] = self.min
        if self.max is not None:
            d["MAX"] = self.max
        if self.speed is not None:
            d["SPEED"] = self.speed
        if self.waveform is not None:
            d["WAVEFORM"] = self.waveform
        d.update(self._extra)
        return d


@dataclass
class FxSlot:
    """One effect slot in the signal chain."""
    slot: int
    model: str                    # "dist.SCREAMER", "eq.EQ", "vol.VOLUME", …
    params: dict = field(default_factory=dict)   # {PARAM_NAME: value}
    enable: Optional[bool] = True  # None for slots that have no ENABLE (e.g. vol)

    # Whether this slot uses an {"fx": {…}} sub-dict in the JSON (wah/cmpr/dist/amp/
    # gate/mod/dly/rvb do; eq and vol have params at the slot level directly).
    _use_fx_subdict: bool = field(default=True, repr=False)

    @classmethod
    def from_json(cls, slot_idx: int, data: dict) -> FxSlot:
        use_fx = "fx" in data
        if use_fx:
            fx = data["fx"]
            model = fx.get("name", "")
            params = {k: v for k, v in fx.items() if k != "name"}
            enable = bool(data.get("ENABLE", 1))
        else:
            model = data.get("name", "")
            params = {k: v for k, v in data.items() if k not in ("name", "ENABLE")}
            raw_enable = data.get("ENABLE")
            enable = bool(raw_enable) if raw_enable is not None else None

        return cls(
            slot=slot_idx,
            model=model,
            params=params,
            enable=enable,
            _use_fx_subdict=use_fx,
        )

    def to_json(self) -> dict:
        if self._use_fx_subdict:
            d: dict = {}
            if self.enable is not None:
                d["ENABLE"] = int(self.enable)
            d["fx"] = {"name": self.model, **self.params}
            return d
        else:
            d = {"name": self.model, **self.params}
            if self.enable is not None:
                d["ENABLE"] = int(self.enable)
            return d

    @property
    def category(self) -> str:
        """Return the effect category prefix (e.g. 'dist', 'amp')."""
        return self.model.split(".")[0] if "." in self.model else ""


@dataclass
class Preset:
    """A complete RP360XP preset."""
    name: str = ""
    prs_levl: int = 75
    factmodify: int = 0
    slots: dict[int, FxSlot] = field(default_factory=dict)   # {slot_idx: FxSlot}
    ctrls: dict[str, Ctrl] = field(default_factory=dict)     # {ctrl_name: Ctrl}
    # Signal-chain order: list of slot indices as the device sent them.
    # json.loads preserves JSON key insertion order (Python 3.7+), so if the
    # device serialises fxc in chain order this will reflect it; if not it
    # falls back to slot-index order, which is still correct for display.
    chain_order: list[int] = field(default_factory=list)

    # Known control names
    CTRL_NAMES = ("treadle", "altTreadle", "lfo1", "ctrlVSw", "ctrlA", "ctrlB", "ctrlC")

    @classmethod
    def from_json(cls, data: dict) -> Preset:
        preset = cls(
            name=data.get("name", ""),
            prs_levl=data.get("PRS LEVL", 75),
            factmodify=data.get("FACTMODIFY", 0),
        )
        for slot_str, slot_data in data.get("fxc", {}).items():
            idx = int(slot_str)
            preset.slots[idx] = FxSlot.from_json(idx, slot_data)
        # Preserve key order from JSON — reflects chain order if device sends it that way
        preset.chain_order = [int(k) for k in data.get("fxc", {}).keys()]
        for ctrl_name, ctrl_data in data.get("ctrls", {}).items():
            preset.ctrls[ctrl_name] = Ctrl.from_json(ctrl_data) if ctrl_data else Ctrl()
        return preset

    def to_json(self) -> dict:
        fxc = {str(idx): slot.to_json() for idx, slot in sorted(self.slots.items())}
        ctrls = {name: ctrl.to_json() for name, ctrl in self.ctrls.items()}
        return {
            "name": self.name,
            "PRS LEVL": self.prs_levl,
            "FACTMODIFY": self.factmodify,
            "fxc": fxc,
            "ctrls": ctrls,
        }

    def __repr__(self) -> str:
        return f"Preset({self.name!r}, {len(self.slots)} slots)"
