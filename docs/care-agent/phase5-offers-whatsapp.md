# Care Agent Phase 5 — Offers & WhatsApp Hook (scoped plan, not built)

Not implemented in this pass — sending real marketing/service messages
needs a decision on consent language and campaign cadence that's a business
call, not a coding one, plus the `wa-service` Node bridge running to test
against.

## What already exists to build on

- `models/care.py::CareOffer` (already live) — title, body, image, CTA,
  targeting (`target_type`/`target_value`: all / model / warranty_window /
  sale_range), `channel` (in_app / whatsapp / both), `is_marketing`,
  `consent_required`.
- `GET /care/api/v1/offers` (`routers/care_api.py`) — already live, the
  tray/agent already polls this; Phase 5 only needs to populate rows and add
  the WhatsApp send path, not touch the customer-facing read side.
- `routers/whatsapp.py` — the existing Node `wa-service` bridge
  (`POST /whatsapp/send`, see docstring at the top of that file) is the real
  channel already in production use for dealer/customer messaging. Reuse
  this, don't build a second WhatsApp integration.

## Steps (when this is picked up)

1. Build a staff CRUD screen for `CareOffer` under `/care-support/offers`
   (mirror `routers/care_admin.py` conventions) — create/edit/activate,
   with the four MVP targeting types from spec section 4.5. No new backend
   model needed, `CareOffer` already has every field.
2. Add a resolver: given a `CareOffer` row, compute the matching device/sale
   set (join `CareWarranty`/`Sale` for warranty_window and sale_range
   targets). This is a new function in `services/care_service.py`, e.g.
   `resolve_offer_targets(db, offer) -> list[device_id]`.
3. For `channel in ("whatsapp", "both")` offers, call the existing
   `_wa("POST", "/send", ...)` helper pattern from `routers/whatsapp.py` —
   do NOT introduce a second WhatsApp client. Respect `consent_required`:
   only send to customers whose `Dealer`/`Sale` record has an opted-in
   WhatsApp contact, same consent model the dealer-facing WhatsApp flow
   already uses.
4. Add a `care_offer_deliveries` audit table (offer_id, device_id, channel,
   sent_at, delivery_status) — every send must be traceable, per spec
   section 19.4's campaign-audit-trail language and the project's own
   audit-trail-mandatory rule.
5. Rate-limit sends (reuse the pattern in `limiter.py`) so a bad targeting
   query can't blast the entire install base in one run.

## Why this wasn't built now

Sending real customer marketing messages is a one-way action once it goes
out — worth getting consent language, cadence, and targeting review from
Pankaj before any code path can actually push to a customer's WhatsApp. The
schema and read-side API are already there; this is a genuinely small build
once that's confirmed.
