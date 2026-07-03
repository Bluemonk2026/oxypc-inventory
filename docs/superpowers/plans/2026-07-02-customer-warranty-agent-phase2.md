# Customer Warranty/Support Agent (Phase 2) — Scoping Spec

> Not yet built. Phase 1 (RMA capture + warranty-type-at-sale in the ERP) is being built separately. This is the plan for the follow-on desktop product.

**Goal:** A brand-new, customer-installed desktop EXE (separate codebase from OxyQC Standalone) that lets an end customer:
1. Log a support call against their device (serial number auto-detected or entered)
2. See their warranty status (pulled from OxyPC Inventory via API, using Phase 1's `warranty_expires_at`)
3. Request a remote session so the support team can diagnose/fix the issue

**Remote control decision:** Integrate an existing remote-access tool (e.g. RustDesk self-hosted, or AnyDesk/TeamViewer via their launch-URL/API) rather than building custom remote-control. The agent EXE triggers the chosen tool and reports the session ID back to OxyPC Inventory so support staff can look up "which customer session maps to which ticket."

## Open decisions before implementation (need Pankaj's input)
1. **Remote tool choice** — RustDesk (self-hosted, free, more setup) vs AnyDesk/TeamViewer (commercial, faster to integrate, per-seat licensing cost). Recommend RustDesk self-hosted given ITAD/BFSI clients' data-residency sensitivity, but confirm.
2. **Ticket/call model** — does a "support ticket" table already exist anywhere (CRM module?), or does this need a new `support_tickets` table in OxyPC Inventory?
3. **Distribution** — how does the EXE reach the customer? Bundled at time of sale (USB/download link on invoice), or pushed later when they first call support?
4. **Auth** — does the customer need an account/login, or is the serial number + a simple OTP (SMS/email) enough to authenticate a call?
5. **API surface** — Phase 2 EXE will need a small public-facing API (serial lookup, warranty status, create-ticket) on OxyPC Inventory. This must NOT expose the full Device table — needs a narrow, rate-limited, unauthenticated-but-scoped endpoint or an API-key-gated one. Security review required before building (per this repo's MCS/CLAUDE.md security gate).

## Suggested build sequence (once above are answered)
1. Process map: customer call → ticket created → remote session requested → tech joins → resolution logged → ticket closed
2. New tables: `support_tickets`, `remote_sessions` (bounded to a new schema/table-pool per this repo's Database-First standard)
3. Narrow public API (serial lookup + create ticket) — rate-limited, no direct Device table exposure
4. Desktop EXE (new PyInstaller project, separate from OxyQC Standalone): serial detection, ticket UI, remote-tool launcher
5. Support-side UI in OxyPC Inventory: ticket queue + "which remote session" lookup
6. Security review (CSO-style: exposed API surface, remote-tool credential handling, no PII leakage)

**Do not start code until the 5 open decisions above are answered.**
