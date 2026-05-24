"""Tests for expression pedal and LFO device methods + CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from rp360xp.cli import cli
from rp360xp.device import Device


# ------------------------------------------------------------------ helpers

def _make_dev():
    dev = Device.__new__(Device)
    dev._protocol = MagicMock()
    return dev


def _make_mock_cm():
    instance = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=instance)
    cm.__exit__ = MagicMock(return_value=False)
    return cm, instance


# ================================================================== device API

# ------------------------------------------------------------------ assign_stomp / ctrlVSw

def test_assign_stomp_vsw():
    dev = _make_dev()
    dev.assign_stomp("ctrlVSw", 7)
    dev._protocol.send_command.assert_called_once_with(
        "ssc", path="preset/ctrls",
        value={"ctrlVSw": {"LNK": "../../fxc/7/ENABLE"}},
    )

def test_assign_stomp_rejects_expression_ctrl():
    dev = _make_dev()
    with pytest.raises(ValueError):
        dev.assign_stomp("treadle", 5)

# ------------------------------------------------------------------ assign_expression

def test_assign_expression_treadle():
    dev = _make_dev()
    dev.assign_expression("treadle", 5, "VOLUME", 50, 81, flat=True)
    dev._protocol.send_command.assert_called_once_with(
        "ssc", path="preset/ctrls",
        value={"treadle": {"LNK": "../../fxc/5/VOLUME", "MIN": 50, "MAX": 81}},
    )

def test_assign_expression_alt_treadle_fx():
    dev = _make_dev()
    dev.assign_expression("altTreadle", 7, "PEDAL", 3, 93)
    dev._protocol.send_command.assert_called_once_with(
        "ssc", path="preset/ctrls",
        value={"altTreadle": {"LNK": "../../fxc/7/fx/PEDAL", "MIN": 3, "MAX": 93}},
    )

def test_assign_expression_rejects_lfo():
    dev = _make_dev()
    with pytest.raises(ValueError, match="treadle"):
        dev.assign_expression("lfo1", 1, "DRIVE")

def test_assign_expression_rejects_stomp():
    dev = _make_dev()
    with pytest.raises(ValueError):
        dev.assign_expression("ctrlA", 1, "DRIVE")

# ------------------------------------------------------------------ assign_lfo

def test_assign_lfo_default_params():
    dev = _make_dev()
    dev.assign_lfo(1, "DRIVE")
    dev._protocol.send_command.assert_called_once_with(
        "ssc", path="preset/ctrls",
        value={"lfo1": {
            "LNK": "../../fxc/1/fx/DRIVE",
            "MIN": 0, "MAX": 99,
            "SPEED": 74, "WAVEFORM": 0,
        }},
    )

def test_assign_lfo_custom_params():
    dev = _make_dev()
    dev.assign_lfo(1, "DRIVE", min_val=15, max_val=70, speed=96, waveform=2)
    dev._protocol.send_command.assert_called_once_with(
        "ssc", path="preset/ctrls",
        value={"lfo1": {
            "LNK": "../../fxc/1/fx/DRIVE",
            "MIN": 15, "MAX": 70,
            "SPEED": 96, "WAVEFORM": 2,
        }},
    )

def test_assign_lfo_flat_slot():
    dev = _make_dev()
    dev.assign_lfo(5, "VOLUME", flat=True)
    args = dev._protocol.send_command.call_args
    assert "../../fxc/5/VOLUME" == args[1]["value"]["lfo1"]["LNK"]

@pytest.mark.parametrize("bad_speed", [-1, 186])
def test_assign_lfo_rejects_bad_speed(bad_speed):
    dev = _make_dev()
    with pytest.raises(ValueError, match="speed"):
        dev.assign_lfo(1, "DRIVE", speed=bad_speed)

@pytest.mark.parametrize("bad_waveform", [-1, 3])
def test_assign_lfo_rejects_bad_waveform(bad_waveform):
    dev = _make_dev()
    with pytest.raises(ValueError, match="waveform"):
        dev.assign_lfo(1, "DRIVE", waveform=bad_waveform)

# ------------------------------------------------------------------ clear_ctrl

def test_clear_ctrl_treadle():
    dev = _make_dev()
    dev.clear_ctrl("treadle")
    dev._protocol.send_command.assert_called_once_with(
        "sp", path="preset/ctrls/treadle/LNK", value=""
    )

def test_clear_ctrl_lfo():
    dev = _make_dev()
    dev.clear_ctrl("lfo1")
    dev._protocol.send_command.assert_called_once_with(
        "sp", path="preset/ctrls/lfo1/LNK", value=""
    )

def test_clear_ctrl_rejects_unknown():
    dev = _make_dev()
    with pytest.raises(ValueError):
        dev.clear_ctrl("ctrlD")

def test_clear_stomp_delegates_to_clear_ctrl():
    dev = _make_dev()
    dev.clear_stomp("ctrlA")
    dev._protocol.send_command.assert_called_once_with(
        "sp", path="preset/ctrls/ctrlA/LNK", value=""
    )

# ================================================================== CLI

runner = CliRunner()

# ------------------------------------------------------------------ stomp VSW

def test_cli_stomp_assign_vsw():
    mock_cm, instance = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, ["stomp", "assign", "VSW", "7"])
    assert result.exit_code == 0, result.output
    instance.assign_stomp.assert_called_once_with("ctrlVSw", 7)

def test_cli_stomp_clear_vsw():
    mock_cm, instance = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, ["stomp", "clear", "VSW"])
    assert result.exit_code == 0, result.output
    instance.clear_stomp.assert_called_once_with("ctrlVSw")

# ------------------------------------------------------------------ ctrl assign treadle

def test_cli_ctrl_assign_treadle():
    mock_cm, instance = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, [
            "ctrl", "assign", "treadle", "5", "VOLUME",
            "--min", "50", "--max", "81", "--flat",
        ])
    assert result.exit_code == 0, result.output
    instance.assign_expression.assert_called_once_with(
        "treadle", 5, "VOLUME", 50, 81, flat=True
    )

def test_cli_ctrl_assign_alt():
    mock_cm, instance = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, [
            "ctrl", "assign", "alt", "7", "PEDAL",
            "--min", "3", "--max", "93",
        ])
    assert result.exit_code == 0, result.output
    instance.assign_expression.assert_called_once_with(
        "altTreadle", 7, "PEDAL", 3, 93, flat=False
    )

# ------------------------------------------------------------------ ctrl assign lfo

def test_cli_ctrl_assign_lfo():
    mock_cm, instance = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, [
            "ctrl", "assign", "lfo", "1", "DRIVE",
            "--min", "15", "--max", "70",
            "--speed", "96", "--waveform", "0",
        ])
    assert result.exit_code == 0, result.output
    instance.assign_lfo.assert_called_once_with(
        1, "DRIVE", 15, 70, 96, 0, flat=False
    )

def test_cli_ctrl_assign_lfo_waveform_range():
    mock_cm, _ = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, [
            "ctrl", "assign", "lfo", "1", "DRIVE", "--waveform", "3"
        ])
    assert result.exit_code != 0

def test_cli_ctrl_assign_lfo_speed_range():
    mock_cm, _ = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, [
            "ctrl", "assign", "lfo", "1", "DRIVE", "--speed", "186"
        ])
    assert result.exit_code != 0

# ------------------------------------------------------------------ ctrl clear

def test_cli_ctrl_clear_treadle():
    mock_cm, instance = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, ["ctrl", "clear", "treadle"])
    assert result.exit_code == 0, result.output
    instance.clear_ctrl.assert_called_once_with("treadle")

def test_cli_ctrl_clear_lfo():
    mock_cm, instance = _make_mock_cm()
    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, ["ctrl", "clear", "lfo"])
    assert result.exit_code == 0, result.output
    instance.clear_ctrl.assert_called_once_with("lfo1")
