"""Tests for master-vol device method and CLI command — no hardware required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest
from click.testing import CliRunner

from rp360xp.cli import cli
from rp360xp.device import Device


# ------------------------------------------------------------------ Device API

def test_get_master_vol_calls_rp():
    """get_master_vol() issues an rp on system/MASTERVOL and returns an int."""
    dev = Device.__new__(Device)
    dev._protocol = MagicMock()
    dev._protocol.send_command.return_value = 54

    result = dev.get_master_vol()

    dev._protocol.send_command.assert_called_once_with("rp", path="system/MASTERVOL")
    assert result == 54
    assert isinstance(result, int)


def test_set_master_vol_calls_sp():
    """set_master_vol() issues an sp on system/MASTERVOL with the given int."""
    dev = Device.__new__(Device)
    dev._protocol = MagicMock()

    dev.set_master_vol(75)

    dev._protocol.send_command.assert_called_once_with(
        "sp", path="system/MASTERVOL", value=75
    )


@pytest.mark.parametrize("bad", [-1, 100, 200])
def test_set_master_vol_rejects_out_of_range(bad):
    """set_master_vol() raises ValueError for values outside 0-99."""
    dev = Device.__new__(Device)
    dev._protocol = MagicMock()

    with pytest.raises(ValueError, match="0-99"):
        dev.set_master_vol(bad)

    dev._protocol.send_command.assert_not_called()


def test_set_master_vol_boundary_values():
    """set_master_vol() accepts 0 and 99 without raising."""
    dev = Device.__new__(Device)
    dev._protocol = MagicMock()

    dev.set_master_vol(0)
    dev.set_master_vol(99)

    assert dev._protocol.send_command.call_count == 2


# ------------------------------------------------------------------ CLI read

def _make_mock_device(vol=54):
    """Return a context-manager mock that exposes get/set_master_vol."""
    instance = MagicMock()
    instance.get_master_vol.return_value = vol
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=instance)
    cm.__exit__ = MagicMock(return_value=False)
    return cm, instance


def test_cli_master_vol_read():
    """master-vol without argument reads and displays the current value."""
    runner = CliRunner()
    mock_cm, instance = _make_mock_device(vol=54)

    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, ["master-vol"])

    assert result.exit_code == 0, result.output
    assert "54" in result.output
    instance.get_master_vol.assert_called_once()
    instance.set_master_vol.assert_not_called()


# ------------------------------------------------------------------ CLI write

def test_cli_master_vol_set():
    """master-vol VALUE writes the value and confirms in output."""
    runner = CliRunner()
    mock_cm, instance = _make_mock_device()

    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, ["master-vol", "70"])

    assert result.exit_code == 0, result.output
    assert "70" in result.output
    instance.set_master_vol.assert_called_once_with(70)
    instance.get_master_vol.assert_not_called()


def test_cli_master_vol_set_zero():
    """master-vol 0 is accepted (boundary value)."""
    runner = CliRunner()
    mock_cm, instance = _make_mock_device()

    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, ["master-vol", "0"])

    assert result.exit_code == 0, result.output
    instance.set_master_vol.assert_called_once_with(0)


def test_cli_master_vol_set_max():
    """master-vol 99 is accepted (boundary value)."""
    runner = CliRunner()
    mock_cm, instance = _make_mock_device()

    with patch("rp360xp.cli.Device", return_value=mock_cm):
        result = runner.invoke(cli, ["master-vol", "99"])

    assert result.exit_code == 0, result.output
    instance.set_master_vol.assert_called_once_with(99)


# ------------------------------------------------------------------ CLI range

@pytest.mark.parametrize("bad", ["100", "-1", "200"])
def test_cli_master_vol_rejects_out_of_range(bad):
    """master-vol with a value outside 0-99 is rejected by click before connecting."""
    runner = CliRunner()

    with patch("rp360xp.cli.Device") as MockDevice:
        result = runner.invoke(cli, ["master-vol", bad])

    assert result.exit_code != 0
    # click should reject the value before we ever instantiate Device
    MockDevice.assert_not_called()
