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
