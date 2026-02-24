"""SSDP-based discovery for Roku devices on the local network."""

from __future__ import annotations

import asyncio
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from .errors import ErrorCode, RokuError

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SEARCH_TARGET = "roku:ecp"

M_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"Host: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    'Man: "ssdp:discover"\r\n'
    f"ST: {SEARCH_TARGET}\r\n"
    "MX: 3\r\n"
    "\r\n"
)


@dataclass
class RokuDevice:
    """Represents a discovered Roku device on the network."""

    name: str
    model: str
    serial: str
    host: str
    port: int = 8060

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __str__(self) -> str:
        return f"{self.name} ({self.model})"


def _ssdp_search(timeout: float = 5.0) -> list[str]:
    """Send SSDP M-SEARCH and collect Roku device location URLs.

    This is a blocking call intended to run in a thread.
    """
    locations: list[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    except OSError as exc:
        raise RokuError(ErrorCode.E1010, f"Cannot create socket: {exc}") from exc

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        # Send the search request twice to account for UDP packet loss
        for _ in range(2):
            sock.sendto(M_SEARCH.encode(), (SSDP_ADDR, SSDP_PORT))

        seen: set[str] = set()
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                response = data.decode("utf-8", errors="replace")
                for line in response.split("\r\n"):
                    if line.lower().startswith("location:"):
                        loc = line.split(":", 1)[1].strip()
                        if loc not in seen:
                            seen.add(loc)
                            locations.append(loc)
            except socket.timeout:
                break
            except OSError:
                break
    except OSError as exc:
        raise RokuError(ErrorCode.E1001, str(exc)) from exc
    finally:
        sock.close()

    return locations


async def _fetch_device_info(client: httpx.AsyncClient, location: str) -> RokuDevice | None:
    """Fetch device info from a Roku device at the given location URL."""
    try:
        parsed = urlparse(location)
        host = parsed.hostname
        port = parsed.port or 8060

        resp = await client.get(f"http://{host}:{port}/query/device-info")
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        name = root.findtext("user-device-name") or root.findtext("model-name") or "Unknown Roku"
        model = root.findtext("model-name") or "Unknown"
        serial = root.findtext("serial-number") or "Unknown"

        return RokuDevice(name=name, model=model, serial=serial, host=host, port=port)
    except ET.ParseError:
        return None
    except httpx.HTTPError:
        return None
    except Exception:
        return None


async def connect_device(host: str, port: int = 8060) -> RokuDevice:
    """Connect to a Roku device by IP address and fetch its info.

    Args:
        host: IP address of the Roku device.
        port: ECP port (default 8060).

    Returns:
        A RokuDevice with name, model, and serial populated.

    Raises:
        RokuError: E1003 if connection fails, E1007 on timeout, E1009 on bad XML.
    """
    location = f"http://{host}:{port}/"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{host}:{port}/query/device-info")
            resp.raise_for_status()

            root = ET.fromstring(resp.text)
            name = root.findtext("user-device-name") or root.findtext("model-name") or "Unknown Roku"
            model = root.findtext("model-name") or "Unknown"
            serial = root.findtext("serial-number") or "Unknown"

            return RokuDevice(name=name, model=model, serial=serial, host=host, port=port)
    except ET.ParseError as exc:
        raise RokuError(ErrorCode.E1009, f"Invalid XML from {host}:{port}") from exc
    except httpx.TimeoutException as exc:
        raise RokuError(ErrorCode.E1007, f"Timeout connecting to {host}:{port}") from exc
    except httpx.HTTPError as exc:
        raise RokuError(ErrorCode.E1003, f"Cannot reach {host}:{port}: {exc}") from exc


async def discover_devices(timeout: float = 5.0) -> list[RokuDevice]:
    """Discover Roku devices on the local network.

    Performs SSDP multicast search, then queries each responding device
    for its name, model, and serial number.

    Raises:
        RokuError: E1001 if network discovery fails, E1010 for socket errors.
    """
    locations = await asyncio.to_thread(_ssdp_search, timeout)

    if not locations:
        return []

    devices: list[RokuDevice] = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        tasks = [_fetch_device_info(client, loc) for loc in locations]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, RokuDevice):
                devices.append(result)

    return devices
