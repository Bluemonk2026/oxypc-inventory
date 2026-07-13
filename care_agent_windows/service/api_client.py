"""Thin client for /care/api/v1 (spec section 12). Owns the envelope
contract, idempotency keys, and version headers. Only the service talks to
the network — the tray app never does.
"""
import json
import platform
import uuid
from typing import Optional

import requests

AGENT_VERSION = "1.0.0"
SCHEMA_VERSION = "1"
REQUEST_TIMEOUT_SECONDS = 15


class ApiError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, status_code: int = 0):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


class CareApiClient:
    def __init__(self, base_url: str, device_token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.device_token = device_token
        self.session = requests.Session()

    def _headers(self, idempotency_key: str = "") -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Care-Agent-Version": AGENT_VERSION,
            "X-Care-Schema-Version": SCHEMA_VERSION,
            "X-Request-ID": str(uuid.uuid4()),
        }
        if self.device_token:
            headers["Authorization"] = f"Bearer {self.device_token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _call(self, method: str, path: str, json_body: dict = None, idempotency_key: str = "") -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.request(
                method, url, json=json_body, headers=self._headers(idempotency_key),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as e:
            raise ApiError("CARE_NETWORK_ERROR", str(e), retryable=True)

        try:
            envelope = resp.json()
        except json.JSONDecodeError:
            raise ApiError("CARE_BAD_RESPONSE", "Server returned a non-JSON response",
                          retryable=resp.status_code >= 500, status_code=resp.status_code)

        if not envelope.get("success"):
            err = envelope.get("error") or {}
            raise ApiError(err.get("code", "CARE_ERROR"), err.get("message", "Request failed"),
                          retryable=bool(err.get("retryable")), status_code=resp.status_code)
        return envelope.get("data", {})

    # ── Pairing (no device token yet) ──────────────────────────────────
    def pair(self, provisioning_token: str, bios_serial: str = "", manufacturer: str = "",
             model: str = "", motherboard_uuid: str = "") -> dict:
        return self._call("POST", "/care/api/v1/pair", {
            "provisioning_token": provisioning_token,
            "bios_serial": bios_serial, "manufacturer": manufacturer, "model": model,
            "motherboard_uuid": motherboard_uuid, "agent_version": AGENT_VERSION,
        })

    # ── Authenticated calls ─────────────────────────────────────────────
    def get_device(self) -> dict:
        return self._call("GET", "/care/api/v1/device")

    def get_warranty(self) -> dict:
        return self._call("GET", "/care/api/v1/warranty")

    def get_offers(self) -> dict:
        return self._call("GET", "/care/api/v1/offers")

    def get_tickets(self) -> dict:
        return self._call("GET", "/care/api/v1/tickets")

    def get_ticket(self, ticket_number: str) -> dict:
        return self._call("GET", f"/care/api/v1/tickets/{ticket_number}")

    def submit_ticket(self, category: str, description: str, contact_preference: str = "",
                      diagnostics: dict = None, idempotency_key: str = "") -> dict:
        body = {"category": category, "description": description,
                "customer_contact_preference": contact_preference}
        if diagnostics:
            body["diagnostics"] = diagnostics
        return self._call("POST", "/care/api/v1/tickets", body, idempotency_key=idempotency_key)

    def submit_diagnostics(self, diagnostics: dict, idempotency_key: str = "") -> dict:
        return self._call("POST", "/care/api/v1/diagnostics", {"diagnostics": diagnostics},
                          idempotency_key=idempotency_key)

    def heartbeat(self) -> dict:
        return self._call("POST", "/care/api/v1/heartbeat", {
            "agent_version": AGENT_VERSION, "platform": platform.platform(),
        })

    def rotate_token(self) -> dict:
        return self._call("POST", "/care/api/v1/token/rotate")

    def deactivate(self) -> dict:
        return self._call("POST", "/care/api/v1/deactivate")
