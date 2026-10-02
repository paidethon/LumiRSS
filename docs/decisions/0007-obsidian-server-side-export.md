# ADR 0007 — Obsidian Server-Side Export Behind the Read-Only Projection

Status: Accepted

## Context

ADR 0004 fixed the data-ownership table: the Obsidian vault owns its own
content and Lumi keeps a one-way, rebuildable projection of it — the
projection "never writes back". That invariant protected the vault from
being treated as a Lumi scratch space, but it also hardcoded a product
limitation: members who use Obsidian as their long-term knowledge base
had no path to move Lumi content (articles, bookmarks, clips, snapshots,
their annotations, AI summaries/translations) into the vault, short of
copy-pasting by hand.

A browser-side path does not exist: the browser has neither filesystem
write access to the vault nor any business knowing host paths — upstream
credentials and server paths must never reach the browser. And a naive
"server writes into the vault" feature would break exactly what ADR 0004
protected: user-authored notes could be clobbered, vault-wide symlinks
could be followed outside the vault, and an unbounded writer could fill
the disk.

## Decision

1. **The read side is untouched.** `/vault` stays a read-only mount and
   the projection module (`obsidian.py`) still contains zero write calls.
   "Vault is a read projection" remains true for everything the reader,
   search, graph and Agent see.
2. **One bounded write face, separately mounted and opt-in.** A new
   overlay (`docker-compose.obsidian-export.yml`) mounts an export root
   (`LUMIRSS_OBSIDIAN_EXPORT_HOST_DIR` on the host, fixed
   `LUMIRSS_OBSIDIAN_EXPORT_DIR=/vault-export` in the container, rw) —
   typically a Lumi-dedicated subtree of the vault (e.g.
   `…/MyVault/LumiRSS`). Not stacking the overlay keeps every existing
   deployment byte-identical with the feature off. The API is
   `POST /api/v1/obsidian/export` (batch of refs + include flags for
   summary/translation/annotations), plus `/status` (today's usage,
   recent exports) and per-user subdir preferences; the Web entry is the
   reader's "更多操作 → 导出到 Obsidian".
3. **Never overwrite, idempotent by content-id.** Writes go through tmp
   + `os.link` (the link fails atomically if the target exists), falling
   back to `O_EXCL` on filesystems without hardlinks — an existing file,
   including a user's hand-written note, can never be clobbered. The
   content-id is derived deterministically from the ItemRef; re-exporting
   the same content returns `exists` instead of writing again. Same-name
   different-content conflicts get `-2`…`-99` suffixes; the old file is
   preserved.
4. **Path containment and per-user isolation.** The export root is
   realpath-resolved once and every write re-resolves its target and
   rejects anything escaping the root (symlink/junction planted inside a
   subdirectory = rejected, never followed). Files land only under
   `<subdir>/<user_id>/` — the subdir is a per-user preference
   (default `LumiRSS`), `user_id` is the server-derived account id, so
   accounts on the same instance never see each other's exports.
5. **Bounded and audited.** 1 MB per file, 50 refs per batch, 64 MB per
   user per day; oversized bodies are truncated and the frontmatter says
   so (`truncated: true`). Every written/exists outcome is logged to a
   per-user `obsidian_export_log` ledger; the ledger is an audit
   projection — the filesystem remains the source of truth.

## Consequences

- When the export root points into the vault, exported notes are
  re-indexed by the read-side scanner like any other note — they show up
  in search, backlinks and the projection without a second sync path.
- Lumi still never deletes or modifies anything in the export root;
  deleting content in Lumi does not delete exported notes. There is
  still no two-way sync or free-form write-back — ADR 0004's "the vault
  owns its content" stands; what changed is that a narrow, defensive
  export channel now exists (this ADR partially supersedes ADR 0004's
  "never writes back" clause for the export root only).
- The feature is honest about failure: unconfigured/unreachable export
  root, path rejections, quota exhaustion and write failures surface as
  per-item error reasons in the batch response, and one bad item never
  fails the batch.
