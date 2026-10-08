# Repair tasks and verification

Scope: [agreed repair requirements](../specs/2026-10-07-diagnosed-fixes.md). Base refreshed before edits: `origin/main` at `38dc0d7`, equal to the working branch. Agents work on disjoint files in the shared worktree; root integrates documentation and final checks.

1. **Pin integrity agent.** Add real-server regressions for edits during pending create/edit, stale append and undo, and duplicate submission; demonstrate failures, then repair ownership and revision handling. Check existing document-switch flows, JavaScript types, and translations.
2. **Build agent.** Preserve a CSV's exact mtime and size, assert changed PDF text, then force latexmk rules for changed recorded inputs while retaining byproducts. Verify one-pass warm edits, unchanged skips, and dpi-only reuse.
3. **Outline agent.** Align grid items at their first line, reduce desktop padding, add row spacing in both lists, and show printed page labels without suffixes. Verify desktop and touch geometry and inspect the native collaborative browser.
4. **Root.** Make the unsigned revision fixture deterministic and check every revision-range test. Record the approved scope and integrate current Handbook rules.
5. **Dynamic reassignment.** The build agent adds Firefox/WebKit critical save flows and their CI browser installation. The outline agent finds and measures bounded figure-selection candidates against the original map, adds failing examples and generated invariants, then implements the reviewed rule. Completed agents review another slice's changes.
6. **Integration.** Inspect the complete diff against the constraints and Handbook; run pytest, instance tests, Ruff, ShellCheck, boundaries, both mypy platforms, viewer typecheck, and strict ratchet. Run changed CI test entry points and record honest skip reasons. Refresh the remote base again and address any divergence without discarding work.

Physical iOS validation is an explicit remaining device check, not a substitute claim based on WebKit desktop automation. No PR, deployment, or release is required by this task.
