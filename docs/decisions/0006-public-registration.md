# ADR 0006 — Public Registration as an Optional, Default-Off Instance Policy

Status: Accepted

## Context

ADR 0005 made LumiRSS invite-only multi-account: the only way in was a
one-time, expiring invite, because the deployment is the operator's own
small circle and public sign-up was equated with becoming a multi-tenant
service. That reasoning protected the operator's exposure, but it also
hard-coded a product restriction into the architecture: an operator who
wants to point friends at a signup form instead of hand-delivering links
had no path, and the frontend had to pretend no register surface could
ever exist.

The product decision has changed: LumiRSS now supports **optional public
registration, disabled by default**. Invite-based onboarding remains fully
supported; the operator chooses per instance whether self-serve signup is
also available. What did NOT change is anything about data isolation —
that part of ADR 0005 stands.

## Decision

1. **Invite + optional self-registration.** `/activate` (invite
   redemption) and `POST /api/v1/auth/register` (self-serve) coexist;
   the operator picks the mix. Invites keep their one-time, expiring,
   SHA-256-only semantics.
2. **Disabled by default, everywhere.** The switch is the instance-level
   `allow_public_registration` setting (control DB, `instance_settings`
   table, migration 0089). The default lives in the application layer,
   not the database: an absent row means closed, so upgraded instances
   and fresh installs alike stay closed until an admin explicitly
   enables it. There is deliberately no env var and no localStorage
   override — the control DB is the single source of truth, changes are
   audited (`GET/PUT /api/v1/admin/registration-policy`).
3. **Server-enforced, role hardcoded to `member`.** The gate lives in
   the BFF register endpoint, not in a hidden frontend button; a closed
   instance answers a uniform `403 registration_disabled` (no username
   oracle), the request can never specify a role, and the register path
   is rate-limited and covered by the CSRF Origin check. Registration
   mirrors `/auth/activate` in every other respect: FreshRSS pool
   assignment is atomic, an empty pool yields the honest "binding
   pending" state, and the response only carries session facts — identity
   comes from `/auth/session`.
4. **Per-account isolation is untouched.** Self-registered accounts get
   the same control-plane row, per-user database and server-derived
   identity as invited ones. Nothing about the data layout changes.

## Consequences

- Opening registration is an operator judgment call: this ADR ships the
  switch and the honest gate, not a public-internet hardening story.
  Rate limiting and CSRF coverage bound the abuse surface, but an
  operator who flips the switch on a public domain must evaluate their
  own exposure (edge auth, TLS, monitoring, FreshRSS pool sizing).
- Public-internet hardening and multi-tenant guarantees (quotas, tenant
  isolation SLAs) remain explicitly out of scope — enabling registration
  does not move LumiRSS into multi-tenancy.
- ADR 0005 is partially superseded: its invite-only exclusivity no longer
  holds; its control/per-user database split and server-derived identity
  remain the law of the land.
