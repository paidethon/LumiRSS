# LumiRSS <version> — offline install bundle

This bundle is a ready-to-install LumiRSS release. It contains:

| file | purpose |
|---|---|
| `lumirss` | lifecycle CLI: deploy / update / backup / restore / doctor / rollback / export-images / import-images / migrate-single |
| `docker-compose.prod.yml` | the production stack (prebuilt GHCR images, digest-pinned FreshRSS/RSSHub) |
| `docker-compose.allinone.yml` | alternative single-container stack (Caddy + BFF + FreshRSS + RSSHub in one s6-supervised container) |
| `docker-compose.external-caddy.yml` | optional: existing host reverse proxy owns TLS |
| `docker-compose.obsidian.yml` | optional read-only Obsidian vault mount |
| `.env.prod.example` | configuration template (copy to `.env.prod`, fill in secrets) |
| `VERSION` | this release's version — the deploy tag default (never mutable `latest`) |
| `ALL-IN-ONE.md` | single-container topology: image layout, s6 services, ports, 4-container migration |
| `release-manifest.json` | advisory manifest: digest-pinned `bff`/`web`/`allinone` images, git SHA, migration list (DB scope), `min_compat` upgrade floor, platform |
| `SHA256SUMS` | SHA-256 over every file in this bundle |

## Verify, then install (air-gapped works)

```bash
sha256sum -c SHA256SUMS                 # integrity first — refuse on failure

# images: EITHER pull from GHCR (online)
sudo ./lumirss deploy                   # pins this VERSION by default

# ...OR load an offline image archive (from './lumirss export-images')
sudo ./lumirss import-images <DIR>      # verifies that archive's SHA256SUMS, then loads
sudo ./lumirss deploy
```

`release-manifest.json` is what you verify AGAINST: the `images` entries
are the exact `@sha256:` digests the release pipeline pushed, `migrations`
lists every DB migration the target applies (upgrade-preview diffs it
against your applied set), `min_compat` is the oldest releasable version
you can upgrade from, and `platform` is the published image platform
(linux/amd64) — check `uname -m` on the target before loading offline.

## Single-container topology (optional)

Same data, same named volumes (`lumi-data`, `freshrss-data`), same project
name — the four workloads share one s6-supervised container
(`lumirss-allinone` image, external-caddy-only: loopback HTTP on
127.0.0.1:18080, the host proxy owns TLS). `ALL-IN-ONE.md` has the details.

```bash
sudo ./lumirss deploy --single       # fresh single-container install
sudo ./lumirss migrate-single        # running 4-container stack → single
                                     # container (backup-gated; volumes kept)
sudo ./lumirss rollback-single       # back to the 4-container stack
```

Daily operations and upgrade flow: `./lumirss status|doctor`, upgrade with
`./lumirss update` (backup → pull → migrate → health → verify, aborts
before touching the running stack on failure).
