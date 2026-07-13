# OxyPC Care Agent — Windows Service + Tray (Phase 3, software-only)

Source for the restricted Windows service and customer-facing tray app
described in the Care Agent master spec (sections 8, 11, 13, 14). This is
runnable Python source, not a shipped product — see "Not done yet" below
before anyone treats this as installable.

## Layout

```
common/
  ipc_protocol.py        Named-pipe framing + command allowlist (both sides import this)
  diagnostics_schema.py   Field registry, mirrors services/care_service.py's allowlist
service/
  care_agent_service.py   Windows service entry point (win32serviceutil)
  api_client.py           /care/api/v1 HTTP client, envelope + idempotency handling
  credential_store.py     Machine-bound DPAPI storage for the device token
  offline_queue.py         Encrypted local queue, retry/backoff, dead-letter
  diagnostics_collector.py WMI/Event Log collectors, allowlist-only output
  ipc_server.py            Named-pipe server, dispatch table == the allowlist
tray/
  tray_app.py              pystray tray icon + menu (warranty, get support, tickets, offers)
  ipc_client.py            Named-pipe client — the tray's ONLY channel to the service
```

## What this pass delivers

- The full local IPC contract (spec 8.3), enforced identically on both ends
  via a shared allowlist — not just documented, structurally impossible to
  bypass without editing `common/ipc_protocol.py` on both sides.
- Machine-bound DPAPI credential storage (spec 8.4/11.2) — the tray process
  never has code that can read the credential file at all.
- An offline queue with the spec's exact defaults (7-day retention, 10
  pending tickets, 10 pending diagnostics, exponential backoff + jitter,
  dead-letter after repeated failure).
- A diagnostics collector that can only ever return fields present in
  `common/diagnostics_schema.DIAGNOSTIC_FIELD_REGISTRY` — there is no code
  path that forwards an arbitrary WMI/Event Log value to the server.
- An API client matching the section 12 envelope/error contract, including
  idempotency keys on ticket submission.
- A tray app that shows the diagnostic disclosure and requires explicit
  consent before running diagnostics, per spec section 4.3 / 17.4.

## Not done yet — do not ship without these

1. **Code signing.** Nothing here is signed. Per spec section 17.5, an
   unsigned installer/service/update package must never go to a production
   device. Needs a code-signing certificate — that's Pankaj's call, not
   something I can generate.
2. **Installer / MSI / service registration script.** There is no
   `install_service.bat` or MSI here yet — only the service class and
   `if __name__ == "__main__": win32serviceutil.HandleCommandLine(...)`,
   which supports `python care_agent_service.py install|start|stop|remove`
   for manual dev-machine testing only.
3. **Update framework** (spec section 18 — signed manifest, staged rollout,
   kill switch). Not built. Do not deploy this to real customer devices
   without an update path, or a bad build can't be recovered from remotely.
4. **Uninstall script** removing the DPAPI credential/queue files and
   deregistering the service cleanly (spec 8.6). `credential_store.clear_credential()`
   and manual `net stop`/`sc delete` exist as building blocks; there's no
   single uninstall entry point yet.
5. **Real hardware validation.** Collectors were written against the
   documented WMI/Event Log APIs but have not been run against the range of
   OEM firmware OxyPC actually images (spec 22, "diagnostic tests" —
   representative-device accuracy check still outstanding).
6. **Imaging-time integration** — wiring this into the actual imaging/QC
   step so a provisioning token gets generated and redeemed automatically.
   That's Phase 4 (see the separate scoped plan).

## Local dev testing (no signing needed)

```
pip install -r requirements.txt
cd care_agent_windows
python service\care_agent_service.py install
python service\care_agent_service.py start
python tray\tray_app.py
```

Run `python service\care_agent_service.py stop` / `remove` to tear down.
The service needs a paired device credential to do anything useful — until
imaging integration exists (Phase 4), pairing has to be triggered manually
by calling `AgentState.provision(...)` with a token issued via
`POST /care/internal/pairings` (staff-only, already live).
