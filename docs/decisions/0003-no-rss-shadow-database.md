# ADR 0003 — No RSS Shadow Database in SQLite

Status: Accepted

## Context

It would be tempting to mirror FreshRSS entries into Lumi SQLite for faster
search, offline access or cross-source indexing. This would create a second
source of truth and synchronization complexity.

## Decision

During MVP, Lumi SQLite does not store RSS entries, feed metadata or read/star
state. SQLite is reserved for application settings, AI results, connector
configuration and future non-RSS source data.

## Consequences

- Search and offline capabilities depend on FreshRSS or future dedicated
  indexes (not a shadow database);
- Future cross-source features must use a Lumi-owned unified source layer,
  not force everything into FreshRSS.
