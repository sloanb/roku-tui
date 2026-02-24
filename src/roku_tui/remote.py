"""Roku External Control Protocol (ECP) client."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from enum import Enum
from urllib.parse import quote

import httpx

from .discovery import RokuDevice
from .errors import ErrorCode, RokuError


class RokuKey(str, Enum):
    """Roku remote control key identifiers (ECP key names)."""

    HOME = "Home"
    REV = "Rev"
    FWD = "Fwd"
    PLAY = "Play"
    SELECT = "Select"
    LEFT = "Left"
    RIGHT = "Right"
    DOWN = "Down"
    UP = "Up"
    BACK = "Back"
    INSTANT_REPLAY = "InstantReplay"
    INFO = "Info"
    BACKSPACE = "Backspace"
    SEARCH = "Search"
    ENTER = "Enter"
    VOLUME_DOWN = "VolumeDown"
    VOLUME_UP = "VolumeUp"
    VOLUME_MUTE = "VolumeMute"
    POWER = "Power"
    POWER_OFF = "PowerOff"
    POWER_ON = "PowerOn"


class RokuRemote:
    """Async client for controlling a Roku device via ECP.

    Args:
        device: The RokuDevice to control.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, device: RokuDevice, timeout: float = 5.0):
        self.device = device
        self._client = httpx.AsyncClient(timeout=timeout)

    async def keypress(self, key: RokuKey) -> None:
        """Send a keypress command to the Roku device."""
        try:
            resp = await self._client.post(f"{self.device.base_url}/keypress/{key.value}")
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise RokuError(ErrorCode.E1007, f"Timeout sending {key.value}") from exc
        except httpx.ConnectError as exc:
            raise RokuError(ErrorCode.E1008, f"Cannot reach {self.device.host}") from exc
        except httpx.HTTPStatusError as exc:
            raise RokuError(
                ErrorCode.E1004, f"{key.value}: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RokuError(ErrorCode.E1004, str(exc)) from exc

    async def send_text(self, text: str) -> None:
        """Send a string of text to the Roku device, character by character."""
        for char in text:
            encoded = quote(char, safe="")
            try:
                resp = await self._client.post(
                    f"{self.device.base_url}/keypress/Lit_{encoded}"
                )
                resp.raise_for_status()
            except httpx.TimeoutException as exc:
                raise RokuError(ErrorCode.E1007, f"Timeout sending character '{char}'") from exc
            except httpx.HTTPError as exc:
                raise RokuError(ErrorCode.E1004, f"Failed to send character '{char}': {exc}") from exc

    async def get_device_info(self) -> dict[str, str | None]:
        """Retrieve device information from the Roku."""
        try:
            resp = await self._client.get(f"{self.device.base_url}/query/device-info")
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            return {child.tag: child.text for child in root}
        except httpx.TimeoutException as exc:
            raise RokuError(ErrorCode.E1007, "Timeout getting device info") from exc
        except httpx.ConnectError as exc:
            raise RokuError(ErrorCode.E1008, f"Cannot reach {self.device.host}") from exc
        except ET.ParseError as exc:
            raise RokuError(ErrorCode.E1009, "Invalid XML in device info response") from exc
        except httpx.HTTPError as exc:
            raise RokuError(ErrorCode.E1005, str(exc)) from exc

    async def get_apps(self) -> list[dict[str, str | None]]:
        """Retrieve the list of installed apps/channels."""
        try:
            resp = await self._client.get(f"{self.device.base_url}/query/apps")
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            return [
                {
                    "id": app.get("id"),
                    "name": app.text,
                    "type": app.get("type"),
                    "version": app.get("version"),
                }
                for app in root.findall("app")
            ]
        except httpx.TimeoutException as exc:
            raise RokuError(ErrorCode.E1007, "Timeout getting apps") from exc
        except httpx.ConnectError as exc:
            raise RokuError(ErrorCode.E1008, f"Cannot reach {self.device.host}") from exc
        except ET.ParseError as exc:
            raise RokuError(ErrorCode.E1009, "Invalid XML in apps response") from exc
        except httpx.HTTPError as exc:
            raise RokuError(ErrorCode.E1005, str(exc)) from exc

    async def launch_app(self, app_id: str) -> None:
        """Launch an installed app/channel by its ID."""
        try:
            resp = await self._client.post(f"{self.device.base_url}/launch/{app_id}")
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise RokuError(ErrorCode.E1007, f"Timeout launching app {app_id}") from exc
        except httpx.HTTPError as exc:
            raise RokuError(ErrorCode.E1004, f"Failed to launch app {app_id}: {exc}") from exc

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
