"""Private listening audio pipeline: RTP receive, Opus decode, playback.

Orchestrates the full private listening session:
  - EcpSession handles WebSocket auth and audio request
  - RtcpHandler performs the RTCP handshake (VDLY/CVER/XDLY/NCLI)
  - AudioPipeline receives RTP, decodes Opus, writes PCM to speakers
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
from enum import Enum, auto

from .ecp_session import (
    CLOCK_RATE,
    RTCP_APP_PORT,
    RTCP_PORT,
    RTP_PORT,
    EcpSession,
    RtcpAppName,
    build_rtcp_app_packet,
    build_rtcp_bye_packet,
    build_rtcp_rr_packet,
    parse_rtcp_app_packet,
)
from .errors import ErrorCode, RokuError

log = logging.getLogger(__name__)

# Opus frame size: 20ms at 48kHz = 960 samples per channel
_OPUS_FRAME_SIZE = 960


class AudioState(Enum):
    """State machine for private listening sessions."""

    IDLE = auto()
    CONNECTING = auto()
    HANDSHAKING = auto()
    STREAMING = auto()
    ERROR = auto()
    STOPPING = auto()


def _get_local_ip() -> str:
    """Determine the local IP address reachable by devices on the LAN."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    finally:
        s.close()


def _parse_rtp_payload(data: bytes) -> bytes | None:
    """Strip the RTP header and return the Opus payload.

    Handles variable-length headers with CSRC entries and extensions.
    Returns None if the packet is malformed.
    """
    if len(data) < 12:
        return None

    byte0 = data[0]
    cc = byte0 & 0x0F          # CSRC count
    x = (byte0 >> 4) & 0x01    # extension bit

    offset = 12 + cc * 4       # skip fixed header + CSRC list

    if x:
        # Extension header: 2-byte profile + 2-byte length (in 32-bit words)
        if len(data) < offset + 4:
            return None
        ext_length = struct.unpack("!H", data[offset + 2:offset + 4])[0]
        offset += 4 + ext_length * 4

    if offset >= len(data):
        return None

    return data[offset:]


# --------------------------------------------------------------------------
# Audio Pipeline (data plane)
# --------------------------------------------------------------------------


class AudioPipeline:
    """RTP receiver with Opus decode and audio playback via sounddevice.

    Binds to UDP port 6970 to receive RTP packets from the Roku, strips the
    RTP header, decodes the Opus payload, and writes PCM to the default
    audio output device.
    """

    def __init__(self, rtp_sock: socket.socket) -> None:
        self._rtp_sock = rtp_sock
        self._running = False
        self._decoder = None
        self._stream = None

    def start(self) -> None:
        """Initialize Opus decoder and audio output stream.

        Raises:
            RokuError: E1015 if opuslib or sounddevice are not installed.
        """
        try:
            import opuslib
            import sounddevice as sd
        except ImportError:
            raise RokuError(
                ErrorCode.E1015,
                "Install audio deps: pip install roku-tui[audio]",
            )

        self._decoder = opuslib.Decoder(CLOCK_RATE, 2)
        self._stream = sd.RawOutputStream(
            samplerate=CLOCK_RATE,
            channels=2,
            dtype="int16",
        )
        self._stream.start()
        self._running = True

    def receive_loop(self) -> None:
        """Blocking loop: receive RTP, decode Opus, write PCM.

        Intended to run in a thread via asyncio.to_thread().
        """
        pkt_count = 0
        decode_count = 0
        err_count = 0
        while self._running:
            try:
                data, addr = self._rtp_sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            pkt_count += 1
            if pkt_count <= 3 or pkt_count % 500 == 0:
                log.debug(
                    "RTP pkt #%d: %d bytes from %s, header=%s",
                    pkt_count, len(data), addr, data[:12].hex(),
                )

            payload = _parse_rtp_payload(data)
            if payload is None:
                if pkt_count <= 10:
                    log.debug("RTP pkt #%d: payload parse returned None", pkt_count)
                continue

            try:
                pcm = self._decoder.decode(payload, _OPUS_FRAME_SIZE)
                self._stream.write(pcm)
                decode_count += 1
            except Exception as exc:
                err_count += 1
                if err_count <= 5:
                    log.warning("Opus decode error #%d: %s (payload %d bytes)", err_count, exc, len(payload))

        log.debug(
            "RTP loop exited: %d packets received, %d decoded, %d errors",
            pkt_count, decode_count, err_count,
        )

    def stop(self) -> None:
        """Stop the audio pipeline and release resources."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._decoder = None


# --------------------------------------------------------------------------
# RTCP Handler (control plane)
# --------------------------------------------------------------------------


class RtcpHandler:
    """Handles RTCP handshake and keepalive for private listening.

    Sends RTCP from the RTP socket (port 6970) to the Roku (port 5150),
    and receives RTCP responses on port 6971.
    """

    def __init__(
        self,
        roku_ip: str,
        send_sock: socket.socket,
        recv_sock: socket.socket,
    ) -> None:
        self.roku_ip = roku_ip
        self._send_sock = send_sock
        self._recv_sock = recv_sock
        self._running = False
        self.delay_ms = 200
        self.vdly_sent = False
        self.cver_sent = False
        self.xdly_received = False
        self.ncli_received = False

    @property
    def handshake_complete(self) -> bool:
        return (
            self.vdly_sent
            and self.cver_sent
            and self.xdly_received
            and self.ncli_received
        )

    def start(self) -> None:
        self._running = True

    def send_vdly(self, delay_ms: int | None = None) -> None:
        """Send VDLY (audio-video sync delay) APP packet."""
        if delay_ms is not None:
            self.delay_ms = delay_ms
        data = (self.delay_ms * 1000).to_bytes(4, "big")
        pkt = build_rtcp_app_packet(RtcpAppName.VDLY.value, data)
        self._send_sock.sendto(pkt, (self.roku_ip, RTCP_PORT))
        self.vdly_sent = True
        log.debug("Sent VDLY: %d ms to %s:%d", self.delay_ms, self.roku_ip, RTCP_PORT)

    def send_cver(self) -> None:
        """Send CVER (client version) APP packet."""
        pkt = build_rtcp_app_packet(RtcpAppName.CVER.value, b"0002")
        self._send_sock.sendto(pkt, (self.roku_ip, RTCP_PORT))
        self.cver_sent = True
        log.debug("Sent CVER to %s:%d", self.roku_ip, RTCP_PORT)

    def send_bye(self) -> None:
        """Send RTCP BYE to end the session."""
        pkt = build_rtcp_bye_packet()
        self._send_sock.sendto(pkt, (self.roku_ip, RTCP_PORT))
        log.debug("Sent BYE")

    def send_rr(self) -> None:
        """Send a minimal RTCP RR for keepalive."""
        pkt = build_rtcp_rr_packet()
        self._send_sock.sendto(pkt, (self.roku_ip, RTCP_PORT))

    def receive_loop(self) -> None:
        """Blocking loop: receive and process RTCP from Roku on port 6971.

        Intended to run in a thread via asyncio.to_thread().
        """
        while self._running:
            try:
                data, _ = self._recv_sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            result = parse_rtcp_app_packet(data)
            if result is None:
                continue

            name, app_data = result
            if name == RtcpAppName.XDLY.value:
                received_delay = int.from_bytes(app_data, "big") // 1000
                if received_delay == self.delay_ms:
                    self.xdly_received = True
                else:
                    # Roku wants a different delay; re-send VDLY
                    self.delay_ms = received_delay
                    self.vdly_sent = False
                log.debug("Received XDLY: %d ms", received_delay)
            elif name == RtcpAppName.NCLI.value:
                self.ncli_received = True
                log.debug("Received NCLI")

    def stop(self) -> None:
        self._running = False


# --------------------------------------------------------------------------
# Session Orchestrator
# --------------------------------------------------------------------------


class PrivateListeningSession:
    """Orchestrates EcpSession + RTCP + AudioPipeline for private listening.

    Usage::

        session = PrivateListeningSession("192.168.1.100")
        await session.start()   # connects, authenticates, streams
        ...
        await session.stop()    # sends BYE, cleans up
    """

    def __init__(
        self,
        roku_ip: str,
        roku_port: int = 8060,
        state_callback=None,
    ) -> None:
        self.roku_ip = roku_ip
        self.roku_port = roku_port
        self._state_callback = state_callback
        self._state = AudioState.IDLE
        self._ecp: EcpSession | None = None
        self._pipeline: AudioPipeline | None = None
        self._rtcp: RtcpHandler | None = None
        self._rtp_sock: socket.socket | None = None
        self._rtcp_recv_sock: socket.socket | None = None
        self._rtp_task: asyncio.Task | None = None
        self._rtcp_task: asyncio.Task | None = None
        self._ws_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    @property
    def state(self) -> AudioState:
        return self._state

    def _set_state(self, state: AudioState) -> None:
        self._state = state
        if self._state_callback:
            self._state_callback(state)

    async def start(self) -> None:
        """Start private listening: auth, handshake, stream, and keepalive.

        This method does NOT return until stop() is called (or an error
        occurs).  It runs the keepalive loop inline so the calling Textual
        worker stays alive, keeping all background tasks running.

        Raises:
            RokuError: On connection, auth, or pipeline errors.
        """
        if self._state not in (AudioState.IDLE, AudioState.ERROR):
            return

        self._stop_event = asyncio.Event()
        self._set_state(AudioState.CONNECTING)

        try:
            receiver_ip = _get_local_ip()
        except Exception as exc:
            self._set_state(AudioState.ERROR)
            raise RokuError(
                ErrorCode.E1011, f"Cannot determine local IP: {exc}"
            ) from exc

        # 1. WebSocket auth + audio request
        self._ecp = EcpSession(self.roku_ip, self.roku_port)
        try:
            await self._ecp.connect(receiver_ip)
        except RokuError:
            self._set_state(AudioState.ERROR)
            raise

        # 1b. Keep consuming WebSocket messages so the Roku doesn't
        # consider the client dead and drop the audio session.
        self._ws_task = asyncio.create_task(self._ecp.run_message_loop())

        # 2. Create UDP sockets
        log.debug("Binding RTP socket to 0.0.0.0:%d, RTCP to 0.0.0.0:%d", RTP_PORT, RTCP_APP_PORT)
        log.debug("Receiver IP: %s, Roku: %s:%d", receiver_ip, self.roku_ip, self.roku_port)
        try:
            self._rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._rtp_sock.bind(("0.0.0.0", RTP_PORT))
            self._rtp_sock.settimeout(1.0)

            self._rtcp_recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._rtcp_recv_sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
            )
            self._rtcp_recv_sock.bind(("0.0.0.0", RTCP_APP_PORT))
            self._rtcp_recv_sock.settimeout(0.5)
        except OSError as exc:
            await self._ecp.close()
            self._set_state(AudioState.ERROR)
            raise RokuError(
                ErrorCode.E1014, f"Cannot bind UDP sockets: {exc}"
            ) from exc

        # 3. Start audio pipeline
        self._pipeline = AudioPipeline(self._rtp_sock)
        try:
            self._pipeline.start()
        except RokuError:
            self._close_sockets()
            await self._ecp.close()
            self._set_state(AudioState.ERROR)
            raise

        # 4. Start RTCP handler
        self._set_state(AudioState.HANDSHAKING)
        self._rtcp = RtcpHandler(
            self.roku_ip, self._rtp_sock, self._rtcp_recv_sock
        )
        self._rtcp.start()

        # 5. Launch receive threads
        self._rtp_task = asyncio.create_task(
            asyncio.to_thread(self._pipeline.receive_loop)
        )
        self._rtcp_task = asyncio.create_task(
            asyncio.to_thread(self._rtcp.receive_loop)
        )

        # 6. Drive RTCP handshake: VDLY → wait for XDLY → CVER → RR
        try:
            await self._drive_handshake()
        except Exception as exc:
            await self.stop()
            self._set_state(AudioState.ERROR)
            if isinstance(exc, RokuError):
                raise
            raise RokuError(ErrorCode.E1011, str(exc)) from exc

        # 7. Run keepalive inline — this blocks until stop() signals.
        self._set_state(AudioState.STREAMING)
        log.debug("Entering keepalive loop")
        await self._keepalive_loop()

    async def _drive_handshake(self, timeout: float = 5.0) -> None:
        """Drive the RTCP handshake: VDLY → wait for XDLY → CVER → RR."""
        import time

        deadline = time.monotonic() + timeout

        # Step 1: Send VDLY
        self._rtcp.send_vdly()

        # Step 2: Wait for XDLY confirmation
        while not self._rtcp.xdly_received:
            if time.monotonic() > deadline:
                # Proceed anyway — some Roku firmwares may not send XDLY
                log.warning("XDLY not received within timeout, proceeding")
                break
            await asyncio.sleep(0.1)

        # Step 3: Send CVER + RR
        self._rtcp.send_cver()
        self._rtcp.send_rr()

        # Step 4: Brief wait for NCLI (optional, don't block on it)
        for _ in range(10):
            if self._rtcp.ncli_received:
                log.debug("NCLI received, handshake complete")
                break
            await asyncio.sleep(0.1)
        else:
            log.warning("NCLI not received, proceeding anyway")

    async def _keepalive_loop(self) -> None:
        """Periodically send RTCP to keep the session alive.

        Both reference implementations send more than just RR:
          - RPListening sends VDLY + CVER + RR every cycle
          - roku-audio-receiver sends compound RR + SDES via GStreamer at ~200ms
        We match RPListening's approach at 500ms intervals.

        Runs until the stop event is set or the session state changes.
        """
        try:
            while self._rtcp and self._state == AudioState.STREAMING:
                try:
                    self._rtcp.send_vdly()
                    self._rtcp.send_cver()
                    self._rtcp.send_rr()
                except OSError as exc:
                    log.warning("Keepalive send error: %s", exc)
                    break
                # Wait 500ms or until stop is signalled
                if self._stop_event:
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=0.5
                        )
                        break  # stop was signalled
                    except asyncio.TimeoutError:
                        pass  # normal — send next keepalive
                else:
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        log.debug("Keepalive loop exited")

    async def stop(self) -> None:
        """Stop private listening and clean up all resources."""
        if self._state == AudioState.IDLE:
            return

        self._set_state(AudioState.STOPPING)

        # Signal keepalive loop to exit
        if self._stop_event:
            self._stop_event.set()

        # Send BYE
        if self._rtcp:
            try:
                self._rtcp.send_bye()
            except Exception:
                pass
            self._rtcp.stop()
            self._rtcp = None

        # Stop audio pipeline
        if self._pipeline:
            self._pipeline.stop()
            self._pipeline = None

        # Close sockets (unblocks receive threads)
        self._close_sockets()

        # Wait for threads to finish
        for task in (self._rtp_task, self._rtcp_task):
            if task:
                try:
                    await asyncio.wait_for(task, timeout=3.0)
                except (asyncio.TimeoutError, Exception):
                    pass
        self._rtp_task = None
        self._rtcp_task = None

        # Cancel WebSocket consumer and close
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except (asyncio.CancelledError, Exception):
                pass
            self._ws_task = None
        if self._ecp:
            await self._ecp.close()
            self._ecp = None

        self._set_state(AudioState.IDLE)

    def _close_sockets(self) -> None:
        for sock in (self._rtp_sock, self._rtcp_recv_sock):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self._rtp_sock = None
        self._rtcp_recv_sock = None
