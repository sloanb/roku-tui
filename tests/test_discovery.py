"""Tests for the device discovery module."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from roku_tui.discovery import (
    M_SEARCH,
    RokuDevice,
    _fetch_device_info,
    _ssdp_search,
    connect_device,
    discover_devices,
)
from roku_tui.errors import ErrorCode, RokuError

from tests.fixtures import (
    DEVICE_INFO_XML,
    DEVICE_INFO_XML_MINIMAL,
    SSDP_RESPONSE,
    SSDP_RESPONSE_TWO,
)


# ---------------------------------------------------------------------------
# RokuDevice
# ---------------------------------------------------------------------------

class TestRokuDevice:
    def test_base_url(self, fake_device):
        assert fake_device.base_url == "http://192.168.1.100:8060"

    def test_base_url_custom_port(self):
        d = RokuDevice(name="X", model="Y", serial="Z", host="10.0.0.1", port=9090)
        assert d.base_url == "http://10.0.0.1:9090"

    def test_str(self, fake_device):
        assert str(fake_device) == "Living Room Roku (Roku Ultra)"

    def test_default_port(self):
        d = RokuDevice(name="A", model="B", serial="C", host="1.2.3.4")
        assert d.port == 8060


# ---------------------------------------------------------------------------
# _ssdp_search
# ---------------------------------------------------------------------------

class TestSsdpSearch:
    def test_happy_path_returns_locations(self):
        mock_sock = MagicMock()
        # First recvfrom returns data, second raises timeout
        mock_sock.recvfrom.side_effect = [
            (SSDP_RESPONSE.encode(), ("192.168.1.100", 1900)),
            socket.timeout(),
        ]

        with patch("roku_tui.discovery.socket.socket", return_value=mock_sock):
            result = _ssdp_search(timeout=1.0)

        assert result == ["http://192.168.1.100:8060/"]
        # Verify sendto called twice (we send M-SEARCH twice)
        assert mock_sock.sendto.call_count == 2

    def test_multiple_devices(self):
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = [
            (SSDP_RESPONSE.encode(), ("192.168.1.100", 1900)),
            (SSDP_RESPONSE_TWO.encode(), ("192.168.1.101", 1900)),
            socket.timeout(),
        ]

        with patch("roku_tui.discovery.socket.socket", return_value=mock_sock):
            result = _ssdp_search(timeout=1.0)

        assert len(result) == 2
        assert "http://192.168.1.100:8060/" in result
        assert "http://192.168.1.101:8060/" in result

    def test_deduplicates_locations(self):
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = [
            (SSDP_RESPONSE.encode(), ("192.168.1.100", 1900)),
            (SSDP_RESPONSE.encode(), ("192.168.1.100", 1900)),  # duplicate
            socket.timeout(),
        ]

        with patch("roku_tui.discovery.socket.socket", return_value=mock_sock):
            result = _ssdp_search(timeout=1.0)

        assert result == ["http://192.168.1.100:8060/"]

    def test_no_responses(self):
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = socket.timeout()

        with patch("roku_tui.discovery.socket.socket", return_value=mock_sock):
            result = _ssdp_search(timeout=1.0)

        assert result == []

    def test_socket_creation_error(self):
        with patch("roku_tui.discovery.socket.socket", side_effect=OSError("No network")):
            with pytest.raises(RokuError) as exc_info:
                _ssdp_search()
            assert exc_info.value.error_code is ErrorCode.E1010

    def test_send_error_raises_e1001(self):
        mock_sock = MagicMock()
        mock_sock.sendto.side_effect = OSError("Network is unreachable")

        with patch("roku_tui.discovery.socket.socket", return_value=mock_sock):
            with pytest.raises(RokuError) as exc_info:
                _ssdp_search()
            assert exc_info.value.error_code is ErrorCode.E1001

    def test_recv_oserror_breaks_loop(self):
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = [
            (SSDP_RESPONSE.encode(), ("192.168.1.100", 1900)),
            OSError("Connection reset"),
        ]

        with patch("roku_tui.discovery.socket.socket", return_value=mock_sock):
            result = _ssdp_search(timeout=1.0)

        assert result == ["http://192.168.1.100:8060/"]

    def test_response_without_location_ignored(self):
        no_location = (
            "HTTP/1.1 200 OK\r\n"
            "ST: roku:ecp\r\n"
            "\r\n"
        )
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = [
            (no_location.encode(), ("192.168.1.100", 1900)),
            socket.timeout(),
        ]

        with patch("roku_tui.discovery.socket.socket", return_value=mock_sock):
            result = _ssdp_search(timeout=1.0)

        assert result == []


# ---------------------------------------------------------------------------
# _fetch_device_info
# ---------------------------------------------------------------------------

class TestFetchDeviceInfo:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        mock_resp = MagicMock()
        mock_resp.text = DEVICE_INFO_XML
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)

        device = await _fetch_device_info(client, "http://192.168.1.100:8060/")

        assert device is not None
        assert device.name == "Living Room Roku"
        assert device.model == "Roku Ultra"
        assert device.serial == "ABC123XYZ"
        assert device.host == "192.168.1.100"
        assert device.port == 8060

    @pytest.mark.asyncio
    async def test_minimal_xml_uses_fallbacks(self):
        mock_resp = MagicMock()
        mock_resp.text = DEVICE_INFO_XML_MINIMAL
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)

        device = await _fetch_device_info(client, "http://10.0.0.5:8060/")

        assert device is not None
        assert device.name == "Roku Express"  # falls back to model-name
        assert device.serial == "Unknown"

    @pytest.mark.asyncio
    async def test_invalid_xml_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.text = "not xml at all <<<"
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)

        device = await _fetch_device_info(client, "http://192.168.1.100:8060/")
        assert device is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        device = await _fetch_device_info(client, "http://192.168.1.100:8060/")
        assert device is None

    @pytest.mark.asyncio
    async def test_default_port_when_missing(self):
        mock_resp = MagicMock()
        mock_resp.text = DEVICE_INFO_XML
        mock_resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get = AsyncMock(return_value=mock_resp)

        device = await _fetch_device_info(client, "http://192.168.1.100/")
        assert device is not None
        assert device.port == 8060


# ---------------------------------------------------------------------------
# discover_devices
# ---------------------------------------------------------------------------

class TestDiscoverDevices:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        mock_resp = MagicMock()
        mock_resp.text = DEVICE_INFO_XML
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("roku_tui.discovery._ssdp_search", return_value=["http://192.168.1.100:8060/"]),
            patch("roku_tui.discovery.httpx.AsyncClient", return_value=mock_client),
        ):
            devices = await discover_devices(timeout=1.0)

        assert len(devices) == 1
        assert devices[0].name == "Living Room Roku"

    @pytest.mark.asyncio
    async def test_no_locations_returns_empty(self):
        with patch("roku_tui.discovery._ssdp_search", return_value=[]):
            devices = await discover_devices(timeout=1.0)

        assert devices == []

    @pytest.mark.asyncio
    async def test_fetch_failure_skipped(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("roku_tui.discovery._ssdp_search", return_value=["http://192.168.1.100:8060/"]),
            patch("roku_tui.discovery.httpx.AsyncClient", return_value=mock_client),
        ):
            devices = await discover_devices(timeout=1.0)

        assert devices == []

    @pytest.mark.asyncio
    async def test_ssdp_error_propagates(self):
        with patch(
            "roku_tui.discovery._ssdp_search",
            side_effect=RokuError(ErrorCode.E1010, "no network"),
        ):
            with pytest.raises(RokuError) as exc_info:
                await discover_devices()
            assert exc_info.value.error_code is ErrorCode.E1010


# ---------------------------------------------------------------------------
# connect_device
# ---------------------------------------------------------------------------

class TestConnectDevice:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        mock_resp = MagicMock()
        mock_resp.text = DEVICE_INFO_XML
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("roku_tui.discovery.httpx.AsyncClient", return_value=mock_client):
            device = await connect_device("192.168.1.100")

        assert device.name == "Living Room Roku"
        assert device.model == "Roku Ultra"
        assert device.serial == "ABC123XYZ"
        assert device.host == "192.168.1.100"
        assert device.port == 8060

    @pytest.mark.asyncio
    async def test_custom_port(self):
        mock_resp = MagicMock()
        mock_resp.text = DEVICE_INFO_XML
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("roku_tui.discovery.httpx.AsyncClient", return_value=mock_client):
            device = await connect_device("10.0.0.1", port=9090)

        assert device.host == "10.0.0.1"
        assert device.port == 9090

    @pytest.mark.asyncio
    async def test_unreachable_host_raises_e1003(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("roku_tui.discovery.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RokuError) as exc_info:
                await connect_device("192.168.1.200")
            assert exc_info.value.error_code is ErrorCode.E1003

    @pytest.mark.asyncio
    async def test_invalid_xml_raises_e1009(self):
        mock_resp = MagicMock()
        mock_resp.text = "not xml at all <<<"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("roku_tui.discovery.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RokuError) as exc_info:
                await connect_device("192.168.1.100")
            assert exc_info.value.error_code is ErrorCode.E1009

    @pytest.mark.asyncio
    async def test_timeout_raises_e1007(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("roku_tui.discovery.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RokuError) as exc_info:
                await connect_device("192.168.1.100")
            assert exc_info.value.error_code is ErrorCode.E1007
