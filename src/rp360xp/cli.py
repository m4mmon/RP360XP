"""Command-line interface for the RP360XP."""

from __future__ import annotations

import json
import re
import sys
from typing import Optional

import click

from .device import Device, DeviceError, NUM_PRESETS, BANK_USER, BANK_FACTORY
from .effects_db import EffectsDB
from .model import Preset, LFO_WAVEFORMS
from .protocol import ProtocolError, TimeoutError as RpTimeoutError
from .transport import TransportError


# ------------------------------------------------------------------ helpers

def _die(msg: str) -> None:
    click.echo(f"Error: {msg}", err=True)
    sys.exit(1)


def _device(ctx) -> Device:
    return Device(port=ctx.obj["port"])


def _enable_tag(enable) -> str:
    if enable is None:
        return "     "
    return "[ON] " if enable else "[OFF]"


def _print_preset(preset: Preset, *, dirty: bool = False, as_json: bool = False) -> None:
    if as_json:
        click.echo(json.dumps(preset.to_json(), indent=2, ensure_ascii=False))
        return

    db = EffectsDB()
    dirty_marker = " *" if dirty else ""
    click.echo(f'\n"{preset.name}"{dirty_marker}  (level {preset.prs_levl})\n')

    for idx in sorted(preset.slots):
        slot = preset.slots[idx]
        address = slot.model.split(".")[-1] if "." in slot.model else slot.model
        effect = db.by_model_name(slot.model) or db.by_address(address)
        category    = effect["category"]    if effect else ""
        displayname = effect["displayName"] if effect else address
        tag = _enable_tag(slot.enable)
        click.echo(f"  Slot {idx}  {tag}  {category:<12}  {displayname}")
        for param, value in slot.params.items():
            click.echo(f"              {param:<20} {value}")

    if preset.ctrls:
        click.echo()
        click.echo("  Controllers:")
        for name, ctrl in preset.ctrls.items():
            if not ctrl.lnk:
                click.echo(f"    {name}  (unassigned)")
                continue
            min_s = str(ctrl.min) if ctrl.min is not None else "-"
            max_s = str(ctrl.max) if ctrl.max is not None else "-"
            line = f"    {name:<12}  lnk={ctrl.lnk}  min={min_s}  max={max_s}"
            if ctrl.speed is not None:
                line += f"  speed={ctrl.speed}"
            if ctrl.waveform is not None:
                wname = LFO_WAVEFORMS.get(ctrl.waveform, str(ctrl.waveform))
                line += f"  waveform={ctrl.waveform}({wname})"
            click.echo(line)
    click.echo()


# ------------------------------------------------------------------ group

@click.group()
@click.option("--port", default=None, metavar="PORT",
              help="Serial port — auto-detected if omitted")
@click.pass_context
def cli(ctx, port):
    """Control the DigiTech RP360XP from the command line."""
    ctx.ensure_object(dict)
    ctx.obj["port"] = port


# ------------------------------------------------------------------ info

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="JSON output")
@click.pass_context
def info(ctx, as_json):
    """Show current preset name and edit-buffer state."""
    try:
        with _device(ctx) as dev:
            dirty = dev.is_preset_dirty()
            bank, idx = dev.last_preset_info()
            preset = dev.get_active_preset()
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    if as_json:
        click.echo(json.dumps({
            "bank": bank,
            "preset_index": idx,
            "preset_name": preset.name,
            "dirty": dirty,
        }, indent=2))
    else:
        dirty_marker = " [unsaved changes]" if dirty else ""
        click.echo(f"{bank} #{idx + 1}: \"{preset.name}\"{dirty_marker}")


# ------------------------------------------------------------------ list

@cli.command(name="list")
@click.option("--bank", default="user", type=click.Choice(["user", "factory"]),
              show_default=True)
@click.option("--json", "as_json", is_flag=True, help="JSON output")
@click.pass_context
def list_presets(ctx, bank, as_json):
    """List all preset names in a bank (slow — 99 queries)."""
    try:
        with _device(ctx) as dev:
            with click.progressbar(range(NUM_PRESETS), label="Reading presets",
                                   file=sys.stderr) as bar:
                names = []
                for i in bar:
                    try:
                        name = dev._protocol.send_command(
                            "rp", path=f"banks/{bank}/{i}/name"
                        )
                        names.append(name)
                    except Exception:
                        names.append(None)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    if as_json:
        click.echo(json.dumps([
            {"index": i, "name": n} for i, n in enumerate(names)
        ], indent=2, ensure_ascii=False))
    else:
        click.echo(f"\n{'#':>3}  Name")
        click.echo("-" * 40)
        for i, name in enumerate(names):
            if name is not None:
                click.echo(f"{i + 1:>3}  {name}")


# ------------------------------------------------------------------ show

@cli.command()
@click.argument("slot", type=int, required=False, default=None)
@click.option("--bank", default="user", type=click.Choice(["user", "factory"]),
              show_default=True)
@click.option("--json", "as_json", is_flag=True, help="JSON output")
@click.pass_context
def show(ctx, slot, bank, as_json):
    """Show preset detail.

    Without SLOT: shows the current edit buffer.
    With SLOT (1-based): reads that preset from the bank without loading it.
    """
    try:
        with _device(ctx) as dev:
            if slot is None:
                dirty = dev.is_preset_dirty()
                preset = dev.get_active_preset()
            else:
                idx = slot - 1
                if not (0 <= idx < NUM_PRESETS):
                    _die(f"Slot must be 1..{NUM_PRESETS}")
                dirty = False
                b = BANK_USER if bank == "user" else BANK_FACTORY
                preset = dev._get_preset(b, idx)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    _print_preset(preset, dirty=dirty, as_json=as_json)


# ------------------------------------------------------------------ enable / disable

@cli.command()
@click.argument("slot", type=int)
@click.pass_context
def enable(ctx, slot):
    """Enable effect SLOT (0-based) in the edit buffer."""
    try:
        with _device(ctx) as dev:
            dev.set_enable(slot, True)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo(f"Slot {slot} enabled")


@cli.command()
@click.argument("slot", type=int)
@click.pass_context
def disable(ctx, slot):
    """Disable effect SLOT (0-based) in the edit buffer."""
    try:
        with _device(ctx) as dev:
            dev.set_enable(slot, False)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo(f"Slot {slot} disabled")


# ------------------------------------------------------------------ load

@cli.command()
@click.argument("slot", type=int)
@click.option("--bank", default="user", type=click.Choice(["user", "factory"]),
              show_default=True)
@click.pass_context
def load(ctx, slot, bank):
    """Load preset SLOT (1-based) into the edit buffer."""
    idx = slot - 1
    if not (0 <= idx < NUM_PRESETS):
        _die(f"Slot must be 1..{NUM_PRESETS}")
    try:
        with _device(ctx) as dev:
            b = BANK_USER if bank == "user" else BANK_FACTORY
            if b == BANK_USER:
                preset = dev.load_user_preset(idx)
            else:
                preset = dev.load_factory_preset(idx)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    click.echo(f'Loaded: #{slot} "{preset.name}"')


# ------------------------------------------------------------------ save

@cli.command()
@click.argument("slot", type=int, required=False, default=None)
@click.option("--name", default=None, help="Rename before saving")
@click.pass_context
def save(ctx, slot, name):
    """Save the edit buffer.

    Without SLOT: saves back to the current preset's user slot (in-place).
    With SLOT (1-based): saves to that user slot ("save as").
    """
    try:
        with _device(ctx) as dev:
            if slot is None:
                idx = dev.last_preset_index()
            else:
                idx = slot - 1
                if not (0 <= idx < NUM_PRESETS):
                    _die(f"Slot must be 1..{NUM_PRESETS}")
            if name:
                dev.save_and_rename(idx, name)
            else:
                dev.save_to_user_slot(idx)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    label = f' as "{name}"' if name else ""
    click.echo(f"Saved to slot #{idx + 1}{label}")


# ------------------------------------------------------------------ set

@cli.command(name="set")
@click.argument("fx_slot", type=int, metavar="SLOT")
@click.argument("param")
@click.argument("value")
@click.option("--flat", is_flag=True,
              help="Slot has no fx subdict (e.g. the VOLUME slot)")
@click.pass_context
def set_param(ctx, fx_slot, param, value, flat):
    """Set a parameter in the edit buffer (not saved automatically).

    SLOT is the effect slot index (0-based).
    VALUE is cast to int if possible, else sent as string.

    Examples:
      rp360xp set 2 DRIVE 80
      rp360xp set 6 VOLUME 75 --flat
      rp360xp set 3 MODEL dist.SCREAMER
    """
    try:
        v = int(value)
    except ValueError:
        v = value

    try:
        with _device(ctx) as dev:
            if param.upper() == "MODEL":
                dev.set_model(fx_slot, str(v))
            else:
                dev.set_param(fx_slot, param, v, flat=flat)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    click.echo(f"Set slot {fx_slot} / {param} = {value}")


# ------------------------------------------------------------------ delete

@cli.command(name="delete")
@click.argument("fx_slot", type=int, metavar="SLOT")
@click.pass_context
def delete_effect(ctx, fx_slot):
    """Remove the effect from SLOT (0-based) in the edit buffer."""
    try:
        with _device(ctx) as dev:
            dev.delete_effect(fx_slot)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo(f"Slot {fx_slot} cleared")


# ------------------------------------------------------------------ add

@cli.command(name="add")
@click.argument("fx_slot", type=int, metavar="SLOT")
@click.argument("model")
@click.option("--json-data", default=None, metavar="JSON",
              help="Override slot data with a raw JSON string")
@click.pass_context
def add_effect(ctx, fx_slot, model, json_data):
    """Add an effect to SLOT (0-based) in the edit buffer.

    MODEL is an address (e.g. SCREAMER) or a full model ID (e.g. dist.SCREAMER).
    Default parameter values from the effects database are used.

    \b
    Examples:
      rp360xp add 2 SCREAMER
      rp360xp add 2 dist.SCREAMER
      rp360xp add 9 EQ
    """
    db = EffectsDB()

    if json_data:
        try:
            slot_data = json.loads(json_data)
        except json.JSONDecodeError as exc:
            _die(f"Invalid JSON: {exc}")
    else:
        address = model.split(".")[-1].upper() if "." in model else model.upper()
        slot_data = db.build_slot_data(address)
        if slot_data is None:
            _die(f"Unknown effect {model!r}. Use 'rp360xp effects' to browse.")

    try:
        with _device(ctx) as dev:
            dev.add_effect(fx_slot, slot_data)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    model_id = slot_data.get("fx", slot_data).get("name", model) if not json_data else model
    click.echo(f"Added {model_id} to slot {fx_slot}")


# ------------------------------------------------------------------ stomp

@cli.group(name="stomp")
def stomp_group():
    """Manage stomp button assignments."""


@stomp_group.command(name="assign")
@click.argument("ctrl", type=click.Choice(["A", "B", "C", "VSW"]))
@click.argument("fx_slot", type=int, metavar="SLOT")
@click.pass_context
def stomp_assign(ctx, ctrl, fx_slot):
    """Assign a toggle control to switch SLOT's ENABLE.

    A, B, C are the three stomp buttons.
    VSW is the toe switch at the end of the expression pedal travel.
    """
    ctrl_name = "ctrlVSw" if ctrl == "VSW" else f"ctrl{ctrl}"
    try:
        with _device(ctx) as dev:
            dev.assign_stomp(ctrl_name, fx_slot)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo(f"Stomp {ctrl} → slot {fx_slot}")


@stomp_group.command(name="clear")
@click.argument("ctrl", type=click.Choice(["A", "B", "C", "VSW"]))
@click.pass_context
def stomp_clear(ctx, ctrl):
    """Remove the assignment for stomp A, B, C or VSW."""
    ctrl_name = "ctrlVSw" if ctrl == "VSW" else f"ctrl{ctrl}"
    try:
        with _device(ctx) as dev:
            dev.clear_stomp(ctrl_name)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo(f"Stomp {ctrl} cleared")


@stomp_group.command(name="clear-all")
@click.pass_context
def stomp_clear_all(ctx):
    """Remove all toggle control assignments (A, B, C and VSW)."""
    try:
        with _device(ctx) as dev:
            dev.clear_all_stomps()
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo("All stomp assignments cleared")


# ------------------------------------------------------------------ ctrl

_CTRL_CLI_MAP = {"treadle": "treadle", "alt": "altTreadle", "lfo": "lfo1"}
_LFO_WAVEFORM_NAMES = {0: "TRIANGLE", 1: "SINE", 2: "SQUARE"}


@cli.group(name="ctrl")
def ctrl_group():
    """Manage expression pedal and LFO assignments."""


@ctrl_group.command(name="assign")
@click.argument("ctrl", type=click.Choice(["treadle", "alt", "lfo"]))
@click.argument("fx_slot", type=int, metavar="SLOT")
@click.argument("param")
@click.option("--min", "min_val", type=int, default=0, show_default=True,
              help="Parameter value when pedal is up / LFO is at minimum")
@click.option("--max", "max_val", type=int, default=99, show_default=True,
              help="Parameter value when pedal is down / LFO is at maximum")
@click.option("--speed", type=click.IntRange(0, 185), default=74, show_default=True,
              help="[lfo] Speed 0-185 (74 ≈ 0.79 Hz)")
@click.option("--waveform", type=click.IntRange(0, 2), default=0, show_default=True,
              help="[lfo] 0=TRIANGLE  1=SINE  2=SQUARE")
@click.option("--flat", is_flag=True,
              help="Slot has no fx subdict (vol, eq)")
@click.pass_context
def ctrl_assign(ctx, ctrl, fx_slot, param, min_val, max_val, speed, waveform, flat):
    """Assign an expression pedal or LFO to an effect parameter.

    \b
    ctrl choices:
      treadle   main expression pedal
      alt       alternate expression pedal (altTreadle)
      lfo       low-frequency oscillator (lfo1)

    \b
    Examples:
      rp360xp ctrl assign treadle 5 VOLUME --min 50 --max 81 --flat
      rp360xp ctrl assign alt 7 PEDAL --min 3 --max 93
      rp360xp ctrl assign lfo 1 DRIVE --min 15 --max 70 --speed 96 --waveform 0
    """
    ctrl_name = _CTRL_CLI_MAP[ctrl]
    try:
        with _device(ctx) as dev:
            if ctrl == "lfo":
                dev.assign_lfo(fx_slot, param, min_val, max_val, speed, waveform,
                               flat=flat)
            else:
                dev.assign_expression(ctrl_name, fx_slot, param, min_val, max_val,
                                      flat=flat)
    except (TransportError, ProtocolError, ValueError) as exc:
        _die(str(exc))

    label = f"slot {fx_slot} / {param}  [{min_val}..{max_val}]"
    if ctrl == "lfo":
        wname = _LFO_WAVEFORM_NAMES[waveform]
        label += f"  speed={speed}  waveform={waveform}({wname})"
    click.echo(f"{ctrl_name} → {label}")


@ctrl_group.command(name="clear")
@click.argument("ctrl", type=click.Choice(["treadle", "alt", "lfo"]))
@click.pass_context
def ctrl_clear(ctx, ctrl):
    """Remove the expression pedal or LFO assignment."""
    ctrl_name = _CTRL_CLI_MAP[ctrl]
    try:
        with _device(ctx) as dev:
            dev.clear_ctrl(ctrl_name)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo(f"{ctrl_name} cleared")


# ------------------------------------------------------------------ reorder

@cli.command()
@click.argument("order", nargs=-1, type=int, required=True)
@click.pass_context
def reorder(ctx, order):
    """Reorder the effect chain.

    Pass all occupied slot indices (0-based) in the desired signal-chain order.
    The list must be a permutation of the slot indices present in the preset —
    typically 0-9 for a full preset, fewer if some slots are empty.

    The device physically reassigns effects to new slot indices and automatically
    updates all controller (treadle, stomp…) assignments to follow.

    \b
    Example — full preset, put slot 9 first:
      rp360xp reorder 9 0 1 2 3 4 5 6 7 8
    """
    order = list(order)
    if len(order) != len(set(order)):
        _die("Duplicate slot index in order")
    if any(i < 0 for i in order):
        _die("Slot indices must be >= 0")
    try:
        with _device(ctx) as dev:
            dev.reorder_chain(order)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo(f"Chain reordered: {' '.join(str(i) for i in order)}")


# ------------------------------------------------------------------ master-vol

@cli.command(name="master-vol")
@click.argument("value", type=click.IntRange(0, 99), required=False, default=None,
                metavar="[VALUE]")
@click.pass_context
def master_vol(ctx, value):
    """Read or set the master output volume (0-99).

    Without VALUE: display the current master volume.
    With VALUE: set it immediately (the preset is not affected).

    \b
    Note: the device also sends np system/MASTERVOL notifications when the
    physical master-volume knob is turned — the same path, bidirectional.

    \b
    Examples:
      rp360xp master-vol        # read current value
      rp360xp master-vol 75     # set to 75
    """
    try:
        with _device(ctx) as dev:
            if value is None:
                current = dev.get_master_vol()
                click.echo(f"Master volume: {current}")
            else:
                dev.set_master_vol(value)
                click.echo(f"Master volume set to {value}")
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))


# ------------------------------------------------------------------ system

_SYSTEM_PARAMS = {
    # confirmed writable
    "FSWMODE":    "FOOTSWITCH MODE : 0=PRESET 1=STOMP 2=LOOPER  [✓]",
    "EXTFSWMODE": "CONTROL IN : 0=FS3X 1=LOOPER  [✓]",
    "LOOPERPOS":  "PHRASE SAMPLER : 0=SOUND CHECK 1=LOOPER  [✓]",
    "STEREO":     "OUTPUT MODE : 0=MONO 1=STEREO  [✓]",
    "OUTPUTSW":   "OUTPUT TO : 0=AMP 1=MIXER  [✓]",
    "USB REC":    "USB RECORD LVL : 0=-12dB 12=0dB 36=+24dB(max)  [✓]",
    "USB PBKQ":   "USB PLAY MIX : 0=100%RP/0%USB  50=50/50  100=0%RP/100%USB  [✓]",
    # read-only — nack code 3 (pilotés par les boutons physiques uniquement)
    "TEMPO":      "BPM drum machine  [lecture seule]",
    "PATTERN":    "Index pattern batterie  [lecture seule]",
    "LEVEL":      "Niveau drum machine  [lecture seule]",
}


@cli.command(name="system")
@click.argument("param")
@click.argument("value", type=int)
@click.pass_context
def system_param(ctx, param, value):
    """Set a global system parameter (experimental — not exposed by Nexus).

    \b
    Writable parameters:
      FSWMODE     FOOTSWITCH MODE : 0=PRESET  1=STOMP  2=LOOPER
      EXTFSWMODE  CONTROL IN      : 0=FS3X  1=LOOPER
      LOOPERPOS   PHRASE SAMPLER  : 0=SOUND CHECK  1=LOOPER
      STEREO      OUTPUT MODE     : 0=MONO  1=STEREO
      OUTPUTSW    OUTPUT TO       : 0=AMP  1=MIXER
      USB REC     USB RECORD LVL  : 0=-12dB  12=0dB  36=+24dB max
      USB PBKQ    USB PLAY MIX    : 0=100%RP  50=50/50  100=100%USB

    Read-only (nack):
      TEMPO / PATTERN / LEVEL  (drum machine — boutons physiques uniquement)

    Example:
      rp360xp system FSWMODE 1
      rp360xp system OUTPUTSW 1
      rp360xp system "USB REC" 12
    """
    param = param.upper()
    if param not in _SYSTEM_PARAMS:
        known = ", ".join(_SYSTEM_PARAMS)
        click.echo(f"Warning: unknown parameter {param!r}. Known: {known}", err=True)
    try:
        with _device(ctx) as dev:
            dev._protocol.send_command("sp", path=f"system/{param}", value=value)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))
    click.echo(f"system/{param} = {value}")


# ------------------------------------------------------------------ effects

@cli.command(name="effects")
@click.argument("category", required=False, default=None)
@click.argument("address", required=False, default=None)
@click.option("--search", "-s", default=None, metavar="TEXT",
              help="Search by name or address across all categories")
@click.option("--json", "as_json", is_flag=True)
def effects_cmd(category, address, search, as_json):
    """Browse the effects catalogue.

    \b
    rp360xp effects                      list all categories
    rp360xp effects Distortion           list effects in a category
    rp360xp effects Distortion SCREAMER  show params of one effect
    rp360xp effects --search wah         search by name or address
    """
    db = EffectsDB()

    # -- search mode
    if search:
        results = db.find(search)
        if as_json:
            click.echo(json.dumps(results, indent=2))
            return
        if not results:
            click.echo("No effects found.")
            return
        for e in results:
            mid = db.model_id(e["address"]) or f"?.{e['address']}"
            click.echo(f"  {mid:<30} {e['displayName']}  [{e['category']}]")
        return

    # -- category list
    if category is None:
        cats = db.categories()
        if as_json:
            click.echo(json.dumps([
                {"category": c, "count": len(db.by_category(c))}
                for c in cats
            ], indent=2))
            return
        click.echo()
        for cat in cats:
            effects = db.by_category(cat)
            click.echo(f"  {cat} ({len(effects)})")
        click.echo()
        click.echo('Use: rp360xp effects CATEGORY [ADDRESS]')
        return

    # -- resolve category (case-insensitive)
    matched = next((c for c in db.categories()
                    if c.lower() == category.lower()), None)
    if matched is None:
        _die(f"Unknown category {category!r}. "
             f"Available: {', '.join(db.categories())}")

    # -- effect detail
    if address:
        address = address.upper()
        effect = db.by_address(address)
        if effect is None or effect["category"] != matched:
            _die(f"Effect {address!r} not found in {matched}")
        if as_json:
            click.echo(json.dumps(effect, indent=2))
            return
        mid = db.model_id(address) or f"?.{address}"
        click.echo(f'\n{effect["displayName"]}  ({mid})\n')
        params = [p for p in effect.get("params", []) if p["address"] != "ENABLE"]
        for p in params:
            lo, hi = p.get("min", 0), p.get("max", 99)
            click.echo(f'  {p["address"]:<20} {lo}..{hi}')
        click.echo()
        return

    # -- effects in category
    effects = db.by_category(matched)
    if as_json:
        click.echo(json.dumps(effects, indent=2))
        return
    click.echo(f"\n{matched} ({len(effects)} effects)\n")
    click.echo(f"  {'MODEL ID':<30} {'DISPLAY NAME':<28} PARAMS")
    click.echo("  " + "-" * 72)
    for e in effects:
        mid = db.model_id(e["address"]) or f"?.{e['address']}"
        params = [p["address"] for p in e.get("params", [])
                  if p["address"] != "ENABLE"]
        click.echo(f"  {mid:<30} {e['displayName']:<28} {', '.join(params)}")
    click.echo()
    click.echo(f'Use: rp360xp effects {matched} ADDRESS  for param details')
    click.echo()


# ------------------------------------------------------------------ import / export

@cli.command(name="import")
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def import_preset(ctx, file):
    """Load a preset from a .rp360p file into the edit buffer.

    The preset is not saved automatically — use 'save' to persist it to a
    user slot.

    Accepts both the Nexus .rp360p format and the JSON produced by
    'rp360xp show --json'.

    \b
    Example:
      rp360xp import MyPreset.rp360p
      rp360xp import MyPreset.rp360p && rp360xp save 5
    """
    try:
        with open(file, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        _die(f"Cannot read {file}: {exc}")

    data = raw.get("preset", raw) if isinstance(raw, dict) else raw
    try:
        preset = Preset.from_json(data)
    except Exception as exc:
        _die(f"Invalid preset file: {exc}")

    try:
        with _device(ctx) as dev:
            dev.send_preset(preset)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    click.echo(f'Loaded: "{preset.name}"  (not saved — use "save" to persist)')


@cli.command(name="export")
@click.argument("file", type=click.Path())
@click.pass_context
def export_preset(ctx, file):
    """Save the current edit-buffer preset to a .rp360p file.

    \b
    Example:
      rp360xp export MyPreset.rp360p
    """
    try:
        with _device(ctx) as dev:
            preset = dev.get_active_preset()
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(preset.to_json(), f, indent=2, ensure_ascii=False)
    except OSError as exc:
        _die(f"Cannot write {file}: {exc}")

    click.echo(f'Exported: "{preset.name}" → {file}')


# ------------------------------------------------------------------ backup helpers

def _parse_rp360b(content: str) -> list[tuple[int, Preset]]:
    """Parse a Nexus .rp360b backup file.

    Returns list of (0-based index, Preset) for all valid entries.
    """
    parts = re.split(r'^##', content, flags=re.MULTILINE)
    result = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        try:
            data = json.loads(part)
            result.append((i, Preset.from_json(data)))
        except (json.JSONDecodeError, Exception) as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Skipping entry %d in .rp360b: %s", i, exc
            )
    return result


def _write_rp360b(file: str, presets: list) -> int:
    """Write presets to a Nexus-compatible .rp360b file.

    presets is a list of 99 items, each either a Preset or None.
    Returns the number of presets written.
    """
    parts = []
    count = 0
    for p in presets:
        if p is not None:
            parts.append(json.dumps(p.to_json(), indent=3, ensure_ascii=False))
            count += 1
        else:
            parts.append("")   # empty slot — empty JSON section
    # Format: sections joined by \n## with a trailing \n##
    content = "\n##".join(parts) + "\n##"
    with open(file, "w", encoding="utf-8") as f:
        f.write(content)
    return count


# ------------------------------------------------------------------ backup

@cli.command()
@click.argument("file", type=click.Path())
@click.option("--nexus", "nexus_fmt", is_flag=True,
              help="Write Nexus-compatible .rp360b format instead of JSON")
@click.pass_context
def backup(ctx, file, nexus_fmt):
    """Export all user presets to FILE.

    By default writes a JSON file (our own format).
    Use --nexus to write a Nexus-compatible .rp360b file.
    """
    try:
        with _device(ctx) as dev:
            presets = []
            with click.progressbar(range(NUM_PRESETS), label="Backing up",
                                   file=sys.stderr) as bar:
                for i in bar:
                    try:
                        presets.append(dev.get_user_preset(i))
                    except Exception:
                        presets.append(None)
    except (TransportError, ProtocolError) as exc:
        _die(str(exc))

    count = sum(1 for p in presets if p is not None)

    if nexus_fmt:
        _write_rp360b(file, presets)
    else:
        entries = [
            {"slot": i + 1, "preset": p.to_json()} if p else None
            for i, p in enumerate(presets)
        ]
        doc = {"version": 1, "device": "RP360XP", "bank": "user", "presets": entries}
        with open(file, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)

    click.echo(f"Backed up {count} presets to {file}")


# ------------------------------------------------------------------ restore

@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Parse file but do not write to device")
@click.option("--bulk", is_flag=True,
              help="Send all presets in one ssc command (experimental — may nack)")
@click.option("--bulk-timeout", default=300.0, show_default=True, metavar="SECS",
              help="Timeout in seconds for the bulk ssc command")
@click.pass_context
def restore(ctx, file, dry_run, bulk, bulk_timeout):
    """Restore user presets from a backup FILE.

    Accepts both the JSON format produced by 'backup' and the Nexus .rp360b
    format (auto-detected by the .rp360b extension).
    """
    with open(file, encoding="utf-8") as f:
        content = f.read()

    if file.endswith(".rp360b"):
        valid = _parse_rp360b(content)
    else:
        try:
            doc = json.loads(content)
        except json.JSONDecodeError as exc:
            _die(f"Cannot parse backup file: {exc}")
        if doc.get("version") != 1 or doc.get("device") != "RP360XP":
            _die("Unrecognised backup format")
        entries = doc.get("presets", [])
        valid = [(e["slot"] - 1, Preset.from_json(e["preset"]))
                 for e in entries if e is not None]

    click.echo(f"Found {len(valid)} presets in backup")

    if dry_run:
        for idx, p in valid:
            click.echo(f"  #{idx + 1:>3}  {p.name}")
        return

    # Build a 99-slot list (None = empty slot)
    presets: list = [None] * NUM_PRESETS
    for idx, p in valid:
        if 0 <= idx < NUM_PRESETS:
            presets[idx] = p

    total = sum(1 for p in presets if p is not None)

    if bulk:
        click.echo(f"Restoring {total} presets (bulk ssc) — timeout {bulk_timeout}s…")
        try:
            with _device(ctx) as dev:
                with click.progressbar(length=1, label="Sending ",
                                       file=sys.stderr) as bar:
                    bar_state = [0, 1]  # [current, total]

                    def _bulk_progress(done, frag_total):
                        if bar_state[1] != frag_total:
                            bar_state[1] = frag_total
                            bar.length = frag_total
                        delta = done - bar_state[0]
                        if delta > 0:
                            bar.update(delta)
                            bar_state[0] = done

                    written = dev.restore_user_bank_bulk(
                        presets, timeout=bulk_timeout, progress=_bulk_progress,
                    )
        except (TransportError, ProtocolError) as exc:
            _die(str(exc))
        click.echo(f"Restored {written} presets")
    else:
        click.echo(f"Restoring {total} presets — this may take several minutes…")
        try:
            with _device(ctx) as dev:
                with click.progressbar(length=total, label="Restoring",
                                       file=sys.stderr) as bar:
                    done_so_far = [0]

                    def _progress(done, _total):
                        bar.update(done - done_so_far[0])
                        done_so_far[0] = done

                    written = dev.restore_user_bank(presets, progress=_progress)
        except (TransportError, ProtocolError) as exc:
            _die(str(exc))
        click.echo(f"Restored {written} presets")


# ------------------------------------------------------------------ listen

def _decode_notification(msg: list, preset=None) -> tuple[str, bool]:
    """Decode a device notification message.

    Returns (human_readable_string, is_unknown).
    is_unknown=True means we don't fully understand the message — caller should
    log it prominently so new message types can be discovered.
    """
    if not msg or not isinstance(msg, list):
        return repr(msg), True

    cmd = msg[0]

    # ------------------------------------------------------------------ np
    if cmd == "np":
        if len(msg) < 4:
            return f"np  (short)  {msg[1:]}", True
        path, value = msg[2], msg[3]

        # preset/fxc/N/ENABLE
        if "/fxc/" in path and path.endswith("/ENABLE"):
            parts = path.split("/")
            try:
                n = int(parts[parts.index("fxc") + 1])
                state = "ON" if value else "OFF"
                label = _slot_label_for_listen(n, preset)
                return f"Stomp  {label}  →  {state}", False
            except (ValueError, IndexError):
                pass

        # preset/fxc/N/fx/PARAM  or  preset/fxc/N/PARAM  (flat slots)
        if "/fxc/" in path:
            parts = path.split("/")
            try:
                n = int(parts[parts.index("fxc") + 1])
                param = parts[-1]
                label = _slot_label_for_listen(n, preset)
                return f"Param  {label}  {param} = {value}", False
            except (ValueError, IndexError):
                pass

        # preset/name
        if path in ("preset/name", "name") or path.endswith("/name"):
            return f"Name   →  \"{value}\"", False

        # preset/PRS LEVL
        if path.endswith("PRS LEVL"):
            return f"Level  preset  →  {value}", False

        # preset/ctrls/CTRL/PROPERTY  (controller fields)
        if "/ctrls/" in path:
            parts = path.split("/ctrls/")
            if len(parts) == 2:
                ctrl, _, prop = parts[1].partition("/")
                if prop == "LNK":
                    if value:
                        return f"Ctrl   {ctrl}  →  lnk={value}", False
                    return f"Ctrl   {ctrl}  →  unassigned", False
                if prop == "MIN":
                    return f"Ctrl   {ctrl}  min={value}", False
                if prop == "MAX":
                    return f"Ctrl   {ctrl}  max={value}", False
                if prop == "SPEED":
                    return f"Ctrl   {ctrl}  speed={value}", False
                if prop == "WAVEFORM":
                    from .model import LFO_WAVEFORMS
                    wname = LFO_WAVEFORMS.get(value, str(value))
                    return f"Ctrl   {ctrl}  waveform={value} ({wname})", False

        # system/MASTERVOL
        if path == "system/MASTERVOL":
            return f"Vol    master  →  {value}", False

        # system/LAST PRES
        if path == "system/LAST PRES":
            if isinstance(value, int):
                if value >= 100:
                    return f"Pres   factory #{value - 100 + 1}", False
                return f"Pres   user #{value + 1}", False

        # system/PRESETDIRTY
        if path == "system/PRESETDIRTY":
            state = "dirty" if value else "clean"
            return f"Dirty  →  {state}  ({value})", False

        # Unknown np path
        return f"np     {path!r}  =  {value!r}", True

    # ------------------------------------------------------------------ cm
    if cmd == "cm":
        path = msg[2] if len(msg) > 2 else ""
        value = msg[3] if len(msg) > 3 else None

        # cm path='preset' value='banks/user/N'  →  preset saved to slot
        if path == "preset" and isinstance(value, str) and "banks/" in value:
            parts = value.split("/")
            try:
                bank = parts[1]
                idx = int(parts[2]) + 1
                return f"Saved  {bank} #{idx:>2}", False
            except (IndexError, ValueError):
                pass

        # cm path='banks/user/N' value='preset'  →  preset selected
        if "banks/user" in str(path):
            try:
                idx = int(str(path).split("/")[-1]) + 1
                return f"Pres   user #{idx:>2}  selected", False
            except (ValueError, IndexError):
                pass

        if "banks/factory" in str(path):
            try:
                idx = int(str(path).split("/")[-1]) + 1
                return f"Pres   factory #{idx:>2}  selected", False
            except (ValueError, IndexError):
                pass

        return f"cm     path={path!r}  value={value!r}", True

    # ------------------------------------------------------------------ ndc  (slot deleted)
    if cmd == "ndc":
        slot = msg[2] if len(msg) > 2 else "?"
        return f"Del    slot {slot}  removed from chain", False

    # ------------------------------------------------------------------ nac  (slot added)
    if cmd == "nac":
        slot = msg[2] if len(msg) > 2 else "?"
        return f"Add    slot {slot}  added to chain", False

    # ------------------------------------------------------------------ nsc  (chain reordered)
    if cmd == "nsc":
        path = msg[2] if len(msg) > 2 else "?"
        order = msg[3] if len(msg) > 3 else "?"
        return f"Order  {path}  →  {order}", False

    # ------------------------------------------------------------------ unknown
    return f"[{cmd}]  {msg[1:]}", True


def _slot_label_for_listen(n: int, preset) -> str:
    """Short slot label: 'slot N (ModelName)' if preset available."""
    if preset and n in preset.slots:
        model = preset.slots[n].model
        name = model.split(".")[-1] if "." in model else model
        return f"slot {n} ({name})"
    return f"slot {n}"


@cli.command()
@click.option("--no-raw", is_flag=True, help="Hide the raw JSON line")
@click.option("--skip-names", is_flag=True, help="Skip initial preset-name read")
@click.pass_context
def listen(ctx, no_raw, skip_names):
    """Connect and print all device notifications in real time.

    Known messages show a short human-readable summary.
    Unknown messages are prefixed with [?] so new message types can be discovered.
    Press Ctrl-C to quit.
    """
    import signal
    import time as _time

    dev = _device(ctx)
    preset_ref = [None]

    def _ts():
        return _time.strftime("%H:%M:%S")

    def on_notification(msg: list) -> None:
        summary, unknown = _decode_notification(msg, preset_ref[0])
        prefix = "[?] " if unknown else "    "
        click.echo(f"{_ts()}  {prefix}{summary}")
        if not no_raw:
            click.echo(f"           {msg}")
        # Reload preset when slot structure changes so labels stay accurate
        if msg and msg[0] in ("cm", "nac", "ndc", "nsc"):
            try:
                preset_ref[0] = dev.get_active_preset()
            except Exception:
                pass

    dev.on_notification(on_notification)

    click.echo("Connecting…")
    try:
        dev.connect()
    except TransportError as exc:
        _die(str(exc))

    click.echo("Connected.")

    try:
        preset_ref[0] = dev.get_active_preset()
        bank, idx = dev.last_preset_info()
        dirty = dev.is_preset_dirty()
        dirty_s = " (dirty)" if dirty else ""
        click.echo(f"Active: {bank} #{idx + 1} \"{preset_ref[0].name}\"{dirty_s}")
    except Exception as exc:
        click.echo(f"Warning: could not read active preset: {exc}", err=True)

    if not skip_names:
        try:
            names = dev.user_preset_names()
            filled = sum(1 for n in names if n)
            click.echo(f"User bank: {filled} presets")
        except Exception:
            pass

    click.echo("\nListening — Ctrl-C to quit\n")

    def _shutdown(sig, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            _time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    click.echo("\nDisconnecting…")
    dev.disconnect()


# ------------------------------------------------------------------ entry point

def main():
    cli()
