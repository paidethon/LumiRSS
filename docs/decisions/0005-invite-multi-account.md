# ADR 0005 — Invite-Based Multi-Account with Control and Per-User Databases

Status: Accepted

## Context

LumiRSS launched single-user: one trusted operator behind their own auth.
The product then needed to admit a small number of invited members
(friends/family of the operator) with fully isolated data — subscriptions,
read/star state, library, AI settings, and FreshRSS bindings — without
becoming a multi-tenant service or adding public registration. The legacy
layout (one `lumi.sqlite` holding both identity and business tables, a
login fed by a single `auth_password` row) cannot express per-account
isolation.

## Decision

1. **Invite-only accounts.** No public registration. The operator
   (owner/admin role) issues single-use, expiring invitations (only the
   SHA-256 of the token is stored); the invitee activates at `/activate`
   by choosing a username and password. Paused members cannot log in;
   password recovery is an admin-issued recovery invite — no email is
   pretended.
2. **Control database + per-user databases.** Identity lives in the
   control database (`LUMIRSS_DB_PATH`): users, sessions, invites, the
   FreshRSS account pool, audit log, and the machine-token owner index.
   Every user's business data lives in its own SQLite file under
   `<data_dir>/users/<uid>/lumi.sqlite` (plus per-user `secrets.json`).
   The historical single-user schema and repositories run unchanged
   against the user file.
3. **Identity is server-derived, never client-supplied.** A
   `RoutingDatabase` on `app.state.db` resolves every connection to the
   current request's user database via a context var set by the session
   middleware (or explicitly by background loops). A request without a
   verified identity is a hard error — no anonymous fall-back database
   exists, and a frontend-declared `user_id` never selects data.
4. **FreshRSS accounts are provisioned, not shared.** The operator
   pre-creates empty FreshRSS accounts with the official CLI
   (`scripts/freshrss_pool.sh`) and registers them in the BFF pool;
   activation assigns one atomically. An empty pool leaves the account
   usable with an honest "FreshRSS binding pending" state — never a
   shared-credential fallback. The deployment env credentials seed the
   owner's binding once, at migration time.
5. **Legacy layout converges idempotently at startup.** The existing
   `lumi.sqlite` becomes the control database; its business tables move
   to the owner's user database (file-level move + consistency backup),
   and machine-channel tokens are re-indexed to the owner.

## Consequences

- Full-instance backup/restore is an admin operation covering all user
  databases; the Obsidian vault projection is owner-only.
- Per-user migrations run lazily with a per-user lock; adding a member
  requires no global schema change.
- Rolling back to a pre-multi-account image is NOT a drop-in: the data
  layout changed irreversibly; restore the pre-upgrade backup instead.
- Multi-tenancy (public sign-up, quotas, tenant isolation guarantees,
  public-internet hardening) remains out of scope — see the PRD.
