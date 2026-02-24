"""Error codes and exception types for Roku TUI.

Error Code Reference:
    E1001 - Network discovery failed (SSDP multicast issue)
    E1002 - No devices found on network
    E1003 - Device connection failed
    E1004 - Command send failed (keypress/launch)
    E1005 - Device info retrieval failed
    E1006 - Invalid device response
    E1007 - Network timeout
    E1008 - Device unreachable
    E1009 - Response parse error (malformed XML)
    E1010 - Socket error (low-level network issue)
"""

from enum import Enum


class ErrorCode(Enum):
    """Enumeration of all application error codes."""

    E1001 = ("E1001", "Network discovery failed", "Unable to perform SSDP discovery on the network")
    E1002 = ("E1002", "No devices found", "No Roku devices were found on the local network")
    E1003 = ("E1003", "Device connection failed", "Failed to establish connection to the Roku device")
    E1004 = ("E1004", "Command failed", "Failed to send command to the Roku device")
    E1005 = ("E1005", "Device info error", "Failed to retrieve device information")
    E1006 = ("E1006", "Invalid response", "Received an invalid response from the device")
    E1007 = ("E1007", "Network timeout", "Network operation timed out")
    E1008 = ("E1008", "Device unreachable", "The Roku device is not reachable on the network")
    E1009 = ("E1009", "Parse error", "Failed to parse device response data")
    E1010 = ("E1010", "Socket error", "Network socket operation failed")

    def __init__(self, code: str, message: str, description: str):
        self.code = code
        self.message = message
        self.description = description


class RokuError(Exception):
    """Base exception for all Roku TUI errors.

    Attributes:
        error_code: The ErrorCode enum member.
        detail: Optional additional context about the error.
    """

    def __init__(self, error_code: ErrorCode, detail: str = ""):
        self.error_code = error_code
        self.detail = detail
        msg = f"[{error_code.code}] {error_code.message}"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
