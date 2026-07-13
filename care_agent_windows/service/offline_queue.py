"""Offline queue for tickets/diagnostics submitted while the agent has no
connectivity (spec section 14). Persisted as DPAPI-encrypted JSON so a lost
or stolen laptop's local disk doesn't leak queued support content.

Defaults match spec section 14: 7-day retention, max 10 pending tickets, max
10 pending diagnostic snapshots, exponential backoff with jitter, dead-letter
after repeated failure so a single broken item can't block the queue forever.
"""
import json
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

try:
    import win32crypt
except ImportError:  # pragma: no cover
    win32crypt = None

QUEUE_DIR = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "OxyPC", "CareAgent"
)
QUEUE_FILE = os.path.join(QUEUE_DIR, "offline_queue.bin")
_QUEUE_ENTROPY = b"oxypc-care-agent-queue-v1"

MAX_RETENTION_DAYS = 7
MAX_PENDING_TICKETS = 10
MAX_PENDING_DIAGNOSTICS = 10
MAX_RETRY_ATTEMPTS = 8
BASE_BACKOFF_SECONDS = 30


class QueueFullError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encrypt(data: bytes) -> bytes:
    if win32crypt is None:
        return data  # non-Windows dev/test fallback — never used in production
    return win32crypt.CryptProtectData(data, "OxyPC Care Agent offline queue", _QUEUE_ENTROPY, None, None, 0)


def _decrypt(data: bytes) -> bytes:
    if win32crypt is None:
        return data
    _, plain = win32crypt.CryptUnprotectData(data, _QUEUE_ENTROPY, None, None, 0)
    return plain


class OfflineQueue:
    """Item shape: {id, kind ('ticket'|'diagnostic'), payload, idempotency_key,
    created_at, attempts, next_attempt_at, status ('pending'|'dead_letter')}"""

    def __init__(self):
        os.makedirs(QUEUE_DIR, exist_ok=True)
        self._items = self._load()
        self._prune_expired()

    def _load(self) -> list:
        if not os.path.exists(QUEUE_FILE):
            return []
        try:
            with open(QUEUE_FILE, "rb") as f:
                raw = f.read()
            return json.loads(_decrypt(raw).decode("utf-8"))
        except Exception:
            return []  # corrupted queue — fail safe by starting empty, don't crash the service

    def _save(self) -> None:
        data = json.dumps(self._items).encode("utf-8")
        tmp_path = QUEUE_FILE + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(_encrypt(data))
        os.replace(tmp_path, QUEUE_FILE)

    def _prune_expired(self) -> None:
        cutoff = _now() - timedelta(days=MAX_RETENTION_DAYS)
        before = len(self._items)
        self._items = [
            it for it in self._items
            if datetime.fromisoformat(it["created_at"]) > cutoff
        ]
        if len(self._items) != before:
            self._save()

    def _pending_count(self, kind: str) -> int:
        return sum(1 for it in self._items if it["kind"] == kind and it["status"] == "pending")

    def enqueue(self, kind: str, payload: dict, idempotency_key: str = "") -> str:
        limit = MAX_PENDING_TICKETS if kind == "ticket" else MAX_PENDING_DIAGNOSTICS
        if self._pending_count(kind) >= limit:
            raise QueueFullError(f"Offline queue full for '{kind}' (max {limit})")
        idempotency_key = idempotency_key or str(uuid.uuid4())
        # Duplicate suppression: same idempotency key already queued
        for it in self._items:
            if it["idempotency_key"] == idempotency_key:
                return it["id"]
        item_id = str(uuid.uuid4())
        self._items.append({
            "id": item_id, "kind": kind, "payload": payload,
            "idempotency_key": idempotency_key,
            "created_at": _now().isoformat(), "attempts": 0,
            "next_attempt_at": _now().isoformat(), "status": "pending",
        })
        self._save()
        return item_id

    def due_items(self) -> list:
        now = _now()
        return [it for it in self._items
                if it["status"] == "pending" and datetime.fromisoformat(it["next_attempt_at"]) <= now]

    def mark_success(self, item_id: str) -> None:
        self._items = [it for it in self._items if it["id"] != item_id]
        self._save()

    def mark_failure(self, item_id: str, retryable: bool) -> None:
        for it in self._items:
            if it["id"] != item_id:
                continue
            it["attempts"] += 1
            if not retryable or it["attempts"] >= MAX_RETRY_ATTEMPTS:
                it["status"] = "dead_letter"
            else:
                backoff = min(BASE_BACKOFF_SECONDS * (2 ** it["attempts"]), 3600)
                jitter = random.uniform(0, backoff * 0.2)
                it["next_attempt_at"] = (_now() + timedelta(seconds=backoff + jitter)).isoformat()
            break
        self._save()

    def pending_count(self) -> int:
        return sum(1 for it in self._items if it["status"] == "pending")

    def dead_letter_items(self) -> list:
        return [it for it in self._items if it["status"] == "dead_letter"]
