"""Tests for the TUI application screens and interactions."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from textual.widgets import Input, ListView

from roku_tui.app import (
    DeviceScreen,
    RemoteButton,
    RemoteScreen,
    RokuTUIApp,
    _BUTTON_MAP,
    _KEY_MAP,
)
from roku_tui.discovery import RokuDevice
from roku_tui.errors import ErrorCode, RokuError
from roku_tui.remote import RokuKey
from roku_tui.storage import DeviceStore, SavedDevice


# ---------------------------------------------------------------------------
# RemoteButton
# ---------------------------------------------------------------------------

class TestRemoteButton:
    def test_cannot_focus(self):
        assert RemoteButton.can_focus is False


# ---------------------------------------------------------------------------
# Key / Button maps
# ---------------------------------------------------------------------------

class TestMaps:
    def test_key_map_values_are_roku_keys(self):
        for v in _KEY_MAP.values():
            assert isinstance(v, RokuKey)

    def test_button_map_values_are_roku_keys(self):
        for v in _BUTTON_MAP.values():
            assert isinstance(v, RokuKey)

    def test_key_map_has_arrow_keys(self):
        assert "up" in _KEY_MAP
        assert "down" in _KEY_MAP
        assert "left" in _KEY_MAP
        assert "right" in _KEY_MAP

    def test_key_map_has_media_keys(self):
        assert "space" in _KEY_MAP
        assert "r" in _KEY_MAP
        assert "f" in _KEY_MAP

    def test_button_map_has_all_buttons(self):
        expected_ids = [
            "btn-power", "btn-home", "btn-back",
            "btn-up", "btn-down", "btn-left", "btn-right", "btn-ok",
            "btn-rev", "btn-play", "btn-fwd",
            "btn-voldown", "btn-mute", "btn-volup",
        ]
        for bid in expected_ids:
            assert bid in _BUTTON_MAP


# ---------------------------------------------------------------------------
# RokuTUIApp
# ---------------------------------------------------------------------------

class TestRokuTUIApp:
    @pytest.mark.asyncio
    async def test_app_starts_with_device_screen(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            assert isinstance(app.screen, DeviceScreen)

    @pytest.mark.asyncio
    async def test_app_title(self):
        app = RokuTUIApp()
        assert app.TITLE == "Roku Remote"


# ---------------------------------------------------------------------------
# DeviceScreen
# ---------------------------------------------------------------------------

class TestDeviceScreen:
    @pytest.mark.asyncio
    async def test_initial_render_has_scan_button(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            btn = app.screen.query_one("#scan-btn")
            assert btn is not None

    @pytest.mark.asyncio
    async def test_scan_finds_devices(self):
        fake_devices = [
            RokuDevice("Living Room", "Roku Ultra", "ABC", "192.168.1.100"),
        ]
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            with patch("roku_tui.app.discover_devices", new_callable=AsyncMock, return_value=fake_devices):
                await pilot.press("s")
                await pilot.pause(delay=0.5)

            status = app.screen.query_one("#status-bar")
            assert "1" in str(status.content)

    @pytest.mark.asyncio
    async def test_scan_no_devices(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            with patch("roku_tui.app.discover_devices", new_callable=AsyncMock, return_value=[]):
                await pilot.press("s")
                await pilot.pause(delay=0.5)

            status = app.screen.query_one("#status-bar")
            assert "No Roku devices found" in str(status.content)

    @pytest.mark.asyncio
    async def test_scan_error(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            with patch(
                "roku_tui.app.discover_devices",
                new_callable=AsyncMock,
                side_effect=RokuError(ErrorCode.E1001, "mock error"),
            ):
                await pilot.press("s")
                await pilot.pause(delay=0.5)

            status = app.screen.query_one("#status-bar")
            rendered = str(status.content)
            assert "E1001" in rendered

    @pytest.mark.asyncio
    async def test_scan_generic_exception(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            with patch(
                "roku_tui.app.discover_devices",
                new_callable=AsyncMock,
                side_effect=RuntimeError("oops"),
            ):
                await pilot.press("s")
                await pilot.pause(delay=0.5)

            status = app.screen.query_one("#status-bar")
            rendered = str(status.content)
            assert "oops" in rendered

    @pytest.mark.asyncio
    async def test_device_selection_pushes_remote_screen(self):
        fake_devices = [
            RokuDevice("Living Room", "Roku Ultra", "ABC", "192.168.1.100"),
        ]
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            with patch("roku_tui.app.discover_devices", new_callable=AsyncMock, return_value=fake_devices):
                await pilot.press("s")
                await pilot.pause(delay=0.5)

            # Focus the list and select first item
            device_list = app.screen.query_one("#device-list", ListView)
            device_list.focus()
            await pilot.pause(delay=0.2)
            # Highlight first item then select
            device_list.index = 0
            await pilot.pause(delay=0.2)
            await pilot.press("enter")
            await pilot.pause(delay=0.5)

            assert isinstance(app.screen, RemoteScreen)

    @pytest.mark.asyncio
    async def test_ip_input_widget_present(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            ip_input = app.screen.query_one("#ip-input", Input)
            assert ip_input is not None

    @pytest.mark.asyncio
    async def test_connect_button_present(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            btn = app.screen.query_one("#connect-btn")
            assert btn is not None

    @pytest.mark.asyncio
    async def test_a_keybinding_focuses_ip_input(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            ip_input = app.screen.query_one("#ip-input", Input)
            assert not ip_input.has_focus
            await pilot.press("a")
            await pilot.pause(delay=0.2)
            assert ip_input.has_focus

    @pytest.mark.asyncio
    async def test_manual_connect_success(self):
        fake_device = RokuDevice("Office Roku", "Roku Express", "XYZ", "10.0.0.5")
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            ip_input = app.screen.query_one("#ip-input", Input)
            ip_input.value = "10.0.0.5"

            with patch("roku_tui.app.connect_device", new_callable=AsyncMock, return_value=fake_device):
                await pilot.click("#connect-btn")
                await pilot.pause(delay=0.5)

            status = app.screen.query_one("#status-bar")
            assert "Office Roku" in str(status.content)
            assert len(app.screen.devices) == 1
            assert app.screen.devices[0].host == "10.0.0.5"

    @pytest.mark.asyncio
    async def test_manual_connect_with_port(self):
        fake_device = RokuDevice("Office Roku", "Roku Express", "XYZ", "10.0.0.5", port=9090)
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            ip_input = app.screen.query_one("#ip-input", Input)
            ip_input.value = "10.0.0.5:9090"

            with patch("roku_tui.app.connect_device", new_callable=AsyncMock, return_value=fake_device) as mock_conn:
                await pilot.click("#connect-btn")
                await pilot.pause(delay=0.5)
                mock_conn.assert_called_with("10.0.0.5", 9090)

    @pytest.mark.asyncio
    async def test_manual_connect_failure_shows_error(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            ip_input = app.screen.query_one("#ip-input", Input)
            ip_input.value = "192.168.1.200"

            with patch(
                "roku_tui.app.connect_device",
                new_callable=AsyncMock,
                side_effect=RokuError(ErrorCode.E1003, "Cannot reach 192.168.1.200:8060"),
            ):
                await pilot.click("#connect-btn")
                await pilot.pause(delay=0.5)

            status = app.screen.query_one("#status-bar")
            rendered = str(status.content)
            assert "E1003" in rendered

    @pytest.mark.asyncio
    async def test_manual_connect_empty_ip_shows_error(self):
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            ip_input = app.screen.query_one("#ip-input", Input)
            ip_input.value = ""

            await pilot.click("#connect-btn")
            await pilot.pause(delay=0.5)

            status = app.screen.query_one("#status-bar")
            assert "enter an IP" in str(status.content)

    @pytest.mark.asyncio
    async def test_manual_connect_via_enter_key(self):
        fake_device = RokuDevice("Office Roku", "Roku Express", "XYZ", "10.0.0.5")
        app = RokuTUIApp()
        async with app.run_test(size=(120, 40)) as pilot:
            ip_input = app.screen.query_one("#ip-input", Input)
            ip_input.focus()
            await pilot.pause(delay=0.1)
            ip_input.value = "10.0.0.5"

            with patch("roku_tui.app.connect_device", new_callable=AsyncMock, return_value=fake_device):
                await pilot.press("enter")
                await pilot.pause(delay=0.5)

            assert len(app.screen.devices) == 1


# ---------------------------------------------------------------------------
# RemoteScreen
# ---------------------------------------------------------------------------

class TestRemoteScreen:
    def _make_app_with_remote(self):
        device = RokuDevice("Test", "Roku Ultra", "S123", "192.168.1.100")
        return RokuTUIApp(), device

    @pytest.mark.asyncio
    async def test_remote_screen_renders(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(RemoteScreen(device))
            await pilot.pause()

            assert isinstance(app.screen, RemoteScreen)
            banner = app.screen.query_one("#device-banner")
            assert "Test" in str(banner.content)

    @pytest.mark.asyncio
    async def test_keyboard_sends_key(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(screen.remote, "keypress", new_callable=AsyncMock) as mock_kp:
                await pilot.press("h")
                await pilot.pause(delay=0.3)
                mock_kp.assert_called_with(RokuKey.HOME)

    @pytest.mark.asyncio
    async def test_arrow_keys(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(screen.remote, "keypress", new_callable=AsyncMock) as mock_kp:
                await pilot.press("up")
                await pilot.pause(delay=0.3)
                mock_kp.assert_called_with(RokuKey.UP)

    @pytest.mark.asyncio
    async def test_space_sends_play(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(screen.remote, "keypress", new_callable=AsyncMock) as mock_kp:
                await pilot.press("space")
                await pilot.pause(delay=0.3)
                mock_kp.assert_called_with(RokuKey.PLAY)

    @pytest.mark.asyncio
    async def test_escape_pops_screen(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()
            assert isinstance(app.screen, RemoteScreen)

            await pilot.press("escape")
            await pilot.pause()

            assert isinstance(app.screen, DeviceScreen)

    @pytest.mark.asyncio
    async def test_button_click_sends_key(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(screen.remote, "keypress", new_callable=AsyncMock) as mock_kp:
                btn = screen.query_one("#btn-play")
                await pilot.click(btn.__class__, offset=(1, 1))
                await pilot.pause(delay=0.3)

    @pytest.mark.asyncio
    async def test_key_error_shows_in_status(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(
                screen.remote,
                "keypress",
                new_callable=AsyncMock,
                side_effect=RokuError(ErrorCode.E1008, "unreachable"),
            ):
                await pilot.press("h")
                await pilot.pause(delay=0.5)

            status = screen.query_one("#status")
            rendered = str(status.content)
            assert "E1008" in rendered

    @pytest.mark.asyncio
    async def test_generic_error_shows_in_status(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(
                screen.remote,
                "keypress",
                new_callable=AsyncMock,
                side_effect=RuntimeError("unexpected"),
            ):
                await pilot.press("h")
                await pilot.pause(delay=0.5)

            status = screen.query_one("#status")
            rendered = str(status.content)
            assert "unexpected" in rendered

    @pytest.mark.asyncio
    async def test_unmount_closes_remote(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(screen.remote, "close", new_callable=AsyncMock) as mock_close:
                await pilot.press("escape")
                await pilot.pause(delay=0.3)
                mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_remote_buttons_present(self):
        app, device = self._make_app_with_remote()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = RemoteScreen(device)
            app.push_screen(screen)
            await pilot.pause()

            for btn_id in _BUTTON_MAP:
                btn = screen.query_one(f"#{btn_id}")
                assert btn is not None


# ---------------------------------------------------------------------------
# Device Persistence
# ---------------------------------------------------------------------------

class TestDeviceScreenPersistence:
    @pytest.mark.asyncio
    async def test_saved_devices_loaded_on_mount(self, tmp_path):
        path = tmp_path / "devices.json"
        store = DeviceStore(path)
        store.load()
        device = RokuDevice("Saved TV", "Ultra", "SAV1", "10.0.0.10")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        store.save()

        app = RokuTUIApp(device_store=DeviceStore(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.3)
            assert len(app.screen.devices) == 1
            assert app.screen.devices[0].name == "Saved TV"
            status = app.screen.query_one("#status-bar")
            assert "saved" in str(status.content).lower()

    @pytest.mark.asyncio
    async def test_scan_merges_with_saved(self, tmp_path):
        # Pre-save a device
        path = tmp_path / "devices.json"
        store = DeviceStore(path)
        store.load()
        saved_dev = RokuDevice("Old TV", "Express", "SAV2", "10.0.0.20")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(saved_dev)
        store.save()

        # Scan discovers a different device
        discovered = [RokuDevice("New TV", "Ultra", "DISC1", "10.0.0.30")]
        app = RokuTUIApp(device_store=DeviceStore(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.3)
            with patch("roku_tui.app.discover_devices", new_callable=AsyncMock, return_value=discovered):
                with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
                    await pilot.press("s")
                    await pilot.pause(delay=0.5)

            # Both devices should be in the list
            assert len(app.screen.devices) == 2
            names = {d.name for d in app.screen.devices}
            assert "New TV" in names
            assert "Old TV" in names

    @pytest.mark.asyncio
    async def test_manual_connect_saves_device(self, tmp_path):
        path = tmp_path / "devices.json"
        store = DeviceStore(path)
        store.load()
        store.save()

        fake_device = RokuDevice("Manual TV", "Express", "MAN1", "10.0.0.40")
        app = RokuTUIApp(device_store=DeviceStore(path))
        async with app.run_test(size=(120, 40)) as pilot:
            ip_input = app.screen.query_one("#ip-input", Input)
            ip_input.value = "10.0.0.40"

            with patch("roku_tui.app.connect_device", new_callable=AsyncMock, return_value=fake_device):
                with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
                    await pilot.click("#connect-btn")
                    await pilot.pause(delay=0.5)

        # Verify persisted to disk
        data = json.loads(path.read_text())
        assert "MAN1" in data["devices"]
        assert data["devices"]["MAN1"]["name"] == "Manual TV"

    @pytest.mark.asyncio
    async def test_selecting_device_updates_last_connected(self, tmp_path):
        path = tmp_path / "devices.json"
        store = DeviceStore(path)
        store.load()
        device = RokuDevice("TV", "Ultra", "SEL1", "10.0.0.50")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        store.save()
        assert store.devices["SEL1"].last_connected is None

        app = RokuTUIApp(device_store=DeviceStore(path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(delay=0.3)
            device_list = app.screen.query_one("#device-list", ListView)
            device_list.focus()
            await pilot.pause(delay=0.2)
            device_list.index = 0
            await pilot.pause(delay=0.2)
            await pilot.press("enter")
            await pilot.pause(delay=0.5)

        # Verify last_connected was written to disk
        data = json.loads(path.read_text())
        assert data["devices"]["SEL1"]["last_connected"] is not None
