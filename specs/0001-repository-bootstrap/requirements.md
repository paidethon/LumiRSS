# Repository Bootstrap Requirements

Issue: #1
Status: Accepted for implementation

## Goal

Create the minimum trustworthy LumiRSS repository baseline.

## Functional requirements

- FR-1: The repository documents LumiRSS product identity and scope.
- FR-2: A root AGENTS.md defines stable agent instructions.
- FR-3: Sensitive local files are excluded from Git and Qoder context.
- FR-4: The current Issue has requirements, tasks and evidence-based state.
- FR-5: GitHub provides implementation Issue and PR templates.
- FR-6: CI validates repository-baseline invariants.

## Non-functional requirements

- NFR-1: No application or infrastructure service is implemented.
- NFR-2: No secret or runtime data is committed.
- NFR-3: Only commands verified in the current repository are documented.
- NFR-4: Product naming is consistently LumiRSS.
- NFR-5: All remote mutations are performed deliberately by the owner.

## Acceptance criteria

- AC-1: A fresh Qoder session correctly explains AGENTS.md.
- AC-2: Required baseline files are present and non-empty.
- AC-3: Repository checks pass locally where applicable and in GitHub Actions.
- AC-4: The diff contains no business code or unrelated changes.
- AC-5: Verification evidence is recorded in the PR and STATE.md.
