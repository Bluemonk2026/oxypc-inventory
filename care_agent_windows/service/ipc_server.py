"""Named-pipe IPC server the tray app talks to. Dispatch table only contains
handlers for commands in common.ipc_protocol.ALLOWED_COMMANDS — there is no
generic "run this" handler, so a compromised or modified tray binary still
can't ask the service for anything beyond this fixed menu.
"""
import logging
import threading

try:
    import win32pipe
    import win32file
    import pywintypes
except ImportError:  # pragma: no cover
    win32pipe = win32file = pywintypes = None

from common.ipc_protocol import (
    PIPE_NAME, ALLOWED_COMMANDS, ALLOWED_DIAGNOSTIC_PROFILES,
    IPCError, decode_request, encode_response,
)

log = logging.getLogger("care_agent.ipc_server")


class IPCServer:
    def __init__(self, agent_state):
        """agent_state exposes: api_client, credential, offline_queue,
        run_diagnostics(profile), get_cached(key), refresh(key)."""
        self.state = agent_state
        self._stop = threading.Event()
        self._handlers = {
            "get_agent_status": self._h_get_agent_status,
            "get_device_summary": self._h_get_device_summary,
            "get_warranty": self._h_get_warranty,
            "get_offers": self._h_get_offers,
            "get_tickets": self._h_get_tickets,
            "get_ticket": self._h_get_ticket,
            "run_diagnostic_profile": self._h_run_diagnostic_profile,
            "submit_ticket": self._h_submit_ticket,
            "get_ticket_status": self._h_get_ticket_status,
            "refresh_warranty": self._h_refresh_warranty,
            "refresh_offers": self._h_refresh_offers,
            "retry_pending_operations": self._h_retry_pending,
        }
        assert set(self._handlers) == ALLOWED_COMMANDS, "IPC handler table must match the allowlist exactly"

    def stop(self):
        self._stop.set()

    def serve_forever(self):
        if win32pipe is None:
            raise RuntimeError("pywin32 not available — cannot host the named pipe on this host")
        while not self._stop.is_set():
            pipe = win32pipe.CreateNamedPipe(
                PIPE_NAME,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1, 65536, 65536, 0, None,
            )
            try:
                win32pipe.ConnectNamedPipe(pipe, None)
                self._handle_client(pipe)
            except pywintypes.error as e:
                log.warning("IPC pipe error: %s", e)
            finally:
                win32file.CloseHandle(pipe)

    def _handle_client(self, pipe):
        try:
            _, raw = win32file.ReadFile(pipe, 65536)
        except pywintypes.error:
            return
        request_id = ""
        try:
            req = decode_request(raw)
            request_id = req.get("request_id", "")
            handler = self._handlers[req["command"]]
            data = handler(req.get("params") or {})
            resp = encode_response(True, data=data, request_id=request_id)
        except IPCError as e:
            resp = encode_response(False, error={"code": e.code, "message": e.message}, request_id=request_id)
        except Exception as e:  # unexpected — never leak internals to the tray
            log.exception("Unhandled IPC handler error")
            resp = encode_response(False, error={"code": "IPC_INTERNAL_ERROR", "message": "Internal error"},
                                   request_id=request_id)
        win32file.WriteFile(pipe, resp)

    # ── Handlers — each one only touches agent_state, never the raw request ──

    def _h_get_agent_status(self, params):
        cred = self.state.credential
        return {
            "paired": cred is not None,
            "pending_queue_items": self.state.offline_queue.pending_count(),
        }

    def _h_get_device_summary(self, params):
        return self.state.get_cached("device")

    def _h_get_warranty(self, params):
        return self.state.get_cached("warranty")

    def _h_get_offers(self, params):
        return self.state.get_cached("offers")

    def _h_get_tickets(self, params):
        return self.state.get_cached("tickets")

    def _h_get_ticket(self, params):
        ticket_number = str(params.get("ticket_number", ""))[:20]
        if not ticket_number:
            raise IPCError("ticket_number is required", "IPC_MISSING_PARAM")
        return self.state.api_client.get_ticket(ticket_number)

    def _h_run_diagnostic_profile(self, params):
        profile = params.get("profile", "support_basic_v1")
        if profile not in ALLOWED_DIAGNOSTIC_PROFILES:
            raise IPCError(f"Unknown diagnostic profile: {profile}", "IPC_INVALID_PROFILE")
        return self.state.run_diagnostics(profile)

    def _h_submit_ticket(self, params):
        category = str(params.get("category", ""))[:50]
        description = str(params.get("description", ""))[:2000]
        contact_preference = str(params.get("customer_contact_preference", ""))[:20]
        diagnostics = params.get("diagnostics") if isinstance(params.get("diagnostics"), dict) else None
        if not category or not description:
            raise IPCError("category and description are required", "IPC_MISSING_PARAM")
        return self.state.submit_ticket(category, description, contact_preference, diagnostics)

    def _h_get_ticket_status(self, params):
        return self._h_get_ticket(params)

    def _h_refresh_warranty(self, params):
        return self.state.refresh("warranty")

    def _h_refresh_offers(self, params):
        return self.state.refresh("offers")

    def _h_retry_pending(self, params):
        return self.state.retry_pending_operations()
