# ADR 0002 — Web Client Talks Only to the BFF

Status: Accepted

## Context

FreshRSS and RSSHub both expose their own web interfaces and APIs. Letting the
browser talk directly would leak credentials, couple the UI to upstream
implementation details, and make the BFF pointless.

## Decision

The React Web client communicates exclusively with relative Lumi BFF endpoints
(`/api/v1/*`). The BFF handles authentication, protocol translation and error
normalization. Upstream credentials never reach the browser.

## Consequences

- Every new data need requires a BFF endpoint;
- The BFF is the security boundary for secrets;
- Frontend cannot independently call FreshRSS, RSSHub or AI providers.
