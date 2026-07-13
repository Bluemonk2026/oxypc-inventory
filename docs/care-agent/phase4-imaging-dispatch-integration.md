# Care Agent Phase 4 — Imaging & Dispatch Gate Integration (scoped plan, not built)

Not implemented in this pass — it depends on the physical imaging/QC bench
workflow, which is Deshwal/OxyPC operational process, not something to wire
up without watching how imaging actually happens on the floor first.

## Goal (spec section 16)

Make "unit has an active Care Agent pairing" a checked precondition before a
device can be marked dispatch-ready — with a documented, audited exception
path for units that legitimately skip it (corporate no-software policy,
non-Windows device, as-is sale).

## What already exists to build on

- `routers/dispatch.py` — dispatch request/approve flow (`create_dispatch_request`,
  `approve_dispatch`). This is the natural gate point.
- `POST /care/internal/pairings` (`routers/care_internal.py:25`) — already
  live, staff-authed, generates the one-time provisioning secret for a
  specific device. This is the call the imaging step needs to make.
- `POST /care/internal/pairings/{id}/revoke` — already live, for the return/
  exchange/buyback revocation path (spec section 9.6).

## Steps (when this is picked up)

1. Add a `dispatch_exceptions` table (or a JSON column on `Device`) recording:
   device_id, reason (enum: corporate_no_software, non_windows, clean_os_request,
   as_is_sale, temporary_technical), approver, approved_at, expires_at,
   notes. Follow the project's schema-first rule — this is a new table,
   route it through `docs/schema.dbml` first.
2. In `approve_dispatch` (`routers/dispatch.py:235`), before allowing the
   status transition, check: does this device have an active
   `CareDevicePairing` with `paired_at` set (agent redeemed its token), OR a
   live `dispatch_exceptions` row? If neither, block with a clear error
   telling staff to either run imaging-time provisioning or record an
   exception.
3. Add a "Provision Care Agent" action on the device/IQC screen that calls
   `POST /care/internal/pairings` and displays the one-time token as a QR
   code or copyable string for the imaging technician to feed into the
   agent installer's first-run prompt (see `care_agent_windows/README.md`
   "Local dev testing" section for how a token gets redeemed today, manually).
4. Add a heartbeat check: if a unit was provisioned but never shows
   `paired_at` set after N hours (agent never phoned home), flag it in the
   dispatch queue rather than silently letting it ship un-paired.
5. Write the reimage/clone-resistance test called out in spec section 22 —
   image the same base Windows image onto two devices, confirm the second
   one's agent fails to redeem the first one's already-used token and
   requires a fresh provisioning call.

## Why this wasn't built now

No agreed imaging/QC bench workflow, no dispatch exception UI mockup, and no
customer devices to test the reimage/clone-resistance scenario against. This
is exactly the kind of "needs real operating data" work the spec's own
Final Implementation Principle (section 25) says to defer.
