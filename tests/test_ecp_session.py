"""Tests for the ECP-2 session module."""

import hashlib
import struct
from base64 import b64encode
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from roku_tui.ecp_session import (
    RTCP_APP,
    RTCP_BYE,
    RTCP_RR,
    RtcpAppName,
    _AUTH_KEY,
    _KEY,
    _char_transform,
    build_rtcp_app_packet,
    build_rtcp_bye_packet,
    build_rtcp_rr_packet,
    compute_auth_response,
    parse_rtcp_app_packet,
    EcpSession,
)
from roku_tui.errors import ErrorCode, RokuError


class _AsyncIter:
    """Helper to make a list work with ``async for``."""

    def __init__(self, items):
        self._it = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


# ---------------------------------------------------------------------------
# Auth key derivation
# ---------------------------------------------------------------------------


class TestCharTransform:
    def test_digit_transforms(self):
        # 0->8, 9->F
        assert _char_transform(ord("0"), 9) == "8"
        assert _char_transform(ord("9"), 9) == "F"

    def test_hex_letter_transforms(self):
        # A->E, F->9, C->C
        assert _char_transform(ord("A"), 9) == "E"
        assert _char_transform(ord("F"), 9) == "9"
        assert _char_transform(ord("C"), 9) == "C"

    def test_non_hex_unchanged(self):
        assert _char_transform(ord("-"), 9) == "-"
        assert _char_transform(ord("Z"), 9) == "Z"

    def test_auth_key_is_bytes(self):
        assert isinstance(_AUTH_KEY, bytes)
        # KEY is a UUID-like string with 36 chars
        assert len(_AUTH_KEY) == len(_KEY)

    def test_auth_key_deterministic(self):
        computed = "".join(_char_transform(ord(c), 9) for c in _KEY).encode()
        assert computed == _AUTH_KEY


class TestComputeAuthResponse:
    def test_returns_base64_string(self):
        result = compute_auth_response("test-challenge")
        assert isinstance(result, str)
        # Should be valid base64 of a SHA1 digest (28 chars)
        assert len(result) == 28

    def test_matches_manual_computation(self):
        challenge = "hello-world"
        expected = b64encode(
            hashlib.sha1(challenge.encode() + _AUTH_KEY).digest()
        ).decode()
        assert compute_auth_response(challenge) == expected

    def test_different_challenges_give_different_responses(self):
        r1 = compute_auth_response("challenge-1")
        r2 = compute_auth_response("challenge-2")
        assert r1 != r2


# ---------------------------------------------------------------------------
# RTCP packet building
# ---------------------------------------------------------------------------


class TestBuildRtcpAppPacket:
    def test_packet_is_16_bytes(self):
        pkt = build_rtcp_app_packet("VDLY", b"\x00\x00\x00\x01")
        assert len(pkt) == 16

    def test_header_fields(self):
        pkt = build_rtcp_app_packet("VDLY", b"\x00" * 4)
        assert pkt[0] == 0x80  # V=2, P=0, subtype=0
        assert pkt[1] == RTCP_APP  # PT=204
        length = struct.unpack("!H", pkt[2:4])[0]
        assert length == 3  # 4 words total

    def test_ssrc_default_zero(self):
        pkt = build_rtcp_app_packet("VDLY", b"\x00" * 4)
        ssrc = struct.unpack("!I", pkt[4:8])[0]
        assert ssrc == 0

    def test_ssrc_custom(self):
        pkt = build_rtcp_app_packet("VDLY", b"\x00" * 4, ssrc=42)
        ssrc = struct.unpack("!I", pkt[4:8])[0]
        assert ssrc == 42

    def test_name_bytes(self):
        pkt = build_rtcp_app_packet("VDLY", b"\x00" * 4)
        assert pkt[8:12] == b"VDLY"

    def test_app_data(self):
        data = (200 * 1000).to_bytes(4, "big")
        pkt = build_rtcp_app_packet("VDLY", data)
        assert pkt[12:16] == data

    def test_short_name_padded(self):
        pkt = build_rtcp_app_packet("AB", b"\x01\x02\x03\x04")
        assert pkt[8:12] == b"AB\x00\x00"

    def test_short_data_padded(self):
        pkt = build_rtcp_app_packet("CVER", b"00")
        assert pkt[12:14] == b"00"
        assert pkt[14:16] == b"\x00\x00"


class TestBuildRtcpByePacket:
    def test_packet_is_8_bytes(self):
        pkt = build_rtcp_bye_packet()
        assert len(pkt) == 8

    def test_header_fields(self):
        pkt = build_rtcp_bye_packet()
        assert pkt[0] == 0x81  # V=2, P=0, SC=1
        assert pkt[1] == RTCP_BYE  # PT=203
        length = struct.unpack("!H", pkt[2:4])[0]
        assert length == 1


class TestBuildRtcpRrPacket:
    def test_packet_is_8_bytes(self):
        pkt = build_rtcp_rr_packet()
        assert len(pkt) == 8

    def test_header_fields(self):
        pkt = build_rtcp_rr_packet()
        assert pkt[0] == 0x80  # V=2, P=0, RC=0
        assert pkt[1] == RTCP_RR  # PT=201


# ---------------------------------------------------------------------------
# RTCP packet parsing
# ---------------------------------------------------------------------------


class TestParseRtcpAppPacket:
    def test_parses_valid_packet(self):
        pkt = build_rtcp_app_packet("XDLY", b"\x00\x01\x00\x00")
        result = parse_rtcp_app_packet(pkt)
        assert result is not None
        name, data = result
        assert name == "XDLY"
        assert data == b"\x00\x01\x00\x00"

    def test_returns_none_for_short_data(self):
        assert parse_rtcp_app_packet(b"\x00" * 15) is None

    def test_returns_none_for_non_app_packet(self):
        pkt = build_rtcp_bye_packet()
        # BYE is only 8 bytes, too short for APP parse
        assert parse_rtcp_app_packet(pkt) is None

    def test_returns_none_for_wrong_pt(self):
        # 16 bytes but PT=201 (RR), not 204 (APP)
        pkt = build_rtcp_rr_packet() + b"\x00" * 8
        assert parse_rtcp_app_packet(pkt) is None

    def test_roundtrip_all_app_names(self):
        for app_name in RtcpAppName:
            pkt = build_rtcp_app_packet(app_name.value, b"\xAA\xBB\xCC\xDD")
            result = parse_rtcp_app_packet(pkt)
            assert result is not None
            assert result[0] == app_name.value
            assert result[1] == b"\xAA\xBB\xCC\xDD"


# ---------------------------------------------------------------------------
# EcpSession
# ---------------------------------------------------------------------------


class TestEcpSession:
    def test_initial_state(self):
        session = EcpSession("192.168.1.1")
        assert not session.connected
        assert session._request_id == 0

    @pytest.mark.asyncio
    async def test_connect_missing_websockets(self):
        session = EcpSession("192.168.1.1")
        with patch.dict("sys.modules", {"websockets": None}):
            with patch("builtins.__import__", side_effect=ImportError("no websockets")):
                with pytest.raises(RokuError) as exc_info:
                    await session.connect("192.168.1.2")
                assert exc_info.value.error_code is ErrorCode.E1015

    @pytest.mark.asyncio
    async def test_connect_websocket_failure(self):
        mock_ws_module = MagicMock()
        mock_ws_module.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))

        session = EcpSession("192.168.1.1")
        with patch.dict("sys.modules", {"websockets": mock_ws_module}):
            with pytest.raises(RokuError) as exc_info:
                await session.connect("192.168.1.2")
            assert exc_info.value.error_code is ErrorCode.E1012

    @pytest.mark.asyncio
    async def test_connect_auth_success(self):
        """Simulate a full auth flow: challenge → auth response → set-audio-output."""
        import json

        challenge_msg = json.dumps({
            "param-challenge": "test-challenge-123",
            "request-id": "0",
        })
        auth_ok_msg = json.dumps({
            "response": "authenticate",
            "status": "200",
            "request-id": "1",
        })

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.__aiter__ = MagicMock(
            return_value=_AsyncIter([challenge_msg, auth_ok_msg])
        )

        mock_ws_module = MagicMock()
        mock_ws_module.connect = AsyncMock(return_value=mock_ws)

        session = EcpSession("192.168.1.1")
        with patch.dict("sys.modules", {"websockets": mock_ws_module}):
            await session.connect("192.168.1.2")

        assert session.connected
        assert session._audio_requested
        # Should have sent 2 messages: auth response + set-audio-output
        assert mock_ws.send.call_count == 2

        # Verify auth response
        auth_call = json.loads(mock_ws.send.call_args_list[0][0][0])
        assert auth_call["request"] == "authenticate"
        assert auth_call["param-response"] == compute_auth_response("test-challenge-123")

        # Verify set-audio-output
        audio_call = json.loads(mock_ws.send.call_args_list[1][0][0])
        assert audio_call["request"] == "set-audio-output"
        assert audio_call["param-audio-output"] == "datagram"
        assert "6970" in audio_call["param-devname"]

    @pytest.mark.asyncio
    async def test_connect_auth_failure(self):
        import json

        challenge_msg = json.dumps({"param-challenge": "test"})
        auth_fail_msg = json.dumps({
            "response": "authenticate",
            "status": "401",
        })

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.__aiter__ = MagicMock(
            return_value=_AsyncIter([challenge_msg, auth_fail_msg])
        )

        mock_ws_module = MagicMock()
        mock_ws_module.connect = AsyncMock(return_value=mock_ws)

        session = EcpSession("192.168.1.1")
        with patch.dict("sys.modules", {"websockets": mock_ws_module}):
            with pytest.raises(RokuError) as exc_info:
                await session.connect("192.168.1.2")
            assert exc_info.value.error_code is ErrorCode.E1013

    @pytest.mark.asyncio
    async def test_close(self):
        mock_ws = AsyncMock()
        session = EcpSession("192.168.1.1")
        session._ws = mock_ws

        await session.close()
        mock_ws.close.assert_called_once()
        assert session._ws is None

    @pytest.mark.asyncio
    async def test_close_when_not_connected(self):
        session = EcpSession("192.168.1.1")
        await session.close()  # should not raise
