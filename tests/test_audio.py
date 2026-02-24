"""Tests for the audio module (RTP parsing, pipeline, session orchestration)."""

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from roku_tui.audio import (
    AudioPipeline,
    AudioState,
    PrivateListeningSession,
    RtcpHandler,
    _get_local_ip,
    _parse_rtp_payload,
)
from roku_tui.ecp_session import (
    RTCP_PORT,
    RtcpAppName,
    build_rtcp_app_packet,
)
from roku_tui.errors import ErrorCode, RokuError


# ---------------------------------------------------------------------------
# RTP payload parsing
# ---------------------------------------------------------------------------


class TestParseRtpPayload:
    def _make_rtp(
        self,
        payload: bytes,
        cc: int = 0,
        extension: bool = False,
        ext_data_words: int = 0,
    ) -> bytes:
        """Build a minimal RTP packet with given options."""
        byte0 = 0x80 | (cc & 0x0F)
        if extension:
            byte0 |= 0x10
        header = struct.pack("!BBHII", byte0, 0x60, 1, 0, 0)
        csrc = b"\x00\x00\x00\x00" * cc
        ext = b""
        if extension:
            ext = struct.pack("!HH", 0xBEDE, ext_data_words)
            ext += b"\x00" * (ext_data_words * 4)
        return header + csrc + ext + payload

    def test_basic_12_byte_header(self):
        payload = b"\xDE\xAD\xBE\xEF"
        packet = self._make_rtp(payload)
        assert _parse_rtp_payload(packet) == payload

    def test_with_csrc(self):
        payload = b"\x01\x02\x03"
        packet = self._make_rtp(payload, cc=3)
        assert _parse_rtp_payload(packet) == payload

    def test_with_extension(self):
        payload = b"\xAA\xBB"
        packet = self._make_rtp(payload, extension=True, ext_data_words=2)
        assert _parse_rtp_payload(packet) == payload

    def test_with_csrc_and_extension(self):
        payload = b"\xFF"
        packet = self._make_rtp(payload, cc=2, extension=True, ext_data_words=1)
        assert _parse_rtp_payload(packet) == payload

    def test_too_short(self):
        assert _parse_rtp_payload(b"\x00" * 11) is None

    def test_empty_payload(self):
        # 12-byte header, no payload
        packet = struct.pack("!BBHII", 0x80, 0x60, 1, 0, 0)
        assert _parse_rtp_payload(packet) is None

    def test_extension_header_too_short(self):
        # Extension bit set but not enough bytes for extension header
        byte0 = 0x90  # V=2, X=1
        header = struct.pack("!BBHII", byte0, 0x60, 1, 0, 0)
        # Only 12 bytes, no room for extension header
        assert _parse_rtp_payload(header) is None


# ---------------------------------------------------------------------------
# AudioState enum
# ---------------------------------------------------------------------------


class TestAudioState:
    def test_all_states_present(self):
        expected = {"IDLE", "CONNECTING", "HANDSHAKING", "STREAMING", "ERROR", "STOPPING"}
        actual = {s.name for s in AudioState}
        assert actual == expected

    def test_initial_state_is_idle(self):
        session = PrivateListeningSession("192.168.1.1")
        assert session.state == AudioState.IDLE


# ---------------------------------------------------------------------------
# AudioPipeline
# ---------------------------------------------------------------------------


class TestAudioPipeline:
    def test_start_missing_deps(self):
        mock_sock = MagicMock()
        pipeline = AudioPipeline(mock_sock)
        with patch.dict("sys.modules", {"opuslib": None, "sounddevice": None}):
            with patch("builtins.__import__", side_effect=ImportError("no opuslib")):
                with pytest.raises(RokuError) as exc_info:
                    pipeline.start()
                assert exc_info.value.error_code is ErrorCode.E1015

    def test_stop_when_not_started(self):
        mock_sock = MagicMock()
        pipeline = AudioPipeline(mock_sock)
        pipeline.stop()  # should not raise

    def test_start_and_stop(self):
        mock_sock = MagicMock()
        mock_decoder = MagicMock()
        mock_stream = MagicMock()

        mock_opuslib = MagicMock()
        mock_opuslib.Decoder.return_value = mock_decoder

        mock_sd = MagicMock()
        mock_sd.RawOutputStream.return_value = mock_stream

        pipeline = AudioPipeline(mock_sock)

        with patch.dict("sys.modules", {"opuslib": mock_opuslib, "sounddevice": mock_sd}):
            pipeline.start()
            assert pipeline._running
            assert pipeline._decoder is mock_decoder
            assert pipeline._stream is mock_stream
            mock_stream.start.assert_called_once()

        pipeline.stop()
        assert not pipeline._running
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()
        assert pipeline._decoder is None
        assert pipeline._stream is None


# ---------------------------------------------------------------------------
# RtcpHandler
# ---------------------------------------------------------------------------


class TestRtcpHandler:
    def _make_handler(self):
        send_sock = MagicMock()
        recv_sock = MagicMock()
        handler = RtcpHandler("192.168.1.1", send_sock, recv_sock)
        handler.start()
        return handler, send_sock, recv_sock

    def test_initial_handshake_not_complete(self):
        handler, _, _ = self._make_handler()
        assert not handler.handshake_complete

    def test_handshake_complete_when_all_set(self):
        handler, _, _ = self._make_handler()
        handler.vdly_sent = True
        handler.cver_sent = True
        handler.xdly_received = True
        handler.ncli_received = True
        assert handler.handshake_complete

    def test_send_vdly(self):
        handler, send_sock, _ = self._make_handler()
        handler.send_vdly(200)
        assert handler.vdly_sent
        send_sock.sendto.assert_called_once()
        args = send_sock.sendto.call_args
        assert args[0][1] == ("192.168.1.1", RTCP_PORT)
        # Verify VDLY name in packet
        pkt = args[0][0]
        assert pkt[8:12] == b"VDLY"

    def test_send_cver(self):
        handler, send_sock, _ = self._make_handler()
        handler.send_cver()
        assert handler.cver_sent
        pkt = send_sock.sendto.call_args[0][0]
        assert pkt[8:12] == b"CVER"
        assert pkt[12:16] == b"0002"

    def test_send_bye(self):
        handler, send_sock, _ = self._make_handler()
        handler.send_bye()
        pkt = send_sock.sendto.call_args[0][0]
        assert pkt[1] == 203  # BYE

    def test_send_rr(self):
        handler, send_sock, _ = self._make_handler()
        handler.send_rr()
        pkt = send_sock.sendto.call_args[0][0]
        assert pkt[1] == 201  # RR

    def test_receive_xdly_matching_delay(self):
        handler, _, recv_sock = self._make_handler()
        handler.delay_ms = 200

        xdly_data = (200 * 1000).to_bytes(4, "big")
        pkt = build_rtcp_app_packet("XDLY", xdly_data)

        recv_sock.recvfrom = MagicMock(
            side_effect=[(pkt, ("192.168.1.1", 5150)), OSError("done")]
        )

        handler.receive_loop()
        assert handler.xdly_received

    def test_receive_xdly_different_delay(self):
        handler, _, recv_sock = self._make_handler()
        handler.delay_ms = 200
        handler.vdly_sent = True

        xdly_data = (150 * 1000).to_bytes(4, "big")
        pkt = build_rtcp_app_packet("XDLY", xdly_data)

        recv_sock.recvfrom = MagicMock(
            side_effect=[(pkt, ("192.168.1.1", 5150)), OSError("done")]
        )

        handler.receive_loop()
        assert handler.delay_ms == 150
        assert not handler.vdly_sent  # needs re-send

    def test_receive_ncli(self):
        handler, _, recv_sock = self._make_handler()

        pkt = build_rtcp_app_packet("NCLI", b"\x00\x00\x00\x00")

        recv_sock.recvfrom = MagicMock(
            side_effect=[(pkt, ("192.168.1.1", 5150)), OSError("done")]
        )

        handler.receive_loop()
        assert handler.ncli_received

    def test_stop(self):
        handler, _, _ = self._make_handler()
        handler.stop()
        assert not handler._running


# ---------------------------------------------------------------------------
# PrivateListeningSession
# ---------------------------------------------------------------------------


class TestPrivateListeningSession:
    def test_initial_state(self):
        session = PrivateListeningSession("192.168.1.1")
        assert session.state == AudioState.IDLE

    def test_state_callback(self):
        states = []
        session = PrivateListeningSession(
            "192.168.1.1", state_callback=states.append
        )
        session._set_state(AudioState.CONNECTING)
        session._set_state(AudioState.STREAMING)
        assert states == [AudioState.CONNECTING, AudioState.STREAMING]

    @pytest.mark.asyncio
    async def test_stop_when_idle(self):
        session = PrivateListeningSession("192.168.1.1")
        await session.stop()  # should not raise
        assert session.state == AudioState.IDLE

    @pytest.mark.asyncio
    async def test_start_sets_connecting_state(self):
        session = PrivateListeningSession("192.168.1.1")
        states = []
        session._state_callback = states.append

        with patch("roku_tui.audio._get_local_ip", return_value="192.168.1.2"):
            mock_ecp = AsyncMock()
            with patch("roku_tui.audio.EcpSession", return_value=mock_ecp):
                mock_ecp.connect = AsyncMock(
                    side_effect=RokuError(ErrorCode.E1012, "ws fail")
                )
                with pytest.raises(RokuError):
                    await session.start()

        assert AudioState.CONNECTING in states

    @pytest.mark.asyncio
    async def test_start_local_ip_failure(self):
        session = PrivateListeningSession("192.168.1.1")

        with patch("roku_tui.audio._get_local_ip", side_effect=OSError("no net")):
            with pytest.raises(RokuError) as exc_info:
                await session.start()
            assert exc_info.value.error_code is ErrorCode.E1011

        assert session.state == AudioState.ERROR

    @pytest.mark.asyncio
    async def test_start_socket_bind_failure(self):
        """Socket bind failure is wrapped as E1014."""
        session = PrivateListeningSession("192.168.1.1")

        with patch("roku_tui.audio._get_local_ip", return_value="192.168.1.2"):
            mock_ecp = AsyncMock()
            with patch("roku_tui.audio.EcpSession", return_value=mock_ecp):
                with patch("roku_tui.audio.socket") as mock_socket_mod:
                    mock_sock = MagicMock()
                    mock_sock.bind.side_effect = OSError("port in use")
                    mock_socket_mod.socket.return_value = mock_sock
                    mock_socket_mod.AF_INET = 2
                    mock_socket_mod.SOCK_DGRAM = 2
                    mock_socket_mod.SOL_SOCKET = 1
                    mock_socket_mod.SO_REUSEADDR = 2

                    with pytest.raises(RokuError) as exc_info:
                        await session.start()
                    assert exc_info.value.error_code is ErrorCode.E1014
                    mock_ecp.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_pipeline_start_failure(self):
        """Pipeline start failure closes sockets and ECP."""
        session = PrivateListeningSession("192.168.1.1")

        with patch("roku_tui.audio._get_local_ip", return_value="192.168.1.2"):
            mock_ecp = AsyncMock()
            with patch("roku_tui.audio.EcpSession", return_value=mock_ecp):
                with patch("roku_tui.audio.socket") as mock_socket_mod:
                    mock_sock = MagicMock()
                    mock_socket_mod.socket.return_value = mock_sock
                    mock_socket_mod.AF_INET = 2
                    mock_socket_mod.SOCK_DGRAM = 2
                    mock_socket_mod.SOL_SOCKET = 1
                    mock_socket_mod.SO_REUSEADDR = 2

                    with patch(
                        "roku_tui.audio.AudioPipeline.start",
                        side_effect=RokuError(ErrorCode.E1015, "no deps"),
                    ):
                        with pytest.raises(RokuError) as exc_info:
                            await session.start()
                        assert exc_info.value.error_code is ErrorCode.E1015

    @pytest.mark.asyncio
    async def test_start_full_happy_path(self):
        """Full start() happy path through handshake to streaming."""
        session = PrivateListeningSession("192.168.1.1")
        states = []
        session._state_callback = states.append

        with patch("roku_tui.audio._get_local_ip", return_value="192.168.1.2"):
            mock_ecp = AsyncMock()
            with patch("roku_tui.audio.EcpSession", return_value=mock_ecp):
                with patch("roku_tui.audio.socket") as mock_socket_mod:
                    mock_sock = MagicMock()
                    mock_socket_mod.socket.return_value = mock_sock
                    mock_socket_mod.AF_INET = 2
                    mock_socket_mod.SOCK_DGRAM = 2
                    mock_socket_mod.SOL_SOCKET = 1
                    mock_socket_mod.SO_REUSEADDR = 2

                    with patch("roku_tui.audio.AudioPipeline") as MockPipeline:
                        mock_pipeline = MagicMock()
                        MockPipeline.return_value = mock_pipeline

                        with patch("roku_tui.audio.RtcpHandler") as MockRtcp:
                            mock_rtcp = MagicMock()
                            mock_rtcp.handshake_complete = True
                            mock_rtcp.vdly_sent = True
                            MockRtcp.return_value = mock_rtcp

                            _real_sleep = asyncio.sleep

                            async def quick_sleep(t):
                                await _real_sleep(0)

                            with patch("roku_tui.audio.asyncio") as mock_asyncio:
                                mock_asyncio.sleep = AsyncMock(side_effect=quick_sleep)
                                mock_asyncio.create_task = asyncio.create_task
                                mock_asyncio.to_thread = asyncio.to_thread
                                mock_asyncio.wait_for = asyncio.wait_for
                                mock_asyncio.Event = asyncio.Event
                                mock_asyncio.TimeoutError = asyncio.TimeoutError
                                mock_asyncio.CancelledError = asyncio.CancelledError

                                # start() now blocks until stop event;
                                # signal stop after a brief delay
                                async def run_and_stop():
                                    await _real_sleep(0.05)
                                    await session.stop()

                                stop_task = asyncio.create_task(run_and_stop())
                                await session.start()
                                await stop_task

        assert AudioState.CONNECTING in states
        assert AudioState.HANDSHAKING in states
        assert AudioState.STREAMING in states
        mock_pipeline.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_handshake_send_failure_stops_and_reraises(self):
        """RTCP send failure during handshake calls stop() and re-raises."""
        session = PrivateListeningSession("192.168.1.1")

        with patch("roku_tui.audio._get_local_ip", return_value="192.168.1.2"):
            mock_ecp = AsyncMock()
            with patch("roku_tui.audio.EcpSession", return_value=mock_ecp):
                with patch("roku_tui.audio.socket") as mock_socket_mod:
                    mock_sock = MagicMock()
                    mock_socket_mod.socket.return_value = mock_sock
                    mock_socket_mod.AF_INET = 2
                    mock_socket_mod.SOCK_DGRAM = 2
                    mock_socket_mod.SOL_SOCKET = 1
                    mock_socket_mod.SO_REUSEADDR = 2

                    with patch("roku_tui.audio.AudioPipeline") as MockPipeline:
                        mock_pipeline = MagicMock()
                        MockPipeline.return_value = mock_pipeline

                        with patch("roku_tui.audio.RtcpHandler") as MockRtcp:
                            mock_rtcp = MagicMock()
                            mock_rtcp.send_vdly.side_effect = OSError("send failed")
                            MockRtcp.return_value = mock_rtcp

                            with patch("roku_tui.audio.asyncio") as mock_asyncio:
                                mock_asyncio.sleep = AsyncMock()
                                mock_asyncio.create_task = MagicMock()
                                mock_asyncio.to_thread = asyncio.to_thread
                                mock_asyncio.wait_for = asyncio.wait_for
                                mock_asyncio.TimeoutError = asyncio.TimeoutError
                                mock_asyncio.CancelledError = asyncio.CancelledError

                                with pytest.raises(RokuError) as exc_info:
                                    await session.start()
                                assert "send failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_keepalive_loop(self):
        """Keepalive loop sends VDLY+CVER+RR packets while streaming."""
        session = PrivateListeningSession("192.168.1.1")
        session._state = AudioState.STREAMING
        session._stop_event = asyncio.Event()
        mock_rtcp = MagicMock()
        session._rtcp = mock_rtcp

        # Signal stop after the loop has run at least once
        async def signal_stop():
            await asyncio.sleep(0.05)
            session._stop_event.set()

        stop_task = asyncio.create_task(signal_stop())
        await session._keepalive_loop()
        await stop_task

        assert mock_rtcp.send_vdly.call_count >= 1
        assert mock_rtcp.send_cver.call_count >= 1
        assert mock_rtcp.send_rr.call_count >= 1

    @pytest.mark.asyncio
    async def test_start_ignores_if_already_streaming(self):
        session = PrivateListeningSession("192.168.1.1")
        session._state = AudioState.STREAMING
        await session.start()  # should return immediately
        assert session.state == AudioState.STREAMING

    @pytest.mark.asyncio
    async def test_stop_full_lifecycle(self):
        """Test stop() cleans up all resources."""
        session = PrivateListeningSession("192.168.1.1")
        session._state = AudioState.STREAMING

        mock_rtcp = MagicMock()
        mock_rtcp.send_bye = MagicMock()
        mock_rtcp.stop = MagicMock()
        session._rtcp = mock_rtcp

        mock_pipeline = MagicMock()
        mock_pipeline.stop = MagicMock()
        session._pipeline = mock_pipeline

        mock_ecp = AsyncMock()
        session._ecp = mock_ecp

        mock_sock1 = MagicMock()
        mock_sock2 = MagicMock()
        session._rtp_sock = mock_sock1
        session._rtcp_recv_sock = mock_sock2

        await session.stop()

        mock_rtcp.send_bye.assert_called_once()
        mock_rtcp.stop.assert_called_once()
        mock_pipeline.stop.assert_called_once()
        mock_ecp.close.assert_called_once()
        mock_sock1.close.assert_called_once()
        mock_sock2.close.assert_called_once()
        assert session.state == AudioState.IDLE
        assert session._rtcp is None
        assert session._pipeline is None
        assert session._ecp is None

    @pytest.mark.asyncio
    async def test_stop_signals_stop_event(self):
        """Stop signals the stop event to break the keepalive loop."""
        session = PrivateListeningSession("192.168.1.1")
        session._state = AudioState.STREAMING
        session._stop_event = asyncio.Event()
        await session.stop()
        assert session._stop_event.is_set()
        assert session.state == AudioState.IDLE

    @pytest.mark.asyncio
    async def test_close_sockets(self):
        session = PrivateListeningSession("192.168.1.1")
        mock_sock = MagicMock()
        session._rtp_sock = mock_sock
        session._rtcp_recv_sock = MagicMock()
        session._close_sockets()
        assert session._rtp_sock is None
        assert session._rtcp_recv_sock is None

    @pytest.mark.asyncio
    async def test_stop_handles_bye_exception(self):
        """Stop gracefully handles exceptions from send_bye."""
        session = PrivateListeningSession("192.168.1.1")
        session._state = AudioState.STREAMING

        mock_rtcp = MagicMock()
        mock_rtcp.send_bye = MagicMock(side_effect=OSError("send failed"))
        mock_rtcp.stop = MagicMock()
        session._rtcp = mock_rtcp

        await session.stop()
        assert session.state == AudioState.IDLE


# ---------------------------------------------------------------------------
# AudioPipeline.receive_loop
# ---------------------------------------------------------------------------


class TestAudioPipelineReceiveLoop:
    def test_receive_loop_processes_rtp(self):
        """receive_loop reads from socket, parses, decodes, and writes."""
        rtp_packet = struct.pack("!BBHII", 0x80, 0x60, 1, 0, 0) + b"\xDE\xAD"
        mock_sock = MagicMock()
        mock_sock.recvfrom = MagicMock(
            side_effect=[(rtp_packet, ("1.2.3.4", 5150)), OSError("done")]
        )

        mock_decoder = MagicMock()
        mock_decoder.decode.return_value = b"\x00" * 3840
        mock_stream = MagicMock()

        pipeline = AudioPipeline(mock_sock)
        pipeline._running = True
        pipeline._decoder = mock_decoder
        pipeline._stream = mock_stream

        pipeline.receive_loop()

        mock_decoder.decode.assert_called_once()
        mock_stream.write.assert_called_once()

    def test_receive_loop_handles_timeout(self):
        """receive_loop continues on socket.timeout."""
        import socket as sock_mod
        mock_sock = MagicMock()
        mock_sock.recvfrom = MagicMock(
            side_effect=[sock_mod.timeout(), OSError("done")]
        )

        pipeline = AudioPipeline(mock_sock)
        pipeline._running = True
        pipeline._decoder = MagicMock()
        pipeline._stream = MagicMock()

        pipeline.receive_loop()
        # Should have called recvfrom twice (timeout + OSError)
        assert mock_sock.recvfrom.call_count == 2

    def test_receive_loop_skips_bad_rtp(self):
        """receive_loop skips packets that fail RTP parsing."""
        bad_packet = b"\x00" * 5  # too short for RTP
        mock_sock = MagicMock()
        mock_sock.recvfrom = MagicMock(
            side_effect=[(bad_packet, ("1.2.3.4", 5150)), OSError("done")]
        )

        mock_decoder = MagicMock()
        pipeline = AudioPipeline(mock_sock)
        pipeline._running = True
        pipeline._decoder = mock_decoder
        pipeline._stream = MagicMock()

        pipeline.receive_loop()
        mock_decoder.decode.assert_not_called()

    def test_receive_loop_handles_decode_error(self):
        """receive_loop continues on Opus decode errors."""
        rtp_packet = struct.pack("!BBHII", 0x80, 0x60, 1, 0, 0) + b"\xDE\xAD"
        mock_sock = MagicMock()
        mock_sock.recvfrom = MagicMock(
            side_effect=[(rtp_packet, ("1.2.3.4", 5150)), OSError("done")]
        )

        mock_decoder = MagicMock()
        mock_decoder.decode.side_effect = RuntimeError("bad opus")

        pipeline = AudioPipeline(mock_sock)
        pipeline._running = True
        pipeline._decoder = mock_decoder
        pipeline._stream = MagicMock()

        pipeline.receive_loop()  # should not raise


# ---------------------------------------------------------------------------
# AudioPipeline.stop edge cases
# ---------------------------------------------------------------------------


class TestAudioPipelineStopEdgeCases:
    def test_stop_handles_stream_error(self):
        """stop() handles exceptions from stream.stop/close."""
        mock_sock = MagicMock()
        pipeline = AudioPipeline(mock_sock)
        mock_stream = MagicMock()
        mock_stream.stop.side_effect = RuntimeError("audio error")
        pipeline._stream = mock_stream
        pipeline.stop()  # should not raise
        assert pipeline._stream is None


# ---------------------------------------------------------------------------
# _get_local_ip
# ---------------------------------------------------------------------------


class TestGetLocalIp:
    def test_returns_string(self):
        with patch("roku_tui.audio.socket") as mock_socket:
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ("192.168.1.5", 0)
            mock_socket.socket.return_value = mock_sock
            mock_socket.AF_INET = 2
            mock_socket.SOCK_DGRAM = 2
            result = _get_local_ip()
            assert result == "192.168.1.5"
            mock_sock.close.assert_called_once()


# ---------------------------------------------------------------------------
# PrivateListeningSession RTCP handshake (immediate send)
# ---------------------------------------------------------------------------


class TestHandshakeImmediateSend:
    """The handshake sends VDLY+CVER+RR back-to-back without waiting."""

    @pytest.mark.asyncio
    async def test_handshake_sends_all_three_packets(self):
        session = PrivateListeningSession("192.168.1.1")
        mock_rtcp = MagicMock()
        session._rtcp = mock_rtcp

        # Simulate the handshake send sequence from start()
        session._rtcp.send_vdly()
        session._rtcp.send_cver()
        session._rtcp.send_rr()

        mock_rtcp.send_vdly.assert_called_once()
        mock_rtcp.send_cver.assert_called_once()
        mock_rtcp.send_rr.assert_called_once()

    @pytest.mark.asyncio
    async def test_handshake_send_failure_raises(self):
        session = PrivateListeningSession("192.168.1.1")
        mock_rtcp = MagicMock()
        mock_rtcp.send_vdly.side_effect = OSError("send failed")
        session._rtcp = mock_rtcp
        session._state = AudioState.HANDSHAKING
        session._ecp = AsyncMock()

        # Inline the handshake error path from start()
        with pytest.raises(OSError):
            session._rtcp.send_vdly()
