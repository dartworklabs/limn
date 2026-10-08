# Reply draft recipient preservation

## Resumed approved scope

The owner approved the six additional diagnosed follow-ups with “좋아 진행하고 외관 변하는 건 무조건 데스크톱, 모바일, 태블릿(폴더블 폰) poc 를 제공해”. This repair resumes the existing diagnosed-fixes and UX-safety-fixes authorization on the refreshed delivery worktree. It preserves a reply draft's text and selected recipient logins through cancellation, switching to another pin, and reopening. Duplicate display names must still refer to the chosen person when sent.

The viewer code and its tests are the screen authority (`docs/handbook/purpose.md`); `viewer.md` owns draft and reply preview rules, `domain.md` owns lifecycle transitions, and `architecture.md` owns API, storage, authentication, dependency and transaction invariants. Closing an input still resets its outcome toggle. The server remains authoritative for mention resolution and reply state transitions. Hints are retained only while the selected person's full display-name tag remains in the text, following existing `mentionHints` behavior.

No appearance, new assignment semantics, lifecycle rule, HTTP API, stored record, authentication, runtime dependency, or transaction change is included. The change does not persist reply drafts across page reloads. Desktop/mobile/foldable appearance PoCs remain part of the parent's appearance-changing work, not a deliverable of this invisible preservation repair.

## Acceptance

Use the real viewer, handler, pin store and notice file to reproduce loss before the fix. Cancel/reopen and switch-away/back with duplicate display names must preserve the selected recipient, notify that login alone, and keep a closed fix pin closed. Ordinary untagged drafts must retain text and existing reopening behavior. Undo and failed sending must recover the chosen recipient and existing outcome override. Removing a tag must stop carrying its hint.

Superpowers tools are unavailable in this session, as checked by the parent. This narrow recorded repair uses the already approved scope without installing packages or changing the implementation workflow.

## Recovery ownership follow-up

Independent production review found a pre-existing touched-path overlap: an old deferred send's undo or late failure assigns its recipient hints and outcome override to a newer same-pin reply. Root confirmed the repair is within approved latest-edit preservation scope. Each newly opened reply gets a per-pin visit number held only in page memory; a send's recovery can restore input only while its visit remains the latest. A newer visit wins while live, cached, deliberately emptied and closed, or already sent. A stale recovery never rewrites the newer draft or steals its focus/cursor. A late failure still reports through the existing status line, without attaching an old-send error to the newer reply.

This remains a single-draft-per-pin interface. Retaining both the newer draft and a separate unsent older recovery would require a new queue/UI or recovery policy; none is authorized by this repair. The older callback's recovery snapshot does not replace the newer visit. The original request body remains unchanged if the earlier send commits successfully. Own-visit undo/failure recovery still restores the original text, hints and override.

Acceptance adds real-browser RED/GREEN for both undo and late failure while a newer same-pin draft is live or closed/cached. Persisted recipient, notification and state remain the oracle; text, hints, override and focus/cursor must match the newer visit. There is no pending-reply block or new API/storage/security/lifecycle policy.
