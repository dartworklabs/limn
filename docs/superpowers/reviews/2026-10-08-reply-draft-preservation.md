# Reply draft preservation verification

The narrow preservation implementation and recovery-ownership follow-up are ready for parent integration review. The draft map holds text and relevant login hints; reopening copies hints into a new textarea. Own-visit undo and send-failure recovery share that representation, restore the outcome override, and retain the existing rule that cancelling resets the override. A newer same-pin visit wins over any older recovery. No appearance, assignment rule, lifecycle decision, API, stored record, permission or dependency changed.

## Evidence

- Real Chromium plus the existing in-process HTTP handler, pin store and event file reproduced four failures before the repair: cancel/reopen, pin switching, undo followed by cancellation, and failed send followed by cancellation all stored an empty recipient list instead of the selected duplicate-name login. The fifth removed-tag case passed on the baseline.
- The repaired tests verify exact persisted message recipients, notification targets and closed state, with the visible outcome checked against those effects. An ordinary untagged draft retains its text and still reopens a closed fix pin. Undo and aborted sending produce no pin write, preserve the chosen recipient and recover the flipped outcome; cancelling still resets that flip.
- Replacing the close-time `mentionHints` snapshot with all raw hints made the removed-tag test fail on its observable outcome: a previously removed tag silently regained its old recipient when typed again. The production source was restored byte-for-byte, then the browser checks passed again.
- `LIMN_TEST_REQUIRE_BROWSER=1 uv run pytest -q src/limn/viewer/tests/test_reply_drafts.py src/limn/viewer/tests/test_viewer_browser.py::ReplyKeyboardAndFailure src/limn/viewer/tests/test_viewer_browser.py::PreviewEqualsServer` passed all 9 tests and 5 subtests. Targeted Ruff lint/format, `npm run typecheck`, and `git diff --check` passed.
- Raw RED, mutation and restored GREEN logs are preserved outside the repository in the machine's Limn repair logs. Parent owns the full integration gates and final approval; no commit, stage, push or PR was made by this worker.

## Recovery ownership follow-up evidence

The independent production review identified a pre-existing touched-path overlap that the original five tests did not cover. Four additional real-handler browser cases reproduced it: older undo and older failed-send recovery while a newer same-pin draft was live or closed/cached. The live cases persisted `robin.one@example.com` instead of the newly chosen `robin.two@example.com`; the cached cases restored and persisted the OLD text instead of NEW. An initial cached-focus diagnostic waited for an element removed by the defect; the final tests read focus immediately from the document so every RED case fails on an actual persisted message assertion. Both exploratory and final RED logs are retained.

Recovery now compares its captured per-pin visit number with the latest visit before changing any draft, box or focus. The counter remains in page memory and retains no DOM. The four overlap cases preserve the newer text, selected login and outcome override, plus exact focus and selection offsets; when the newer draft is cached, another pin's active text field keeps focus. A late failure appears on the existing status line with the affected pin number, and no old-send error is attached to the new reply.

The final targeted browser command listed above passes **13 tests and 5 subtests** after this follow-up, including normal own-visit undo/failure recovery. Updated Ruff lint/format, viewer type checking and diff checks pass. Final logs are `limn-reply-draft-repair-overlap-red.log` and `limn-reply-draft-repair-overlap-green.log` in the machine's repair logs.

The interface still retains one draft per pin. When a new visit exists, the older undone or failed snapshot is not independently recoverable from a second draft queue: it cannot replace the newer draft. Retaining both would require separately approved UI or storage policy. No such queue, pending-reply block, persisted visit counter, new permission or lifecycle rule was introduced.

## Release metadata preparation

The parent authorized preparation of version 0.4.21 and a pending release entry. Remote main still points to `fe98b5897ec8402f37833411fd9447b025dd02ea`, whose version is 0.4.20; remote v0.4.20 exists, v0.4.21 does not, and no other 0.4.21 reservation was found in the worktree. The source version is now 0.4.21 and CHANGELOG has an **Unreleased** entry for the approved production repairs, including compatibility retained for `pins.md`, API, pin records, authentication and runtime dependencies. Unapproved main-bar reading/search and inline assignment prototypes are excluded.

Hatch reads the dynamic version from `src/limn/__init__.py`. The editable project's `uv.lock` entry has no version field. `uv lock --check` passed without a lock-file diff, and importing Limn reports 0.4.21. Release metadata preparation does not tag, publish, install or claim deployment; those remain parent's decisions after review and gates.

## Scope and limits

The managed handler, store and notification file run for real. The existing harness serves blank PNG pages; PDF extraction, SyncTeX and physical-device keyboard/gesture behavior are outside this reply-only test. The failed-send example deliberately aborts the browser transport and then retries through the real handler. A new pure parser or lifecycle rule was not introduced, so this DOM-state preservation repair uses focused sequence examples rather than adding a generated property over unchanged domain functions.

The project supports Python 3.10 and later and ES2022 in current desktop browsers. Python and JavaScript implementation references, their testing references, security rules and Handbook read/sync rules were read. The change preserves the existing viewer slice placement and error style and adds no production cross-slice import. No new security grant or entry point exists; the negative case checks that a removed tag cannot regain its old login hint. The server retains authoritative mention resolution and authentication.

A direct diagnostic invocation of mypy on the new test reported missing test-helper imports and untyped test definitions. This is outside the configured gate: `pyproject.toml` excludes all colocated tests from discovery and sets `mypy_path = "src"`. Parent runs the configured production-only mypy checks. Runtime shutdown, page reload draft persistence, concurrent replacement of the participant directory and physical devices were not exercised. Drafts remain confined to the current page as before.
