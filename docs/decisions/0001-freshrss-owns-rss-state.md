# ADR 0001 — FreshRSS Owns RSS-Domain State

Status: Accepted

## Context

LumiRSS needs a mature RSS engine. Writing our own would be a massive undertaking
with no product benefit. FreshRSS already handles subscriptions, feeds, entries,
read/star state, refresh and OPML.

## Decision

FreshRSS is the sole source of truth for the RSS domain. Lumi SQLite stores only
application settings, AI cache/metadata and future non-RSS connector data — never
a shadow copy of RSS entries.

## Consequences

- All RSS reads/writes go through FreshRSS via the BFF adapter;
- Lumi cannot independently query or index RSS entries without FreshRSS;
- Future full-text search must either query FreshRSS or build a clearly
  scoped index (not a duplicate database).
