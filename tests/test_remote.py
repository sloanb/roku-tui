"""Tests for the Roku ECP remote control client."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import httpx
import pytest

from roku_tui.discovery import RokuDevice
from roku_tui.errors import ErrorCode, RokuError
from roku_tui.remote import RokuKey, RokuRemote

from tests.fixtures import APPS_XML, APPS_XML_EMPTY, DEVICE_INFO_XML


def _make_response(text: str = "", status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    return resp


# ---------------------------------------------------------------------------
# RokuKey
# ---------------------------------------------------------------------------

class TestRokuKey:
    def test_all_values_are_strings(self):
        for key in RokuKey:
            assert isinstance(key.value, str)

    def test_play_value(self):
        assert RokuKey.PLAY.value == "Play"

    def test_from_string(self):
        assert RokuKey("Home") is RokuKey.HOME
        assert RokuKey("VolumeUp") is RokuKey.VOLUME_UP


# ---------------------------------------------------------------------------
# RokuRemote.keypress
# ---------------------------------------------------------------------------

class TestKeypress:
    @pytest.mark.asyncio
    async def test_sends_post(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(return_value=_make_response())

        await remote.keypress(RokuKey.PLAY)

        remote._client.post.assert_called_once_with(
            "http://192.168.1.100:8060/keypress/Play"
        )

    @pytest.mark.asyncio
    async def test_all_keys(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(return_value=_make_response())

        for key in RokuKey:
            await remote.keypress(key)
            remote._client.post.assert_called_with(
                f"http://192.168.1.100:8060/keypress/{key.value}"
            )

    @pytest.mark.asyncio
    async def test_timeout_raises_e1007(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(RokuError) as exc_info:
            await remote.keypress(RokuKey.PLAY)
        assert exc_info.value.error_code is ErrorCode.E1007

    @pytest.mark.asyncio
    async def test_connect_error_raises_e1008(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(RokuError) as exc_info:
            await remote.keypress(RokuKey.HOME)
        assert exc_info.value.error_code is ErrorCode.E1008

    @pytest.mark.asyncio
    async def test_http_status_error_raises_e1004(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(return_value=_make_response(status_code=500))

        with pytest.raises(RokuError) as exc_info:
            await remote.keypress(RokuKey.SELECT)
        assert exc_info.value.error_code is ErrorCode.E1004

    @pytest.mark.asyncio
    async def test_generic_http_error_raises_e1004(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(
            side_effect=httpx.HTTPError("something went wrong")
        )

        with pytest.raises(RokuError) as exc_info:
            await remote.keypress(RokuKey.UP)
        assert exc_info.value.error_code is ErrorCode.E1004


# ---------------------------------------------------------------------------
# RokuRemote.send_text
# ---------------------------------------------------------------------------

class TestSendText:
    @pytest.mark.asyncio
    async def test_sends_each_character(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(return_value=_make_response())

        await remote.send_text("Hi")

        assert remote._client.post.call_count == 2
        remote._client.post.assert_any_call(
            "http://192.168.1.100:8060/keypress/Lit_H"
        )
        remote._client.post.assert_any_call(
            "http://192.168.1.100:8060/keypress/Lit_i"
        )

    @pytest.mark.asyncio
    async def test_encodes_special_characters(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(return_value=_make_response())

        await remote.send_text(" ")

        remote._client.post.assert_called_once_with(
            "http://192.168.1.100:8060/keypress/Lit_%20"
        )

    @pytest.mark.asyncio
    async def test_timeout_raises_e1007(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(RokuError) as exc_info:
            await remote.send_text("a")
        assert exc_info.value.error_code is ErrorCode.E1007

    @pytest.mark.asyncio
    async def test_http_error_raises_e1004(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(
            side_effect=httpx.HTTPError("fail")
        )

        with pytest.raises(RokuError) as exc_info:
            await remote.send_text("x")
        assert exc_info.value.error_code is ErrorCode.E1004


# ---------------------------------------------------------------------------
# RokuRemote.get_device_info
# ---------------------------------------------------------------------------

class TestGetDeviceInfo:
    @pytest.mark.asyncio
    async def test_parses_xml(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(return_value=_make_response(DEVICE_INFO_XML))

        info = await remote.get_device_info()

        assert info["user-device-name"] == "Living Room Roku"
        assert info["model-name"] == "Roku Ultra"
        assert info["serial-number"] == "ABC123XYZ"

    @pytest.mark.asyncio
    async def test_timeout_raises_e1007(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(RokuError) as exc_info:
            await remote.get_device_info()
        assert exc_info.value.error_code is ErrorCode.E1007

    @pytest.mark.asyncio
    async def test_connect_error_raises_e1008(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(RokuError) as exc_info:
            await remote.get_device_info()
        assert exc_info.value.error_code is ErrorCode.E1008

    @pytest.mark.asyncio
    async def test_bad_xml_raises_e1009(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(return_value=_make_response("not xml<<<"))

        with pytest.raises(RokuError) as exc_info:
            await remote.get_device_info()
        assert exc_info.value.error_code is ErrorCode.E1009

    @pytest.mark.asyncio
    async def test_http_error_raises_e1005(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))

        with pytest.raises(RokuError) as exc_info:
            await remote.get_device_info()
        assert exc_info.value.error_code is ErrorCode.E1005


# ---------------------------------------------------------------------------
# RokuRemote.get_apps
# ---------------------------------------------------------------------------

class TestGetApps:
    @pytest.mark.asyncio
    async def test_parses_app_list(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(return_value=_make_response(APPS_XML))

        apps = await remote.get_apps()

        assert len(apps) == 3
        assert apps[0] == {"id": "12", "name": "Netflix", "type": "appl", "version": "4.1"}
        assert apps[1]["name"] == "YouTube"
        assert apps[2]["name"] == "Hulu"

    @pytest.mark.asyncio
    async def test_empty_app_list(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(return_value=_make_response(APPS_XML_EMPTY))

        apps = await remote.get_apps()
        assert apps == []

    @pytest.mark.asyncio
    async def test_timeout_raises_e1007(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(RokuError) as exc_info:
            await remote.get_apps()
        assert exc_info.value.error_code is ErrorCode.E1007

    @pytest.mark.asyncio
    async def test_connect_error_raises_e1008(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(RokuError) as exc_info:
            await remote.get_apps()
        assert exc_info.value.error_code is ErrorCode.E1008

    @pytest.mark.asyncio
    async def test_bad_xml_raises_e1009(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(return_value=_make_response("<<<"))

        with pytest.raises(RokuError) as exc_info:
            await remote.get_apps()
        assert exc_info.value.error_code is ErrorCode.E1009

    @pytest.mark.asyncio
    async def test_http_error_raises_e1005(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))

        with pytest.raises(RokuError) as exc_info:
            await remote.get_apps()
        assert exc_info.value.error_code is ErrorCode.E1005


# ---------------------------------------------------------------------------
# RokuRemote.launch_app
# ---------------------------------------------------------------------------

class TestLaunchApp:
    @pytest.mark.asyncio
    async def test_sends_post(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(return_value=_make_response())

        await remote.launch_app("12")

        remote._client.post.assert_called_once_with(
            "http://192.168.1.100:8060/launch/12"
        )

    @pytest.mark.asyncio
    async def test_timeout_raises_e1007(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(RokuError) as exc_info:
            await remote.launch_app("12")
        assert exc_info.value.error_code is ErrorCode.E1007

    @pytest.mark.asyncio
    async def test_http_error_raises_e1004(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()
        remote._client.post = AsyncMock(side_effect=httpx.HTTPError("fail"))

        with pytest.raises(RokuError) as exc_info:
            await remote.launch_app("99")
        assert exc_info.value.error_code is ErrorCode.E1004


# ---------------------------------------------------------------------------
# RokuRemote.close
# ---------------------------------------------------------------------------

class TestClose:
    @pytest.mark.asyncio
    async def test_closes_client(self, fake_device):
        remote = RokuRemote(fake_device)
        remote._client = AsyncMock()

        await remote.close()

        remote._client.aclose.assert_called_once()
