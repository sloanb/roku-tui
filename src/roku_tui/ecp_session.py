"""ECP-2 WebSocket session for Roku private listening.

Implements the reverse-engineered ECP-2 protocol used by the official Roku
mobile app for private listening. Protocol details sourced from:
  - roku-audio-receiver (github.com/alin23/roku-audio-receiver)
  - RPListening (github.com/runz0rd/RPListening)
"""

from __future__ import annotations

import hashlib
import json
import logging
import struct
from base64 import b64encode
from enum import Enum

from .errors import ErrorCode, RokuError

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Protocol constants
# --------------------------------------------------------------------------

RTP_PORT = 6970
RTCP_PORT = 5150
RTCP_APP_PORT = 6971
LATENCY = 97
CLOCK_RATE = 48000

# RTCP packet types (RFC 3550)
RTCP_RR = 201
RTCP_BYE = 203
RTCP_APP = 204

# --------------------------------------------------------------------------
# Auth key derivation
# --------------------------------------------------------------------------

_KEY = "95E610D0-7C29-44EF-FB0F-97F1FCE4C297"


def _char_transform(var1: int, var2: int) -> str:
    """Transform a hex character for auth key derivation.

    Rotates hex digits by a given offset, leaves non-hex characters unchanged.
    Reverse-engineered from the Roku mobile app.
    """
    if ord("0") <= var1 <= ord("9"):
        var3 = var1 - 48
    elif ord("A") <= var1 <= ord("F"):
        var3 = var1 - 65 + 10
    else:
        return chr(var1)

    var2 = (15 - var3 + var2) & 15
    if var2 < 10:
        var2 += 48
    else:
        var2 = var2 + 65 - 10

    return chr(var2)


_AUTH_KEY: bytes = "".join(_char_transform(ord(c), 9) for c in _KEY).encode()


def compute_auth_response(challenge: str) -> str:
    """Compute the auth response for an ECP-2 challenge.

    Returns base64(sha1(challenge + AUTH_KEY)).
    """
    digest = hashlib.sha1(challenge.encode() + _AUTH_KEY).digest()
    return b64encode(digest).decode()


# --------------------------------------------------------------------------
# RTCP packet building / parsing
# --------------------------------------------------------------------------


class RtcpAppName(str, Enum):
    """Named RTCP APP packet subtypes used in the private listening handshake."""

    VDLY = "VDLY"  # Audio-video sync delay
    XDLY = "XDLY"  # Cross-sync delay (response from Roku)
    CVER = "CVER"  # Client version
    NCLI = "NCLI"  # New client notification


def build_rtcp_app_packet(name: str, data: bytes, ssrc: int = 0) -> bytes:
    """Build an RTCP APP packet (PT=204).

    Layout (16 bytes):
      [0]    V=2, P=0, subtype=0
      [1]    PT=204
      [2-3]  length=3 (4 words total)
      [4-7]  SSRC
      [8-11] name (4 ASCII bytes)
      [12-15] application data
    """
    header = struct.pack("!BBH", 0x80, RTCP_APP, 3)
    ssrc_bytes = struct.pack("!I", ssrc)
    name_bytes = name.encode("ascii")[:4].ljust(4, b"\x00")
    app_data = data[:4].ljust(4, b"\x00")
    return header + ssrc_bytes + name_bytes + app_data


def build_rtcp_bye_packet(ssrc: int = 0) -> bytes:
    """Build an RTCP BYE packet (PT=203)."""
    # V=2, P=0, SC=1 | PT=203 | length=1
    header = struct.pack("!BBH", 0x81, RTCP_BYE, 1)
    ssrc_bytes = struct.pack("!I", ssrc)
    return header + ssrc_bytes


def build_rtcp_rr_packet(ssrc: int = 0) -> bytes:
    """Build an RTCP RR (Receiver Report) packet with one empty report block.

    Matches the 32-byte format used by RPListening:
      [0]    V=2, P=0, RC=1
      [1]    PT=201
      [2-3]  length=7 (8 words = 32 bytes)
      [4-7]  SSRC of sender
      [8-31] one 24-byte report block (zeroed)
    """
    # V=2, P=0, RC=1 | PT=201 | length=7
    header = struct.pack("!BBH", 0x81, RTCP_RR, 7)
    ssrc_bytes = struct.pack("!I", ssrc)
    report_block = b"\x00" * 24
    return header + ssrc_bytes + report_block


def parse_rtcp_app_packet(data: bytes) -> tuple[str, bytes] | None:
    """Parse an RTCP APP packet, returning (name, app_data) or None."""
    if len(data) < 16:
        return None
    pt = data[1]
    if pt != RTCP_APP:
        return None
    name = data[8:12].decode("ascii", errors="replace")
    app_data = data[12:16]
    return name, app_data


# --------------------------------------------------------------------------
# ECP-2 WebSocket session
# --------------------------------------------------------------------------


class EcpSession:
    """WebSocket-based ECP-2 session for Roku private listening control.

    Handles:
      1. WebSocket connection to ws://{ip}:8060/ecp-session
      2. Challenge-response authentication
      3. Sending set-audio-output to start the RTP stream
    """

    def __init__(self, roku_ip: str, roku_port: int = 8060) -> None:
        self.roku_ip = roku_ip
        self.roku_port = roku_port
        self._request_id = 0
        self._ws = None
        self._authenticated = False
        self._audio_requested = False

    async def connect(self, receiver_ip: str) -> None:
        """Connect, authenticate, and request audio streaming.

        Args:
            receiver_ip: Local IP address where the Roku should send RTP.

        Raises:
            RokuError: E1012 on WebSocket error, E1013 on auth failure,
                       E1015 if websockets not installed.
        """
        try:
            import websockets
        except ImportError:
            raise RokuError(
                ErrorCode.E1015,
                "Install audio deps: pip install roku-tui[audio]",
            )

        try:
            self._ws = await websockets.connect(
                f"ws://{self.roku_ip}:{self.roku_port}/ecp-session",
                origin="Android",
                subprotocols=["ecp-2"],
            )
        except Exception as exc:
            raise RokuError(ErrorCode.E1012, str(exc)) from exc

        try:
            async for message in self._ws:
                msg = json.loads(message)
                log.debug("ECP connect msg: %s", msg)

                if "param-challenge" in msg:
                    response = compute_auth_response(msg["param-challenge"])
                    await self._send({
                        "param-response": response,
                        "param-client-friendly-name": "Roku TUI",
                        "param-has-microphone": "false",
                        "param-microphone-sample-rates": "1600",
                        "request": "authenticate",
                    })

                elif msg.get("response") == "authenticate":
                    if msg.get("status") == "200":
                        self._authenticated = True
                        await self._send({
                            "param-devname": (
                                f"{receiver_ip}:{RTP_PORT}:{LATENCY}"
                                f":{CLOCK_RATE // 50}"
                            ),
                            "param-audio-output": "datagram",
                            "request": "set-audio-output",
                        })
                        self._audio_requested = True
                        # Don't return yet — wait for set-audio-output response
                    else:
                        raise RokuError(
                            ErrorCode.E1013,
                            f"Auth status: {msg.get('status')}",
                        )

                elif msg.get("response") == "set-audio-output":
                    if msg.get("status") == "200":
                        return  # Roku confirmed audio — ready for RTCP
                    else:
                        raise RokuError(
                            ErrorCode.E1011,
                            f"set-audio-output rejected: {msg.get('status')}",
                        )
        except RokuError:
            raise
        except Exception as exc:
            raise RokuError(ErrorCode.E1012, str(exc)) from exc

    async def _send(self, obj: dict) -> None:
        """Send a JSON message with auto-incrementing request-id."""
        self._request_id += 1
        obj["request-id"] = str(self._request_id)
        msg = json.dumps(obj)
        log.debug("ECP sending: %s", msg)
        await self._ws.send(msg)

    async def run_message_loop(self) -> None:
        """Consume WebSocket messages to keep the connection alive.

        The Roku sends pings and status messages over the WebSocket.
        If nothing reads them, the Roku considers the client dead and
        drops the audio session after ~5 seconds.  Run this as a
        background task for the lifetime of the private listening session.
        """
        if not self._ws:
            return
        try:
            async for message in self._ws:
                msg = json.loads(message)
                log.debug("ECP WS message: %s", msg)
        except Exception as exc:
            log.debug("ECP WS loop ended: %s", exc)

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._authenticated
