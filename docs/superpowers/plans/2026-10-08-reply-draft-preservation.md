# Reply draft repair tasks

Base: parent refreshed `origin/main` to `fe98b5897ec8`; delivery HEAD matches it, and inherited work is preserved. Worker scope is `reply.js`, a reply-focused regression, optional state types, and narrow documentation. Parent owns integration and full gates; another worker owns PoC files.

- [x] Add real-handler browser regressions for duplicate-name cancel/reopen and pin switching; observe recipient assertion failures before production edits.
- [x] Store text and relevant mention hints together, copy hints on reopening, and keep send undo/failure recovery consistent.
- [x] Verify ordinary draft behavior, removed-tag filtering, undo, and failure recovery against persisted recipients, notifications and pin state.
- [x] Update the viewer Handbook rule and record targeted RED/GREEN evidence outside the repository.
- [x] Run targeted browser tests, relevant existing reply tests, Python lint/format, and viewer type checking.
- [ ] Parent reviews the complete diff and runs full integration gates.

## Recovery ownership follow-up

- [x] Add real-browser overlapping undo/failure cases with newer live and cached same-pin drafts; observe persisted-message failures.
- [x] Bind recovery to the latest per-pin visit without changing the single-draft or lifecycle rules; retain current/newer text, hints, override and cursor.
- [x] Preserve normal undo/failure recovery and use the existing status line for a stale failed send.
- [x] Record the older-recovery limitation, update the current Handbook rule, and run focused RED/GREEN plus static checks.

## Authorized release metadata preparation

- [x] Confirm the remote main and latest tag remain 0.4.20 and there is no 0.4.21 reservation.
- [x] Prepare `__version__ = "0.4.21"` and an Unreleased CHANGELOG entry covering approved production repairs only.
- [x] Verify `uv lock --check`, unchanged `uv.lock`, and importable version 0.4.21. Git publication, release and install decisions remain parent-owned.
