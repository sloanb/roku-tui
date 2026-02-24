"""Tests for the persistent device storage module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from roku_tui.discovery import RokuDevice
from roku_tui.storage import (
    DeviceStore,
    SavedDevice,
    _device_key,
    _now_iso,
    get_config_dir,
    get_local_subnet,
    is_cache_valid,
)


# ---------------------------------------------------------------------------
# is_cache_valid
# ---------------------------------------------------------------------------

class TestIsCacheValid:
    def test_none_returns_false(self):
        assert is_cache_valid(None) is False

    def test_missing_fetched_at_returns_false(self):
        assert is_cache_valid({"apps": []}) is False

    def test_empty_fetched_at_returns_false(self):
        assert is_cache_valid({"fetched_at": "", "apps": []}) is False

    def test_recent_cache_is_valid(self):
        cache = {"fetched_at": _now_iso(), "apps": []}
        assert is_cache_valid(cache) is True

    def test_old_cache_is_invalid(self):
        old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        cache = {"fetched_at": old_ts, "apps": []}
        assert is_cache_valid(cache) is False

    def test_malformed_timestamp_returns_false(self):
        cache = {"fetched_at": "not-a-date", "apps": []}
        assert is_cache_valid(cache) is False


# ---------------------------------------------------------------------------
# SavedDevice
# ---------------------------------------------------------------------------

class TestSavedDevice:
    def test_to_dict_round_trip(self):
        sd = SavedDevice(
            name="Living Room",
            model="Roku Ultra",
            serial="ABC123",
            host="192.168.1.100",
            port=8060,
            subnet="192.168.1.0/24",
            source_ip="192.168.1.50",
            last_connected="2026-01-01T00:00:00+00:00",
            first_seen="2026-01-01T00:00:00+00:00",
            last_seen="2026-01-01T00:00:00+00:00",
        )
        d = sd.to_dict()
        restored = SavedDevice.from_dict(d)
        assert restored.name == sd.name
        assert restored.model == sd.model
        assert restored.serial == sd.serial
        assert restored.host == sd.host
        assert restored.port == sd.port
        assert restored.subnet == sd.subnet
        assert restored.source_ip == sd.source_ip
        assert restored.last_connected == sd.last_connected
        assert restored.first_seen == sd.first_seen
        assert restored.last_seen == sd.last_seen

    def test_from_dict_missing_fields_uses_defaults(self):
        sd = SavedDevice.from_dict({"host": "10.0.0.1"})
        assert sd.name == "Unknown"
        assert sd.model == "Unknown"
        assert sd.serial == "Unknown"
        assert sd.host == "10.0.0.1"
        assert sd.port == 8060
        assert sd.subnet is None
        assert sd.source_ip is None
        assert sd.last_connected is None

    def test_from_dict_empty_dict(self):
        sd = SavedDevice.from_dict({})
        assert sd.host == ""
        assert sd.name == "Unknown"

    def test_to_roku_device(self):
        sd = SavedDevice(
            name="Test",
            model="Express",
            serial="XYZ",
            host="10.0.0.5",
            port=9090,
        )
        rd = sd.to_roku_device()
        assert isinstance(rd, RokuDevice)
        assert rd.name == "Test"
        assert rd.model == "Express"
        assert rd.serial == "XYZ"
        assert rd.host == "10.0.0.5"
        assert rd.port == 9090

    def test_from_roku_device(self):
        rd = RokuDevice(
            name="Living Room",
            model="Ultra",
            serial="ABC",
            host="192.168.1.100",
        )
        with patch("roku_tui.storage.get_local_subnet", return_value=("192.168.1.50", "192.168.1.0/24")):
            sd = SavedDevice.from_roku_device(rd)
        assert sd.name == "Living Room"
        assert sd.model == "Ultra"
        assert sd.serial == "ABC"
        assert sd.host == "192.168.1.100"
        assert sd.port == 8060
        assert sd.source_ip == "192.168.1.50"
        assert sd.subnet == "192.168.1.0/24"
        assert sd.first_seen is not None
        assert sd.last_seen is not None

    def test_from_roku_device_subnet_failure(self):
        rd = RokuDevice(name="Test", model="M", serial="S", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            sd = SavedDevice.from_roku_device(rd)
        assert sd.source_ip is None
        assert sd.subnet is None

    def test_default_timestamps_are_set(self):
        sd = SavedDevice(name="A", model="B", serial="C", host="1.2.3.4")
        # first_seen and last_seen should be valid ISO timestamps
        datetime.fromisoformat(sd.first_seen)
        datetime.fromisoformat(sd.last_seen)

    def test_default_favorites_and_app_cache(self):
        sd = SavedDevice(name="A", model="B", serial="C", host="1.2.3.4")
        assert sd.favorites == []
        assert sd.app_cache is None

    def test_round_trip_with_favorites_and_cache(self):
        cache = {"fetched_at": _now_iso(), "apps": [{"id": "12", "name": "Netflix"}]}
        sd = SavedDevice(
            name="A", model="B", serial="C", host="1.2.3.4",
            favorites=["12", "13"],
            app_cache=cache,
        )
        d = sd.to_dict()
        restored = SavedDevice.from_dict(d)
        assert restored.favorites == ["12", "13"]
        assert restored.app_cache == cache

    def test_from_dict_old_format_no_favorites_or_cache(self):
        data = {"name": "Old", "model": "M", "serial": "S", "host": "10.0.0.1"}
        sd = SavedDevice.from_dict(data)
        assert sd.favorites == []
        assert sd.app_cache is None

    def test_from_dict_non_list_favorites_defaults_to_empty(self):
        data = {"name": "A", "model": "B", "serial": "C", "host": "1.2.3.4", "favorites": "bad"}
        sd = SavedDevice.from_dict(data)
        assert sd.favorites == []

    def test_to_dict_omits_app_cache_when_none(self):
        sd = SavedDevice(name="A", model="B", serial="C", host="1.2.3.4")
        d = sd.to_dict()
        assert "app_cache" not in d
        assert d["favorites"] == []


# ---------------------------------------------------------------------------
# _device_key
# ---------------------------------------------------------------------------

class TestDeviceKey:
    def test_uses_serial_when_known(self):
        d = RokuDevice(name="R", model="M", serial="ABC123", host="10.0.0.1")
        assert _device_key(d) == "ABC123"

    def test_falls_back_to_host_port_for_unknown(self):
        d = RokuDevice(name="R", model="M", serial="Unknown", host="10.0.0.1", port=8060)
        assert _device_key(d) == "10.0.0.1:8060"

    def test_falls_back_for_empty_serial(self):
        d = RokuDevice(name="R", model="M", serial="", host="10.0.0.1", port=8060)
        assert _device_key(d) == "10.0.0.1:8060"


# ---------------------------------------------------------------------------
# get_config_dir
# ---------------------------------------------------------------------------

class TestGetConfigDir:
    def test_respects_xdg_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "custom"))
        result = get_config_dir()
        assert result == tmp_path / "custom" / "roku-tui"

    def test_default_fallback(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = get_config_dir()
        assert result == Path.home() / ".config" / "roku-tui"


# ---------------------------------------------------------------------------
# get_local_subnet
# ---------------------------------------------------------------------------

class TestGetLocalSubnet:
    def test_happy_path(self):
        with patch("roku_tui.storage.socket.socket") as mock_sock_cls:
            mock_sock = mock_sock_cls.return_value
            mock_sock.getsockname.return_value = ("192.168.1.50", 0)
            source_ip, subnet = get_local_subnet("192.168.1.100")
        assert source_ip == "192.168.1.50"
        assert subnet == "192.168.1.0/24"
        mock_sock.connect.assert_called_once_with(("192.168.1.100", 80))
        mock_sock.close.assert_called_once()

    def test_oserror_returns_none(self):
        with patch("roku_tui.storage.socket.socket", side_effect=OSError("fail")):
            source_ip, subnet = get_local_subnet("10.0.0.1")
        assert source_ip is None
        assert subnet is None


# ---------------------------------------------------------------------------
# DeviceStore
# ---------------------------------------------------------------------------

class TestDeviceStore:
    def test_load_missing_file(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        result = store.load()
        assert result == {}

    def test_save_creates_dirs_and_file(self, tmp_path):
        path = tmp_path / "subdir" / "devices.json"
        store = DeviceStore(path)
        store.load()
        store.save()
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert data["devices"] == {}

    def test_save_and_load_round_trip(self, tmp_path):
        path = tmp_path / "devices.json"
        store = DeviceStore(path)
        device = RokuDevice(name="Test", model="Ultra", serial="ABC", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        store.save()

        store2 = DeviceStore(path)
        loaded = store2.load()
        assert "ABC" in loaded
        assert loaded["ABC"].name == "Test"
        assert loaded["ABC"].host == "10.0.0.1"

    def test_merge_new_device(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        device = RokuDevice(name="New", model="M", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=("10.0.0.50", "10.0.0.0/24")):
            key = store.merge_device(device)
        assert key == "S1"
        saved = store.devices["S1"]
        assert saved.name == "New"
        assert saved.source_ip == "10.0.0.50"
        assert saved.subnet == "10.0.0.0/24"

    def test_merge_existing_updates_fields_preserves_first_seen(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        device1 = RokuDevice(name="Old Name", model="M1", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device1)
        first_seen_original = store.devices["S1"].first_seen

        device2 = RokuDevice(name="New Name", model="M2", serial="S1", host="10.0.0.2")
        with patch("roku_tui.storage.get_local_subnet", return_value=("10.0.0.50", "10.0.0.0/24")):
            store.merge_device(device2)

        updated = store.devices["S1"]
        assert updated.name == "New Name"
        assert updated.model == "M2"
        assert updated.host == "10.0.0.2"
        assert updated.first_seen == first_seen_original
        assert updated.source_ip == "10.0.0.50"

    def test_mark_connected(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        device = RokuDevice(name="R", model="M", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        assert store.devices["S1"].last_connected is None

        store.mark_connected("S1")
        assert store.devices["S1"].last_connected is not None
        datetime.fromisoformat(store.devices["S1"].last_connected)

    def test_mark_connected_nonexistent_key(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        # Should not raise
        store.mark_connected("NOPE")

    def test_corrupt_json_backup(self, tmp_path):
        path = tmp_path / "devices.json"
        path.write_text("not json at all{{{", encoding="utf-8")
        store = DeviceStore(path)
        result = store.load()
        assert result == {}
        assert (tmp_path / "devices.json.bak").exists()

    def test_wrong_schema_version_backup(self, tmp_path):
        path = tmp_path / "devices.json"
        path.write_text(json.dumps({"version": 999, "devices": {}}), encoding="utf-8")
        store = DeviceStore(path)
        result = store.load()
        assert result == {}
        assert (tmp_path / "devices.json.bak").exists()

    def test_partial_corrupt_entries_skipped(self, tmp_path):
        path = tmp_path / "devices.json"
        data = {
            "version": 1,
            "devices": {
                "GOOD": {"name": "Good", "model": "M", "serial": "GOOD", "host": "10.0.0.1"},
                "BAD": "not a dict",
            },
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        store = DeviceStore(path)
        result = store.load()
        assert "GOOD" in result
        assert "BAD" not in result

    def test_devices_property_returns_copy(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        device = RokuDevice(name="R", model="M", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        copy1 = store.devices
        copy1.pop("S1")
        # Internal state unaffected
        assert "S1" in store.devices

    def test_unknown_serial_uses_host_port_key(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        device = RokuDevice(name="R", model="M", serial="Unknown", host="10.0.0.1", port=8060)
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            key = store.merge_device(device)
        assert key == "10.0.0.1:8060"
        assert "10.0.0.1:8060" in store.devices

    def test_atomic_write_replaces_file(self, tmp_path):
        path = tmp_path / "devices.json"
        store = DeviceStore(path)
        store.load()
        device = RokuDevice(name="R", model="M", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        store.save()

        # No .tmp file left behind
        assert not (tmp_path / "devices.tmp").exists()
        assert path.exists()
        data = json.loads(path.read_text())
        assert "S1" in data["devices"]

    def test_load_non_dict_devices_field(self, tmp_path):
        path = tmp_path / "devices.json"
        path.write_text(json.dumps({"version": 1, "devices": "bad"}), encoding="utf-8")
        store = DeviceStore(path)
        result = store.load()
        assert result == {}

    def test_multiple_devices_persist(self, tmp_path):
        path = tmp_path / "devices.json"
        store = DeviceStore(path)
        store.load()
        d1 = RokuDevice(name="A", model="M", serial="S1", host="10.0.0.1")
        d2 = RokuDevice(name="B", model="M", serial="S2", host="10.0.0.2")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(d1)
            store.merge_device(d2)
        store.save()

        store2 = DeviceStore(path)
        loaded = store2.load()
        assert len(loaded) == 2
        assert "S1" in loaded
        assert "S2" in loaded

    def test_set_favorites(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        device = RokuDevice(name="R", model="M", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        store.set_favorites("S1", ["12", "13", "14"])
        assert store.devices["S1"].favorites == ["12", "13", "14"]

    def test_set_favorites_truncates_to_five(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        device = RokuDevice(name="R", model="M", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        store.set_favorites("S1", ["1", "2", "3", "4", "5", "6", "7"])
        assert len(store.devices["S1"].favorites) == 5

    def test_set_favorites_nonexistent_key(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        # Should not raise
        store.set_favorites("NOPE", ["12"])

    def test_set_app_cache(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        device = RokuDevice(name="R", model="M", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        apps = [{"id": "12", "name": "Netflix"}]
        store.set_app_cache("S1", apps)
        cache = store.devices["S1"].app_cache
        assert cache is not None
        assert cache["apps"] == apps
        assert "fetched_at" in cache

    def test_set_app_cache_nonexistent_key(self, tmp_path):
        store = DeviceStore(tmp_path / "devices.json")
        store.load()
        # Should not raise
        store.set_app_cache("NOPE", [])

    def test_favorites_and_cache_persist_through_save_load(self, tmp_path):
        path = tmp_path / "devices.json"
        store = DeviceStore(path)
        store.load()
        device = RokuDevice(name="R", model="M", serial="S1", host="10.0.0.1")
        with patch("roku_tui.storage.get_local_subnet", return_value=(None, None)):
            store.merge_device(device)
        store.set_favorites("S1", ["12", "13"])
        store.set_app_cache("S1", [{"id": "12", "name": "Netflix"}])
        store.save()

        store2 = DeviceStore(path)
        loaded = store2.load()
        assert loaded["S1"].favorites == ["12", "13"]
        assert loaded["S1"].app_cache is not None
        assert loaded["S1"].app_cache["apps"] == [{"id": "12", "name": "Netflix"}]
