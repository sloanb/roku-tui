"""Persistent storage for saved Roku devices across sessions."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .discovery import RokuDevice

log = logging.getLogger(__name__)

_APP_DIR = "roku-tui"
_DEVICES_FILE = "devices.json"
_SCHEMA_VERSION = 1


def get_config_dir() -> Path:
    """Return the configuration directory for roku-tui.

    Uses $XDG_CONFIG_HOME/roku-tui, defaulting to ~/.config/roku-tui.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / _APP_DIR


def get_local_subnet(device_ip: str) -> tuple[str | None, str | None]:
    """Determine the local source IP and /24 subnet for reaching *device_ip*.

    Uses a non-connecting UDP socket so no traffic is sent.
    Returns ``(source_ip, subnet)`` or ``(None, None)`` on failure.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((device_ip, 80))
            source_ip = sock.getsockname()[0]
        finally:
            sock.close()
        network = ipaddress.ip_network(f"{source_ip}/24", strict=False)
        return source_ip, str(network)
    except OSError:
        return None, None


def _device_key(device: RokuDevice) -> str:
    """Return the storage key for a device: serial, or host:port if unknown."""
    if device.serial and device.serial != "Unknown":
        return device.serial
    return f"{device.host}:{device.port}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SavedDevice:
    """A Roku device with persistence metadata."""

    name: str
    model: str
    serial: str
    host: str
    port: int = 8060
    subnet: str | None = None
    source_ip: str | None = None
    last_connected: str | None = None
    first_seen: str = field(default_factory=_now_iso)
    last_seen: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "serial": self.serial,
            "host": self.host,
            "port": self.port,
            "subnet": self.subnet,
            "source_ip": self.source_ip,
            "last_connected": self.last_connected,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SavedDevice:
        now = _now_iso()
        return cls(
            name=data.get("name", "Unknown"),
            model=data.get("model", "Unknown"),
            serial=data.get("serial", "Unknown"),
            host=data.get("host", ""),
            port=data.get("port", 8060),
            subnet=data.get("subnet"),
            source_ip=data.get("source_ip"),
            last_connected=data.get("last_connected"),
            first_seen=data.get("first_seen", now),
            last_seen=data.get("last_seen", now),
        )

    def to_roku_device(self) -> RokuDevice:
        return RokuDevice(
            name=self.name,
            model=self.model,
            serial=self.serial,
            host=self.host,
            port=self.port,
        )

    @classmethod
    def from_roku_device(cls, device: RokuDevice) -> SavedDevice:
        source_ip, subnet = get_local_subnet(device.host)
        now = _now_iso()
        return cls(
            name=device.name,
            model=device.model,
            serial=device.serial,
            host=device.host,
            port=device.port,
            subnet=subnet,
            source_ip=source_ip,
            first_seen=now,
            last_seen=now,
        )


class DeviceStore:
    """Manages persistent storage of saved Roku devices in a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        if path is not None:
            self._path = path
        else:
            self._path = get_config_dir() / _DEVICES_FILE
        self._devices: dict[str, SavedDevice] = {}

    @property
    def devices(self) -> dict[str, SavedDevice]:
        """Return a copy of the saved devices dict."""
        return dict(self._devices)

    def load(self) -> dict[str, SavedDevice]:
        """Load devices from the JSON file.

        Returns the loaded devices dict. Corrupt files are backed up.
        """
        if not self._path.exists():
            self._devices = {}
            return self.devices

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Corrupt devices file, backing up: %s", exc)
            self._backup()
            self._devices = {}
            return self.devices

        if not isinstance(data, dict) or data.get("version") != _SCHEMA_VERSION:
            log.warning("Unknown schema version, backing up devices file")
            self._backup()
            self._devices = {}
            return self.devices

        devices: dict[str, SavedDevice] = {}
        raw_devices = data.get("devices", {})
        if isinstance(raw_devices, dict):
            for key, entry in raw_devices.items():
                if not isinstance(entry, dict):
                    log.warning("Skipping invalid device entry: %s", key)
                    continue
                try:
                    devices[key] = SavedDevice.from_dict(entry)
                except Exception as exc:
                    log.warning("Skipping corrupt device entry %s: %s", key, exc)

        self._devices = devices
        return self.devices

    def save(self) -> None:
        """Atomically write devices to the JSON file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _SCHEMA_VERSION,
            "devices": {k: v.to_dict() for k, v in self._devices.items()},
        }
        tmp_path = self._path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8"
            )
            tmp_path.replace(self._path)
        except OSError as exc:
            log.error("Failed to save devices: %s", exc)

    def merge_device(self, device: RokuDevice) -> str:
        """Upsert a device by serial (or host:port if serial is Unknown).

        Updates host/port/name/model/last_seen/subnet; preserves first_seen.
        Returns the storage key used.
        """
        key = _device_key(device)
        existing = self._devices.get(key)
        if existing is not None:
            existing.name = device.name
            existing.model = device.model
            existing.host = device.host
            existing.port = device.port
            existing.last_seen = _now_iso()
            source_ip, subnet = get_local_subnet(device.host)
            if source_ip:
                existing.source_ip = source_ip
                existing.subnet = subnet
        else:
            self._devices[key] = SavedDevice.from_roku_device(device)
        return key

    def mark_connected(self, key: str) -> None:
        """Set last_connected to now for the given device key."""
        device = self._devices.get(key)
        if device is not None:
            device.last_connected = _now_iso()

    def _backup(self) -> None:
        """Backup the current file to .json.bak."""
        bak = self._path.with_suffix(".json.bak")
        try:
            self._path.replace(bak)
        except OSError as exc:
            log.error("Failed to backup devices file: %s", exc)
