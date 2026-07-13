# Care Agent Phase 6 — Pilot & Hardening (scoped plan, not built)

Not implemented in this pass — a pilot needs real customer devices, real
pilot dealers/customers willing to opt in, and at least two support agents
observing for four weeks (spec section 20, Phase 6). None of that can be
simulated in this session.

## Preconditions before a pilot can start

1. Phase 4 (imaging/dispatch integration) is live so pilot units get
   provisioned as part of normal dispatch, not a manual side-process.
2. Phase 3's Windows agent is code-signed and packaged (see
   `care_agent_windows/README.md` "Not done yet" — items 1–4). Nothing
   unsigned goes on a real customer laptop.
3. `routers/care_admin.py` (Phase 2, live) has had at least a few real staff
   run through the ticket queue on internal test devices first.
4. 25–50 candidate devices identified — multiple brands/models, per spec
   section 20.

## Acceptance gates to check at the end of the pilot (spec section 21 — already defined, just needs real data to score against)

Security: zero cross-device leakage, zero revoked-token access, zero
provisioning-token replay, zero secrets in logs.

Reliability: ≥98% pairing success, ≥99% ticket submission success, ≥98%
offline replay success, zero duplicate tickets from retries, ≥99.5%
crash-free sessions, ≥95% diagnostic completion.

Operational: 100% of tickets visible in the staff queue same-day, ≥99%
status sync accuracy, 100% warranty display accuracy on the tested sample,
≥15% target reduction in unnecessary pickups.

Customer-trust: antivirus false-positive rate below the agreed threshold, no
unresolved privacy complaints, uninstall/deactivate verified working.

## What to build when the pilot actually starts

- A pilot dashboard (staff-only) rolling up the acceptance-gate metrics
  above from `care_agent_events`, `care_audit_logs`, and ticket tables that
  already exist — this is mostly SQL against Phase 1/2 tables, not new
  schema.
- A kill-switch check (spec section 18) so a defective pilot build can be
  disabled server-side without needing to physically touch the 25–50
  devices.

## Why this wasn't built now

There is nothing to pilot yet — Phase 4 (auto-provisioning at dispatch) and
signed Phase 3 packaging are both prerequisites. Building pilot tooling
before those exist would be building for a program that can't run.
