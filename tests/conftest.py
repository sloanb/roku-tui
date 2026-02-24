"""Shared fixtures for Roku TUI tests."""

import pytest

from roku_tui.discovery import RokuDevice


@pytest.fixture
def fake_device() -> RokuDevice:
    return RokuDevice(
        name="Living Room Roku",
        model="Roku Ultra",
        serial="ABC123XYZ",
        host="192.168.1.100",
        port=8060,
    )


@pytest.fixture
def fake_device_two() -> RokuDevice:
    return RokuDevice(
        name="Bedroom Roku",
        model="Roku Express",
        serial="DEF456ABC",
        host="192.168.1.101",
        port=8060,
    )
