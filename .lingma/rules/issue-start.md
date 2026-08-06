Before implementation, read:

1. Root `AGENTS.md`.
2. The current GitHub Issue.
3. The matching directory under `specs/`.
4. Relevant ADRs.
5. `contracts/openapi.yaml` when it exists.

Inspect existing files and tests before editing.

Return:

- Current behavior and repository evidence.
- Target behavior.
- Files in scope.
- Files and capabilities out of scope.
- Test and verification plan.
- Risks or source conflicts.
- An implementation plan of no more than eight steps.

Do not edit until this analysis is complete.
LumiRSS currently supports FreshRSS only.
Do not add Folo production compatibility, Miniflux, Redis, queues,
recommendations, digests, vector search or multi-user auth unless the current
Issue explicitly requires it.
