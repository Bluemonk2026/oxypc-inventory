"""OxyPC Care Agent — restricted Windows service (spec section 8.2).

Runs under the least-privileged viable service identity. Owns: first-run
provisioning, the device credential, the offline queue, diagnostics, API
communication, and the IPC server the tray talks to. Exposes no general
command-execution capability — every capability it grants the tray goes
through ipc_server.ALLOWED_COMMANDS.

Not yet done (flagged per spec section 25 — prove value before expanding):
code signing, MSI packaging, staged-rollout update client, Windows service
registration/install script. This file is runnable logic; turning it into a
signed, installable service is Phase 3b and needs a code-signing certificate
from Pankaj before it can ship to any real device.
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone

try:
    import win32serviceutil
    import win32service
    import win32event
except ImportError:  # pragma: no cover
    win32serviceutil = object  # allows the module to import on non-Windows dev hosts for linting
    win32service = win32event = None

from service.api_client import CareApiClient, ApiError
from service.credential_store import save_credential, load_credential, clear_credential
from service.offline_queue import OfflineQueue, QueueFullError
from service.diagnostics_collector import collect_profile
from service.ipc_server import IPCServer

API_BASE_URL = os.environ.get("OXYPC_CARE_API_BASE", "https://app.oxypc.com")
HEARTBEAT_INTERVAL_SECONDS = 300
CACHE_REFRESH_INTERVAL_SECONDS = 900

log = logging.getLogger("care_agent.service")


class AgentState:
    """Shared in-process state the IPC server hands requests off to. Not
    itself a Windows service concept — kept separate so it can be unit
    tested without pywin32 being installed."""

    def __init__(self):
        self.offline_queue = OfflineQueue()
        self.credential = load_credential()
        self.client = self._build_client()
        self._cache = {}
        self._cache_lock = threading.Lock()

    def _build_client(self) -> CareApiClient:
        token = self.credential["device_token"] if self.credential else None
        return CareApiClient(API_BASE_URL, device_token=token)

    # ── Provisioning ─────────────────────────────────────────────────────
    def provision(self, provisioning_token: str, bios_serial: str = "",
                  manufacturer: str = "", model: str = "") -> None:
        """Redeems a single-use provisioning secret written to a restricted
        machine-level location during imaging (spec section 4.1). On success,
        the device credential is DPAPI-persisted and the provisioning secret
        must be deleted by the caller (imaging tooling), never kept around."""
        data = self.client.pair(provisioning_token, bios_serial=bios_serial,
                                manufacturer=manufacturer, model=model)
        issued_at = datetime.now(timezone.utc).isoformat()
        save_credential(data["pairing_id"], data["device_token"], issued_at)
        self.credential = {"pairing_id": data["pairing_id"], "device_token": data["device_token"],
                           "issued_at": issued_at}
        self.client = self._build_client()

    # ── Cache (device/warranty/offers/tickets shown in the tray) ────────
    def get_cached(self, key: str) -> dict:
        with self._cache_lock:
            return self._cache.get(key, {})

    def refresh(self, key: str) -> dict:
        fetchers = {
            "device": self.client.get_device, "warranty": self.client.get_warranty,
            "offers": self.client.get_offers, "tickets": self.client.get_tickets,
        }
        fn = fetchers.get(key)
        if not fn:
            return {}
        try:
            data = fn()
        except ApiError as e:
            log.warning("refresh(%s) failed: %s", key, e)
            return self.get_cached(key)
        with self._cache_lock:
            self._cache[key] = data
        return data

    def refresh_all(self) -> None:
        for key in ("device", "warranty", "offers", "tickets"):
            self.refresh(key)

    # ── Diagnostics + tickets ────────────────────────────────────────────
    def run_diagnostics(self, profile: str) -> dict:
        return collect_profile(profile)

    def submit_ticket(self, category: str, description: str, contact_preference: str,
                      diagnostics: dict) -> dict:
        idempotency_key = f"ticket-{int(time.time() * 1000)}"
        payload = {"category": category, "description": description,
                  "contact_preference": contact_preference, "diagnostics": diagnostics}
        try:
            return self.client.submit_ticket(category, description, contact_preference,
                                             diagnostics, idempotency_key=idempotency_key)
        except ApiError as e:
            if e.retryable:
                try:
                    self.offline_queue.enqueue("ticket", payload, idempotency_key)
                    return {"queued": True, "reason": e.message}
                except QueueFullError as qe:
                    raise
            raise

    def retry_pending_operations(self) -> dict:
        retried, succeeded = 0, 0
        for item in self.offline_queue.due_items():
            retried += 1
            try:
                if item["kind"] == "ticket":
                    p = item["payload"]
                    self.client.submit_ticket(p["category"], p["description"],
                                             p.get("contact_preference", ""), p.get("diagnostics"),
                                             idempotency_key=item["idempotency_key"])
                elif item["kind"] == "diagnostic":
                    self.client.submit_diagnostics(item["payload"], idempotency_key=item["idempotency_key"])
                self.offline_queue.mark_success(item["id"])
                succeeded += 1
            except ApiError as e:
                self.offline_queue.mark_failure(item["id"], retryable=e.retryable)
        return {"retried": retried, "succeeded": succeeded,
                "still_pending": self.offline_queue.pending_count()}


class CareAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "OxyPCCareAgent"
    _svc_display_name_ = "OxyPC Care Agent"
    _svc_description_ = (
        "Post-sale warranty, diagnostics and support-ticket agent for OxyPC "
        "laptops. No remote control. See docs/care-agent for the privacy notice."
    )

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.state = AgentState()
        self.ipc_server = IPCServer(self.state)
        self._ipc_thread = None
        self._heartbeat_thread = None
        self._running = False

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._running = False
        self.ipc_server.stop()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        self._running = True
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        self._ipc_thread = threading.Thread(target=self.ipc_server.serve_forever, daemon=True)
        self._ipc_thread.start()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)

    def _heartbeat_loop(self):
        while self._running:
            if self.state.credential:
                try:
                    self.state.client.heartbeat()
                    self.state.refresh_all()
                    self.state.retry_pending_operations()
                except ApiError as e:
                    log.warning("heartbeat cycle failed: %s", e)
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(CareAgentService)
