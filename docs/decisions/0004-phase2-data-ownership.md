# ADR 0004 — Phase 2 Data Ownership and the Single ItemRef Registry

Status: Accepted

## Context

Phase 2 added several content domains (Library bookmarks/clips/snapshots,
API sources, newsletter bridge, Obsidian projection, RAG index, tags,
workspaces, agent threads). Without a written ownership contract the
implementation drifted: resolvers only covered one library kind, mail kept
an undeclared second article store, the graph mixed scopes, and tests
asserted inverted dedupe semantics. This ADR is the minimal, enforceable
contract every Phase 2 module must satisfy. It extends, and never
contradicts, ADR 0001 (FreshRSS owns RSS state), ADR 0002 (Web talks only
to the BFF) and ADR 0003 (no RSS shadow database).

## Decision

### Ownership table

| Data | Owner (source of truth) | Lumi keeps |
| --- | --- | --- |
| RSS feeds, entries, read/star | FreshRSS | derived search projection (`search_entries`), rebuildable |
| API source configs | Lumi (`api_sources`) | generated Atom is a derivative; converted entries belong to FreshRSS once subscribed |
| Newsletter bridge configs + delivery spool | Lumi (`mail_*`) | spool is bounded, cleanable, rebuildable-from-source; readable entries live in FreshRSS; never a second long-term article store |
| Bookmarks, clips, snapshots (user-saved) | Lumi (`library_items` + kind tables, `library_assets`) | — |
| Obsidian vault content | The vault (filesystem) | one-way, deletable/rebuildable projection (`obsidian_notes`); never writes back |
| RAG vectors/chunks | nobody (derived index) | rebuildable from owned sources; `rag_vec` is the only vector table search queries |
| Tags, workspaces, favorites | Lumi | reference content exclusively via validated typed ItemRefs |
| Agent threads/messages/approvals | Lumi (`agent_*`) | references content via ItemRefs |

### The one ItemRef implementation

`rss:*` and `library:*` refs have exactly one parser (`itemref.py`), one
registry (`sources.py`) and one resolver set (registered in `deps.py`,
dispatching by library kind to the owning store). Every consumer —
workspaces, tags, favorites, graph, unified search, RAG chunks, agent
tools, read-later — resolves through the registry. Attaching a tag,
favoriting, or adding to a workspace validates that the ref resolves at
write time; dangling refs degrade to stale views, they are never silently
dropped or invented (no synthetic nodes for unresolved targets).

### Write rules

1. Cross-table domain writes (identity + payload + projection + spool)
   run in one transaction or an explicit compensating path; a failed write
   leaves no half-created rows, orphan files, or dead subscriptions.
2. Deleting owned content removes (or ref-counts down) its projections,
   assets and subscriptions in the same operation; failures are surfaced,
   not swallowed.
3. Schema changes are forward-only migrations; new columns/tables only —
   no destructive rewrites of production data.

### Display rules

- Every resolved card (unified card, search hit, favorite, workspace item,
  graph node, agent citation) must have a working open action or an honest
  "unavailable" state. Unresolved refs render as stale/missing, never as
  fake content.
- Graphs return both the raw candidate total and the returned count when
  truncated; scope filters apply to every edge type or the scope is not
  offered.

## Consequences

- One resolver to fix when a kind cannot open; no per-feature parsing.
- Mail, API-source and clip features must clean up FreshRSS/spool state
  they created — unsubscribe failures block config deletion.
- RAG, search projections and the Obsidian projection are disposable:
  backup/restore covers owners, not derivatives (assets ARE owned and
  therefore backed up).
- Tests assert ownership semantics (dedupe direction, ETag stability,
  resolver coverage), not just status codes.
