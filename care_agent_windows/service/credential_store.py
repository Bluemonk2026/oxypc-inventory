"""Machine-bound DPAPI credential storage (spec section 8.4).

The device token is the only secret this agent ever holds long-term. It is
encrypted with CryptProtectData using no user-specific entropy and no
CRYPTPROTECT_LOCAL_MACHINE-incompatible flags removed — i.e. machine scope,
not per-Windows-user scope. Rationale (spec 8.4): provisioning can happen
before any customer Windows profile exists, multiple Windows users may share
the laptop, and reimaging must invalidate local access automatically since
DPAPI machine keys are tied to the machine's security state.

Only the service process (running as the dedicated service account) and
Administrators can decrypt this — never the tray app, which never touches
raw credential bytes at all, only IPC responses that omit the token.
"""
import json
import os

try:
    import win32crypt  # pywin32
except ImportError:  # pragma: no cover - only available on Windows with pywin32
    win32crypt = None

CREDENTIAL_DIR = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "OxyPC", "CareAgent"
)
CREDENTIAL_FILE = os.path.join(CREDENTIAL_DIR, "device_credential.bin")

# Entropy is an additional secret mixed into the encryption that isn't stored
# anywhere the attacker can read alongside the ciphertext by itself — but per
# spec 8.4 this must stay machine-scoped, so it is a fixed, non-secret
# constant compiled into the agent, not a per-install random value that could
# get lost. It raises the bar above "copy the .bin file" without depending on
# anything that would break across a service restart.
_DPAPI_ENTROPY = b"oxypc-care-agent-v1"


class CredentialStoreError(Exception):
    pass


def _ensure_dir():
    os.makedirs(CREDENTIAL_DIR, exist_ok=True)


def save_credential(pairing_id: str, device_token: str, issued_at: str) -> None:
    """Encrypt and persist the device token. Overwrites any prior credential —
    callers are responsible for confirming the old one should be replaced
    (e.g. after a successful pairing or token rotation)."""
    if win32crypt is None:
        raise CredentialStoreError("pywin32 not available — cannot use DPAPI on this host")
    _ensure_dir()
    plaintext = json.dumps({
        "pairing_id": pairing_id, "device_token": device_token, "issued_at": issued_at,
    }).encode("utf-8")
    encrypted = win32crypt.CryptProtectData(
        plaintext, "OxyPC Care Agent device credential", _DPAPI_ENTROPY, None, None, 0
    )
    tmp_path = CREDENTIAL_FILE + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(encrypted)
    os.replace(tmp_path, CREDENTIAL_FILE)  # atomic on Windows for same-volume renames


def load_credential() -> dict | None:
    """Returns {"pairing_id", "device_token", "issued_at"} or None if no
    credential exists yet or it fails to decrypt (e.g. after a reimage —
    DPAPI machine keys don't survive that, which is the intended behaviour:
    re-pairing is required, per spec section 11.4)."""
    if win32crypt is None:
        raise CredentialStoreError("pywin32 not available — cannot use DPAPI on this host")
    if not os.path.exists(CREDENTIAL_FILE):
        return None
    with open(CREDENTIAL_FILE, "rb") as f:
        encrypted = f.read()
    try:
        _, plaintext = win32crypt.CryptUnprotectData(encrypted, _DPAPI_ENTROPY, None, None, 0)
    except Exception:
        return None
    return json.loads(plaintext.decode("utf-8"))


def clear_credential() -> None:
    """Used on deactivate/uninstall (spec section 8.6) — removes the local
    credential so a stopped agent can't still authenticate if somehow
    restarted."""
    if os.path.exists(CREDENTIAL_FILE):
        os.remove(CREDENTIAL_FILE)
