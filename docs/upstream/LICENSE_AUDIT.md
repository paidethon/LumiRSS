# LumiRSS License Audit — Gate 0

> This file is an engineering checklist, not legal advice.
>
> No direct upstream source adaptation should be merged until the user
> approves a LumiRSS project license and the final copied/adapted files
> are reviewed.

---

## 1. Current LumiRSS status (verified 2026-08-28)

```text
LICENSE file present:           NO (repo root has no LICENSE file)
Declared package licenses:      none (pyproject.toml / package.json
                                 declare no license)
README license statement:       none
Third-party notice file:        none yet
Existing copied/adapted sources: none — no Folo/OrigRead code has ever
                                 been copied into LumiRSS (verified by
                                 Gate 0B code reading; LumiRSS web src is
                                 an independent implementation)
```

Do not infer "all rights reserved", MIT or AGPL silently. The license
decision belongs to the user.

---

## 2. Reference licenses (verified from locally cloned files)

| Project | License (verified) | Important condition |
|---|---|---|
| Folo | GNU AGPL v3 (`Folo/LICENSE`); README adds exception | `icons/mgc` content is copyrighted by mingcute.com and **cannot be redistributed** |
| OrigRead-Desktop | AGPL-3.0-only (`package.json` field + `LICENSE` file) | source-derived combinations require AGPL compatibility analysis |
| OrigRead (Android) | GPL-3.0 (`LICENSE` file) | code reuse into a network application requires compatibility analysis; GPL ≠ AGPL, network-use obligations differ |
| RSSHub | AGPL-3.0 (upstream project) | currently used only as a separate Docker service pinned by digest; code copying is a different question |
| FreshRSS | AGPL-3.0 (upstream project, 1.29.1) | currently used only as a separate Docker service |
| Docker images (freshrss/freshrss, diygod/rsshub) | upstream licenses apply to image contents | using official images unmodified as separate services is distinct from distributing combined works |

Pin exact license text at the selected upstream SHA (see
`UPSTREAMS.md` §2) before any source reuse.

---

## 3. Decision path

### Option A — Source-first adaptation

If LumiRSS will directly adapt substantial Folo or OrigRead-Desktop
source:

- consider adopting `AGPL-3.0-only` for LumiRSS (recommended by the v6
  proposal, **requires explicit user approval**);
- preserve copyright notices;
- provide corresponding source to network users as required;
- maintain third-party notices and source map;
- still exclude Folo `icons/mgc` assets (the exception survives even
  under AGPL).

### Option B — Independent implementation

If the user does not want AGPL obligations:

- use screenshots, measurements and behavior as design research only;
- implement Lumi components independently;
- avoid copying source expression/assets;
- record material references as `inspired`/`rewritten` in `SOURCE_MAP.md`;
- perform similarity review for close implementations.

A similar visual result does not remove the need to avoid source copying.

---

## 4. Separate-service clarification

Using FreshRSS and RSSHub as separately running services/containers is
not the same engineering act as copying their source into LumiRSS.

Nevertheless:

- retain upstream license notices in distribution where required;
- do not remove their license files from redistributed images/packages;
- document image versions/digests (done: `docker-compose.yml` pins
  FreshRSS 1.29.1 tag and RSSHub by sha256 digest);
- review whether a combined distribution or modified image creates
  additional obligations (currently: official images, unmodified).

---

## 5. Asset policy

Never copy without explicit asset-level permission:

- Folo `icons/mgc`;
- Folo branding/logo/mascot;
- OrigRead branding/logo;
- screenshots containing third-party/private content for product
  marketing;
- fonts from a local machine;
- copyrighted article images as bundled demo data.

Use:

- a separately licensed icon dependency (e.g. `lucide-react` — ISC, but
  any new dependency still requires user approval before install);
- Lumi-owned branding;
- generated/local test data;
- user-provided reference images only as internal design references
  unless redistribution permission is clear.

---

## 6. Required records before merge

- `LICENSE` at repository root (pending user decision);
- `THIRD_PARTY_NOTICES.md` (template prepared in the v6 package,
  to be added when dependencies/licenses are finalized);
- `docs/upstream/UPSTREAMS.md` with SHA/license (done);
- `docs/upstream/SOURCE_MAP.md` (done, empty by design);
- per-file headers when required;
- dependency license review for new UI libraries;
- final confirmation that restricted assets are absent.

---

## 7. License decision record

```text
Decision date: 2026-08-28
Chosen LumiRSS license: AGPL-3.0-only (LICENSE file added at repo root)
Reason: enables compliant adaptation of AGPL-licensed upstream references
  (Folo, OrigRead-Desktop) while preserving upstream copyright obligations
Directly adapted upstreams: none yet (0009 Gate 0 — research only;
  any future adaptation requires per-file SOURCE_MAP entries)
Restrictions/exceptions: Folo icons/mgc must never be redistributed,
  regardless of project license
Notice strategy: THIRD_PARTY_NOTICES.md maintained at repo root;
  per-file copyright headers when upstream code is adapted
Approved by: repository owner (user), during 0009 Gate 0 approval
```

Direct upstream source adaptation is now permitted under AGPL
compliance rules; every adapted/derived file must still be recorded in
`SOURCE_MAP.md` with its exact SHA and path before merge.
