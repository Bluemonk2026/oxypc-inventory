"""Local IPC contract between the tray application and the restricted
Windows service (spec section 8.3). Both sides import this module so the
allowlist can never drift apart.

Transport: a named pipe, one JSON object per message, newline-delimited.
Pipe name and framing live here so both processes agree without either
importing internals from the other.

The service must reject any command not in ALLOWED_COMMANDS before doing
anything else — this is the boundary that keeps the tray (running in the
logged-in user's session, no elevation) from ever being able to ask the
service to do something arbitrary.
"""
import json

PIPE_NAME = r"\\.\pipe\OxyPCCareAgent"

# Every command the tray is allowed to ask the service to perform. Nothing
# else is accepted — no arbitrary shell, no raw WMI query, no PowerShell.
ALLOWED_COMMANDS = frozenset({
    "get_agent_status",
    "get_device_summary",
    "get_warranty",
    "get_offers",
    "get_tickets",
    "get_ticket",
    "run_diagnostic_profile",
    "submit_ticket",
    "get_ticket_status",
    "refresh_warranty",
    "refresh_offers",
    "retry_pending_operations",
})

# Diagnostic profiles the service is willing to execute on request. New
# profiles require a code change here, not a client-supplied string.
ALLOWED_DIAGNOSTIC_PROFILES = frozenset({"support_basic_v1"})

MAX_MESSAGE_BYTES = 64 * 1024


class IPCError(Exception):
    def __init__(self, message: str, code: str = "IPC_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


def encode_request(command: str, params: dict | None = None, request_id: str = "") -> bytes:
    if command not in ALLOWED_COMMANDS:
        raise IPCError(f"Unknown IPC command: {command}", "IPC_UNKNOWN_COMMAND")
    payload = {"command": command, "params": params or {}, "request_id": request_id}
    data = (json.dumps(payload) + "\n").encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise IPCError("IPC request too large", "IPC_MESSAGE_TOO_LARGE")
    return data


def decode_request(raw: bytes) -> dict:
    if len(raw) > MAX_MESSAGE_BYTES:
        raise IPCError("IPC request too large", "IPC_MESSAGE_TOO_LARGE")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise IPCError(f"Malformed IPC request: {e}", "IPC_MALFORMED")
    command = payload.get("command")
    if command not in ALLOWED_COMMANDS:
        raise IPCError(f"Unknown or disallowed IPC command: {command}", "IPC_UNKNOWN_COMMAND")
    return payload


def encode_response(success: bool, data: dict | None = None, error: dict | None = None,
                    request_id: str = "") -> bytes:
    payload = {"success": success, "data": data or {}, "error": error, "request_id": request_id}
    return (json.dumps(payload) + "\n").encode("utf-8")


def decode_response(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))
