# Testing

## During Development

Run only affected tests:

```bash
# Web — single test file
cd apps/web && pnpm test -- path/to/test

# BFF — single test file
cd services/bff && uv run pytest tests/test_specific.py
```

## At Milestone Gate

Run full suites:

```bash
# Web
cd apps/web
pnpm test
pnpm lint
pnpm build

# BFF
cd services/bff
uv run pytest
```

## E2E (Playwright, 0018+)

E2E journeys run against a running stack (default `http://127.0.0.1:18080`,
the production compose smoke entry; override with `LUMIRSS_E2E_BASE_URL`):

```bash
cd apps/web
pnpm test:e2e                                    # all projects
pnpm exec playwright test --project=desktop-1440 # single viewport
```

The WebDAV journey starts an in-memory WebDAV server. When the BFF runs in
Docker, the server must be reachable from the container: set
`LUMIRSS_E2E_WEBDAV_URL=http://<docker-bridge-ip>:18081/` (the compose
network gateway, e.g. `172.19.0.1` — a private IP satisfies the BFF's
plain-http policy).

Reports / traces / screenshots land in gitignored `test-results/` and
`playwright-report/`.

## Visual Verification

For UI milestones, verify at these viewports:

```text
1920 × 1080
1440 × 900
1024 × 768
820 × 1180 (tablet portrait)
390 × 844  (mobile)
```

Check in both Light and Dark themes.

### Required states

- Loading
- Empty feeds / entries
- Selected entry
- Unread/read and starred/unstarred
- Network/API error
- Light/dark/system themes
- Keyboard navigation
- Mobile drawer and list→reader back flow
