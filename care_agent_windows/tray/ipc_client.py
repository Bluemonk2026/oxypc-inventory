"""Named-pipe client used by the tray app. This is the ONLY way the tray
talks to the service — it never opens its own network connection, never
touches DPAPI, never reads the credential file. If this module can't reach
the service, the tray shows a "service unavailable" state, nothing more.
"""
import uuid

try:
    import win32file
    import pywintypes
except ImportError:  # pragma: no cover
    win32file = pywintypes = None

from common.ipc_protocol import PIPE_NAME, encode_request, decode_response, IPCError

CONNECT_TIMEOUT_MS = 3000


class IPCClientError(Exception):
    pass


def call(command: str, params: dict | None = None) -> dict:
    if win32file is None:
        raise IPCClientError("pywin32 not available — cannot reach the service on this host")
    request_id = str(uuid.uuid4())
    try:
        handle = win32file.CreateFile(
            PIPE_NAME, win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None,
        )
    except pywintypes.error as e:
        raise IPCClientError(f"Care Agent service is not running or unreachable: {e}")

    try:
        req = encode_request(command, params, request_id)
        win32file.WriteFile(handle, req)
        _, raw = win32file.ReadFile(handle, 65536)
    except (pywintypes.error, IPCError) as e:
        raise IPCClientError(f"IPC call failed: {e}")
    finally:
        win32file.CloseHandle(handle)

    resp = decode_response(raw)
    if not resp.get("success"):
        err = resp.get("error") or {}
        raise IPCClientError(err.get("message", "Request failed"))
    return resp.get("data", {})
