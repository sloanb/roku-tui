"""Main TUI application for Roku device control."""

from __future__ import annotations

import logging

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static
from textual import events, work

from .discovery import RokuDevice, connect_device, discover_devices
from .errors import RokuError
from .remote import RokuKey, RokuRemote
from .storage import DeviceStore, _device_key

log = logging.getLogger(__name__)

# Maps keyboard keys to Roku remote keys
_KEY_MAP: dict[str, RokuKey] = {
    "up": RokuKey.UP,
    "down": RokuKey.DOWN,
    "left": RokuKey.LEFT,
    "right": RokuKey.RIGHT,
    "enter": RokuKey.SELECT,
    "space": RokuKey.PLAY,
    "h": RokuKey.HOME,
    "b": RokuKey.BACK,
    "i": RokuKey.INFO,
    "r": RokuKey.REV,
    "f": RokuKey.FWD,
    "equal_sign": RokuKey.VOLUME_UP,
    "minus": RokuKey.VOLUME_DOWN,
    "m": RokuKey.VOLUME_MUTE,
    "p": RokuKey.POWER,
}

# Maps button IDs to Roku remote keys
_BUTTON_MAP: dict[str, RokuKey] = {
    "btn-power": RokuKey.POWER,
    "btn-home": RokuKey.HOME,
    "btn-back": RokuKey.BACK,
    "btn-up": RokuKey.UP,
    "btn-down": RokuKey.DOWN,
    "btn-left": RokuKey.LEFT,
    "btn-right": RokuKey.RIGHT,
    "btn-ok": RokuKey.SELECT,
    "btn-rev": RokuKey.REV,
    "btn-play": RokuKey.PLAY,
    "btn-fwd": RokuKey.FWD,
    "btn-voldown": RokuKey.VOLUME_DOWN,
    "btn-mute": RokuKey.VOLUME_MUTE,
    "btn-volup": RokuKey.VOLUME_UP,
}


class RemoteButton(Button):
    """A button that does not capture keyboard focus (click-only)."""

    can_focus = False


class DeviceScreen(Screen):
    """Screen for scanning and selecting Roku devices."""

    DEFAULT_CSS = """
    DeviceScreen {
        layout: vertical;
    }

    #scan-header {
        text-align: center;
        padding: 1 2;
        text-style: bold;
        color: $text;
        background: $primary;
        width: 100%;
    }

    #scan-container {
        height: auto;
        padding: 1 2;
        align: center middle;
    }

    #scan-btn {
        margin: 1 2;
    }

    #ip-input {
        width: 30;
        margin: 1 0;
    }

    #connect-btn {
        margin: 1 1;
    }

    #device-list-container {
        height: 1fr;
        padding: 0 2;
    }

    #status-bar {
        height: 3;
        padding: 1 2;
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("s", "scan", "Scan"),
        Binding("a", "focus_ip", "Add IP"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, device_store: DeviceStore | None = None) -> None:
        super().__init__()
        self.devices: list[RokuDevice] = []
        self.device_store = device_store or DeviceStore()
        self._saved_serials: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Roku Device Scanner", id="scan-header")
        with Horizontal(id="scan-container"):
            yield Button("Scan Network", id="scan-btn", variant="primary")
            yield Input(placeholder="IP address or IP:port", id="ip-input")
            yield Button("Connect", id="connect-btn", variant="success")
        with Container(id="device-list-container"):
            yield ListView(id="device-list")
        yield Static("Press [bold]s[/bold] to scan or [bold]a[/bold] to enter an IP", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        try:
            saved = self.device_store.load()
        except Exception:
            log.exception("Failed to load saved devices")
            return
        if saved:
            device_list = self.query_one("#device-list", ListView)
            for key, sd in saved.items():
                rd = sd.to_roku_device()
                self.devices.append(rd)
                self._saved_serials.add(key)
                device_list.append(
                    ListItem(Label(
                        f"  {rd.name}  --  {rd.model}  ({rd.host}) [dim](saved)[/dim]"
                    ))
                )
            status = self.query_one("#status-bar", Static)
            status.update(
                f"Loaded [bold]{len(saved)}[/] saved device(s). "
                "Press [bold]s[/bold] to scan or select a device."
            )

    def action_scan(self) -> None:
        self._run_scan()

    def action_focus_ip(self) -> None:
        self.query_one("#ip-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "scan-btn":
            self._run_scan()
        elif event.button.id == "connect-btn":
            self._run_connect()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ip-input":
            self._run_connect()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self.devices):
            device = self.devices[idx]
            try:
                key = _device_key(device)
                self.device_store.mark_connected(key)
                self.device_store.save()
            except Exception:
                log.exception("Failed to update last_connected")
            self.app.push_screen(RemoteScreen(device))

    def _repopulate_saved(self) -> None:
        """Re-add saved devices to the list (used after scan clears it)."""
        device_list = self.query_one("#device-list", ListView)
        try:
            saved = self.device_store.load()
        except Exception:
            log.exception("Failed to reload saved devices")
            return
        discovered_keys = {_device_key(d) for d in self.devices}
        for key, sd in saved.items():
            if key not in discovered_keys:
                rd = sd.to_roku_device()
                self.devices.append(rd)
                self._saved_serials.add(key)
                device_list.append(
                    ListItem(Label(
                        f"  {rd.name}  --  {rd.model}  ({rd.host}) [dim](saved)[/dim]"
                    ))
                )

    @work(exclusive=True)
    async def _run_scan(self) -> None:
        status = self.query_one("#status-bar", Static)
        device_list = self.query_one("#device-list", ListView)
        status.update("Scanning network...")
        device_list.clear()
        self.devices.clear()
        self._saved_serials.clear()

        try:
            self.devices = await discover_devices(timeout=5.0)
        except RokuError as exc:
            status.update(f"[bold red]Error:[/] {exc}")
            self._repopulate_saved()
            return
        except Exception as exc:
            status.update(f"[bold red]Scan failed:[/] {exc}")
            self._repopulate_saved()
            return

        # Merge discovered devices into store
        try:
            for device in self.devices:
                self.device_store.merge_device(device)
            self.device_store.save()
        except Exception:
            log.exception("Failed to save discovered devices")

        if not self.devices:
            status.update("No Roku devices found. Press [bold]s[/bold] to retry.")
            self._repopulate_saved()
            return

        for device in self.devices:
            device_list.append(
                ListItem(Label(f"  {device.name}  --  {device.model}  ({device.host})"))
            )

        # Re-add saved devices that weren't discovered
        self._repopulate_saved()

        status.update(
            f"Found [bold]{len(self.devices)}[/] device(s). "
            "Select one to begin controlling it."
        )

    @work(exclusive=True, group="connect")
    async def _run_connect(self) -> None:
        status = self.query_one("#status-bar", Static)
        ip_input = self.query_one("#ip-input", Input)
        raw = ip_input.value.strip()

        if not raw:
            status.update("[bold red]Error:[/] Please enter an IP address.")
            return

        # Parse host:port
        if ":" in raw:
            parts = raw.rsplit(":", 1)
            host = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                status.update(f"[bold red]Error:[/] Invalid port in '{raw}'.")
                return
        else:
            host = raw
            port = 8060

        status.update(f"Connecting to {host}:{port}...")

        try:
            device = await connect_device(host, port)
        except RokuError as exc:
            status.update(f"[bold red]Error:[/] {exc}")
            return
        except Exception as exc:
            status.update(f"[bold red]Connect failed:[/] {exc}")
            return

        # Merge into store
        try:
            self.device_store.merge_device(device)
            self.device_store.save()
        except Exception:
            log.exception("Failed to save connected device")

        self.devices.append(device)
        device_list = self.query_one("#device-list", ListView)
        device_list.append(
            ListItem(Label(f"  {device.name}  --  {device.model}  ({device.host})"))
        )
        ip_input.value = ""
        status.update(
            f"Connected to [bold]{device.name}[/] ({device.host}). "
            f"[bold]{len(self.devices)}[/] device(s) in list."
        )


class RemoteScreen(Screen):
    """Screen for controlling a connected Roku device."""

    DEFAULT_CSS = """
    RemoteScreen {
        layout: vertical;
        align: center top;
    }

    #device-banner {
        text-align: center;
        padding: 1;
        background: $primary;
        color: $text;
        text-style: bold;
        width: 100%;
    }

    #remote-panel {
        width: 60;
        padding: 1 2;
        border: thick $primary;
        background: $surface-darken-1;
        height: auto;
    }

    .section-label {
        text-align: center;
        color: $text-muted;
        padding: 1 0 0 0;
        text-style: bold;
    }

    .btn-row {
        height: auto;
        align: center middle;
        margin: 0 0 1 0;
    }

    .nav-row {
        height: auto;
        align: center middle;
    }

    RemoteButton {
        min-width: 14;
        height: 3;
        margin: 0 1;
    }

    .nav-btn {
        min-width: 10;
        margin: 0 0;
    }

    .ok-btn {
        min-width: 10;
        background: $success;
        color: $text;
    }

    .power-btn {
        background: $error;
        color: $text;
    }

    .media-btn {
        background: $success-darken-1;
    }

    .vol-btn {
        background: $warning-darken-1;
    }

    .nav-spacer {
        width: 10;
        height: 3;
    }

    #status {
        text-align: center;
        padding: 1;
        color: $text-muted;
        height: 3;
    }

    #help-text {
        text-align: center;
        color: $text-muted;
        padding: 1;
        border-top: solid $primary-darken-2;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Devices", priority=True),
    ]

    def __init__(self, device: RokuDevice) -> None:
        super().__init__()
        self.device = device
        self.remote = RokuRemote(device)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"Connected: {self.device.name} ({self.device.host})", id="device-banner"
        )

        with Container(id="remote-panel"):
            # Power / Home / Back
            yield Static("-- Power & Navigation --", classes="section-label")
            with Horizontal(classes="btn-row"):
                yield RemoteButton("Power", id="btn-power", classes="power-btn")
                yield RemoteButton("Home", id="btn-home")
                yield RemoteButton("Back", id="btn-back")

            # D-Pad
            yield Static("-- D-Pad --", classes="section-label")
            with Horizontal(classes="nav-row"):
                yield Static("", classes="nav-spacer")
                yield RemoteButton("Up", id="btn-up", classes="nav-btn")
                yield Static("", classes="nav-spacer")
            with Horizontal(classes="nav-row"):
                yield RemoteButton("Left", id="btn-left", classes="nav-btn")
                yield RemoteButton("  OK  ", id="btn-ok", classes="nav-btn ok-btn")
                yield RemoteButton("Right", id="btn-right", classes="nav-btn")
            with Horizontal(classes="nav-row"):
                yield Static("", classes="nav-spacer")
                yield RemoteButton("Down", id="btn-down", classes="nav-btn")
                yield Static("", classes="nav-spacer")

            # Media controls
            yield Static("-- Media --", classes="section-label")
            with Horizontal(classes="btn-row"):
                yield RemoteButton("Rev", id="btn-rev", classes="media-btn")
                yield RemoteButton("Play/Pause", id="btn-play", classes="media-btn")
                yield RemoteButton("Fwd", id="btn-fwd", classes="media-btn")

            # Volume
            yield Static("-- Volume --", classes="section-label")
            with Horizontal(classes="btn-row"):
                yield RemoteButton("Vol -", id="btn-voldown", classes="vol-btn")
                yield RemoteButton("Mute", id="btn-mute", classes="vol-btn")
                yield RemoteButton("Vol +", id="btn-volup", classes="vol-btn")

        yield Static("Ready", id="status")
        yield Static(
            "Keys: Arrows=Navigate  Enter=OK  Space=Play/Pause  "
            "h=Home  b=Back  p=Power\n"
            "r=Rewind  f=Forward  =/Vol+  -/Vol-  m=Mute  i=Info  "
            "Esc=Back to devices",
            id="help-text",
        )
        yield Footer()

    def on_key(self, event: events.Key) -> None:
        roku_key = _KEY_MAP.get(event.key)
        if roku_key:
            self._send_key(roku_key)
            event.prevent_default()
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id in _BUTTON_MAP:
            self._send_key(_BUTTON_MAP[event.button.id])

    def action_go_back(self) -> None:
        self.app.pop_screen()

    @work
    async def _send_key(self, key: RokuKey) -> None:
        status = self.query_one("#status", Static)
        try:
            await self.remote.keypress(key)
            status.update(f"Sent: {key.value}")
        except RokuError as exc:
            status.update(f"[bold red]Error:[/] {exc}")
        except Exception as exc:
            status.update(f"[bold red]Failed:[/] {exc}")

    async def on_unmount(self) -> None:
        await self.remote.close()


class RokuTUIApp(App):
    """Roku TUI - Control your Roku from the terminal."""

    TITLE = "Roku Remote"
    SUB_TITLE = "Control your Roku from the terminal"

    DEFAULT_CSS = """
    Screen {
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, device_store: DeviceStore | None = None) -> None:
        super().__init__()
        self.device_store = device_store or DeviceStore()

    def on_mount(self) -> None:
        self.push_screen(DeviceScreen(device_store=self.device_store))
