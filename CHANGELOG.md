# Changelog

## 0.3.5 — unreleased

Mouse and touch usability from the 2026-09-26 input review ([viewer.md](docs/handbook/viewer.md) §패널 폭과 시트 높이,
§펼친 화면 레이아웃, §모바일 레이아웃). Viewer only: the HTTP API, `pins.md` and the state directory are unchanged; the
browser keeps two new preferences (`pinPrefs.sideClosed`, and the `side`/`mouse` hints in `pinPrefs.coach`) and a
per-tab draft (`sessionStorage` `limnDraft:<label>:<doc>`). One server fix: new-pin notices name the pin's document.

- **Collapse the panel by its handle, in every layout.** Drag it right: the width follows down to the minimum, stops
  there between half the minimum and the minimum (the bar turns primary), and below half the minimum the panel's
  contents fade to 40% as a preview; a release collapses it with a 0.18s slide, keeping the drag-start width as the
  saved width. A draft (composing, editing, replying, relocating) stops the drag at the minimum instead. The wide panel,
  which could not be closed before, leaves a 6px rail at the right edge (drag it back or double-click it), shows
  `[핀 N ‹]` at the right end of the nav bar, floats the status chips and toasts at the PDF area's bottom-right, and
  opens again for a pick, a mark, a pin link, the review list or an in-text `#N`. Remembered per device
  (`pinPrefs.sideClosed`).
- **Keys.** The handle follows the WAI-ARIA window splitter: Enter collapses and expands, Space cycles the presets,
  Home = minimum, End = maximum (they were reversed); collapsed = `aria-valuenow` 0. `Ctrl/⌘+\` toggles the panel (or
  the phone sheet) at every width outside text fields. Esc closes the 701-900px overlay after a selection, and returns
  from [변경 보기] to the manuscript.
- **Touch.** Swipe the 701-900px overlay right to dismiss it (35% of its width or a fling; a draft only rubber-bands).
  Drag the phone sheet by its whole tool bar, or pull its content down at the top; a downward fling collapses it, an
  upward fling goes to the next height, and a draft stops it at 30% instead of hiding the note. The system back
  gesture closes the sheet, the overlay or the mid outline first (CloseWatcher, else one history entry), and a right
  swipe no longer navigates back out of Limn. A double tap on the PDF toggles fit width and 2x. The click that used to
  follow a handle tap or a quick pick and land on the panel under the finger is swallowed. The documents sheet and help
  close on an outside tap; the documents sheet also follows a pull-down.
- **Undo instead of loss.** Esc or [취소] on a selection with a written note offers `선택 취소됨 · [되돌리기]`, which
  brings back the selection, the note and the box; [되돌리기] after saving a pin also reopens the composer with them.
  The composer draft is also kept per tab in `sessionStorage` (per instance and document, written on every edit): a
  reload, or leaving Limn with a second back gesture and coming back, restores it with `작성 중이던 메모를 되살렸습니다 ·
  [버리기]` (only the note when the PDF was rebuilt meanwhile). Saving clears it; a discard clears it after its undo window.
- **Smaller things.** Mouse hit targets reach 24x24 (WCAG 2.5.8) without changing what is drawn; the PDF shows a
  crosshair and a first-time mouse user gets one hint; a pick in the overlay's right column is no longer hidden
  under the panel; the handle's tooltip hides when the drag starts; more than three toasts get a button that opens
  the stack on touch.
- **New-pin notices name the pin's own document (fix).** On an instance started with several `--doc`, the `mention`
  and `assigned` records a new line pin writes to `events.jsonl` carried the first document's key in `doc`, because
  they were made before the record had its `doc`; a notice about a pin in the second document opened the first one.
  They now carry the pin's document, like every other notice. Region pins, single-document instances and the other
  fields are unchanged; records already written are left as they are.
- Rolling back to 0.3.4 is safe: it ignores `pinPrefs.sideClosed` (a wide panel just opens).

## 0.3.4 — unreleased

English error messages, a Limn mark, and the two ADR-0006 follow-ups of
[issue #24](https://github.com/dartworklabs/limn/issues/24). The `pins.md` format and the stored pin record are
unchanged. The HTTP API adds one field to every error body and two icon routes.

- **Every error body names a stable reason code (API, additive).** Error responses are now
  `{"error": "<Korean text>", "reason": "<code>"}`; the Korean text is unchanged byte for byte. The 409 bodies whose
  `error` is already a code (`done`, `conflict`, `open`, `full`, `claimed`) repeat it in `reason`; the comparison PDF
  status and the `200` refusals of `POST /api/pick` use the same codes. `HTTPError` cannot be built without one. The
  codes are listed in `docs/handbook/api.md` §오류 응답; agents should branch on `reason`, not on the text.
- **The English viewer shows API errors in English.** One function, `errText()`, shows every API error: Korean shows
  the server text as before; English looks up `reason:<code>` in `ui_en.json` (one message per code, tested) and falls
  back to the server text. It covers the error toasts, the pick error in the composer and the re-place banner, the
  edit card's source box and the comparison PDF status line. The composer's pick warning (a UI hint the server composes
  from up to three Korean sentences, not an error body) is shown in English too, sentence by sentence. The English chrome test now drives the common refusals
  (403 view-only, 409 `base_rev` conflict, 400 validation, 404 pin, 422 pin scope) and checks the toasts carry no
  Hangul; the Korean run checks they show the server text unchanged.
- **The Limn mark.** One stroke that starts at a small dot (the pin) and runs into a line (the source line). It replaces
  the label's first letter in the favicon, sits before the instance label in the top bar and the [More] label chip (in
  the instance colour) and in the help dialog header (monochrome, follows the theme). Inline SVG coloured by CSS
  tokens; the geometry lives once in the new pure module `limn.mark`, which also draws the PNG fallbacks at runtime with
  the standard library (`GET /favicon-32.png`, `GET /apple-touch-icon.png`, keyed by `?c=<accent>`). Browser
  notifications use the 180px PNG (Android draws no SVG icons).
- **[View changes] keeps the recorded lines after a move (issue #24 §1).** The absolute paths in a closed pin's `changes`
  are located on read by the ADR-0006 rule, so a moved or cloned checkout still reports `source: "changes"` instead of
  inferring the hunks. The stored `changes` and the API's `changes[].file` are unchanged; a path that cannot be placed
  is dropped as before.
- **Tails stay in the pin's own document (issue #24 §2).** For a moved record without `file_rel`, the longest existing
  tail is searched in the pin's document folder (its build root) instead of the whole manuscript folder, so a
  same-named file of another document is never picked, and a document folder renamed with its `--doc` spec is followed.
  Instances started without `--doc` behave as before (a single `--doc` pointing at a sub-folder searches only it). No
  write migration.
- Rolling back to 0.3.3 is safe: nothing new is stored, so 0.3.3 reads the same state directory. Its error bodies
  simply have no `reason`, and it serves its own page and favicon.

## 0.3.3 — unreleased

Agents on the machine that serves an instance get a standard place for their token, so the instance can turn off
the deprecated headerless loopback agent (decision record [ADR-0007](docs/adr/0007-agent-token-file.md)); the
instance manager also runs on macOS semantics ([issue #12](https://github.com/dartworklabs/limn/issues/12)). The
`pins.md` format and the HTTP API change only by addition: one clause at the end of the agent-auth line once a token
file exists, and a hint after the existing text of one `401`. The state directory is unchanged.

- **Token file.** `limn token create <instance> --save` writes the new token to `~/.config/limn/<instance>.token`
  (the instance config folder, `LIMN_CONFIG_DIR`; never the `LIMN_SOURCE_DIR` copy): mode 0600, a missing folder
  made 0700, the token not printed unless `--print`. It refuses an existing file (`--force` replaces it atomically and
  names the replaced token if it is still valid) and a folder inside a git work tree that does not ignore the file
  (even with `--force`). Every refusal comes before the token exists; a failed write revokes the new token.
  `limn token path <instance>` prints the path, `limn token list` says which token the file holds, and
  `limn token revoke` removes the file when it held the revoked token.
- **Server (additive).** `--agent-token-file` (default `LIMN_AGENT_TOKEN_FILE`, which `limn run` sets; no new argv, so
  a config without access keys still runs the v0.1 argv) tells the server where the file is. It only checks that the
  file exists, never reads it. Then pins.md's agent-auth line ends with
  `` 이 기기의 에이전트는 토큰 파일을 붙인다: `curl -H "Authorization: Bearer $(cat ~/.config/limn/<instance>.token)" …`… ``
  (not for a remote `GET /pins.md`), and with the loopback agent off a headerless local request gets `401` whose
  text is the old message followed by where the token file is (a proxied request keeps the old text).
- **Instance manager.** `limn status`, `list`, and the waits in `start`, `update` and `doc … --restart` send the
  token file (on curl's stdin, never its command line), so they keep working with `AGENT_LOOPBACK=0` - and only when
  every listener on the port is this account's (`/proc/net/tcp` on Linux, `lsof` on macOS), so another account holding
  the port while the instance is down never receives it. A `401` is
  reported with the command that fixes it and ends the wait at once instead of running out `LIMN_WAIT`. A token
  file that is a symlink, belongs to another account, is open to group/others, or is not one token line is not used
  (a warning says why). `limn snippet` tells agents on the serving machine to use the token file.
- **macOS.** `instances.sh` checks that its Python is >= 3.10 (`LIMN_PYTHON` too old is an error; run directly it
  takes the first new-enough `python3`/`python3.1x`, not macOS's 3.9 `/usr/bin/python3`), reads `stat` fields on
  GNU or BSD, and bounds `limn update`'s tag lookup without `timeout(1)` (`gtimeout` or `perl`). The tests follow:
  `test_instances.sh` picks a Python >= 3.10 and a portable `stat`, and `test_cli_env_parsing_matches_instances_sh`
  no longer relies on `source <(…)`, which sources nothing in macOS's bash 3.2. CI gains a `macos` job (Python
  tests without TeX/Chromium, the instance manager under `/bin/bash` 3.2).
- **Rollout per instance:** install 0.3.3, `limn token create <instance> --name <name> --save`, switch the paper
  repository's AGENTS.md to `limn snippet <instance>`, then `AGENT_LOOPBACK=0` and restart.
- Rolling back to 0.3.2 is safe: it neither sets nor reads `LIMN_AGENT_TOKEN_FILE` and ignores token files; with
  `AGENT_LOOPBACK=0` its `limn status` shows `401` again and its start wait runs out `LIMN_WAIT`, while the server and
  token-using agents behave the same.

## 0.3.2 — unreleased

Pins follow a moved manuscript ([issue #7](https://github.com/dartworklabs/limn/issues/7), decision record
[ADR-0006](docs/adr/0006-relative-pin-paths.md)). The stored pin record gains one optional field. The
HTTP API adds one computed field, and `file` in responses now names the file where it is now. The `pins.md` format is
unchanged.

- **`file_rel` (stored, additive).** When the server creates, edits (note, range or relocation) or restores a pin, it
  also stores the file's path relative to `--manuscript` (`sections/intro.tex`) and rewrites `file` as the current
  absolute path. Records written earlier are **not** rewritten to add it (no write migration), not even when another
  write touches the file.
- **Locating a pin's file (every read).** The stored `file` if it lies under the current manuscript folder; else a
  `file_rel` that the stored `file` ends with (a stale one left by a 0.3.0 relocation is ignored; a longer existing
  tail of `file` wins, for a widened folder); else, for older records, the longest tail of `file` that exists under
  the folder (the rule `to_source()` uses for SyncTeX paths), never with `..` parts. The result must still resolve
  inside the folder, so a symlink cannot lead out. Pins that cannot be located stay outside the tree exactly as
  before: no line re-sync, no range edit, no quote, nothing read.
- **Line re-sync of a moved record.** Its `synced_at` was measured on another file, so the mtime shortcut is taken only
  while the anchor's head is still at the recorded line; a re-match also writes the located path into `file`, so the
  lines and `file` describe one file (switching back to an old checkout follows its lines again). No anchor is
  backfilled from a located file.
- **What changes after moving a checkout.** Pins keep following edits via their anchor, `/edit` with `lo`/`hi` works
  (it was `400`), `pins.md` keeps `sections/x.tex L12-L18` and the long-line `«…»` quote, overlaps join pins made
  before and after the move, and [View changes] uses the current path.
- **API (additive).** Pin responses carry a computed `rel_path` (old records too) and `file` is the absolute path
  valid on this machine now (the stored value when the pin cannot be located). The stored `file_rel` is not returned.
  The issue's suggested name `rel` is already the overlap list in `GET /api/pins`.
- `/edit` checks a `note_append` that would exceed the note limit before changing anything (a 400 could leave a
  partial edit when the same write re-synced lines).
- Not covered: the paths inside a closed pin's `changes` stay absolute (after a move, [View changes] infers the hunks),
  and view-only PDF pins keep their `pdf` path (they are found by document key). Follow-ups:
  [issue #24](https://github.com/dartworklabs/limn/issues/24).
- Rolling back to 0.3.1 (or 0.3.0) is safe: both ignore `file_rel` (and never return a `rel_path`), records
  rewritten by 0.3.2 carry a current `file`, and untouched records look exactly as they did before the upgrade.

## 0.3.1 — 2026-09-26

Two low-severity findings of the v0.2.1 security review ([issue #10](https://github.com/dartworklabs/limn/issues/10)).
The `pins.md` format and the HTTP API are unchanged. One notification behaviour changes; the state directory gains two
files once something is audited (`audit.jsonl` and its lock `.audit.lock`).

- **Note mentions have a ten-minute cooldown (L3).** A note save, edit or `note_append` that tags someone again sends
  that person a `mention` at most once per ten minutes per (editor, person, pin) (`NOTE_MENTION_COOLDOWN_S` = 600 s).
  Toggling `@Bob` off and on through repeated edits used to notify Bob on every edit. Suppressed mentions are not
  written; the pin's `mentions` field still follows the note. Replies and reopen reasons still notify every time.
  The rule reads `events.jsonl`: a `mention` without `msg` came from a note.
- **Audit log (L5).** Destructive and owner actions are appended to `<state_dir>/audit.jsonl`, one
  `{at, ts, action, by, via, details}` per line: `cleared` and `purged` from the server (`via: "http"`), and
  `token_created`, `token_revoked`, `member_added`, `member_role`, `member_removed` from `limn token` / `limn member`
  (`via: "cli"`, `by` = the OS account that ran the command). Limn only ever appends to it (never truncated, unlike
  `events.jsonl`, which keeps the newest 5000 and could rotate the `cleared` record out), under a cross-process lock
  (`.audit.lock`), mode 0600, no symlinks followed. Token lines carry the id and name, never the token or its hash.
  A failed audit write is a warning; the action stands. The `cleared` and `purged` events are still written.
- Rolling back to 0.3.0 is safe: 0.3.0 never opens `audit.jsonl` or `.audit.lock`, and the cooldown keeps no state
  of its own.

## 0.3.0 — 2026-09-26

Pin-scoped [View changes] ([issue #9](https://github.com/dartworklabs/limn/issues/9), decision record
[ADR-0005](docs/adr/0005-pin-scoped-changes.md)). The HTTP API changes are additive. One `pins.md` line changes: the close
instruction; everything else in `pins.md` is byte-for-byte the same.

- **Agents: always send `changes` (agent-visible).** The close instruction in `pins.md` and the skill now ask agents to
  close with `changes` (the lines changed for the pin, numbered as in the commit `ref` names — after a squash merge, the
  merged `main`) and `ref` = `PR #<n> (<commit hash>)`. Committing each pin separately helps but is not required; PRs may
  be squash-merged. Nothing enforces it; old agents keep working.
- **`changes` on close (additive).** `POST /api/pins/{id}/close` takes an optional `changes: [{file, lo, hi}]`, the
  new-side line ranges the agent changed for this pin (`file` relative to the manuscript folder like the `pins.md`
  location column, or absolute inside it). Invalid shapes are `400` and change nothing; `[]` is the old close. Stored on
  the pin as `changes` (absolute paths, with `changes_at` = that close's `done_at`) on the first close, kept on re-close,
  cleared by reopen; exposed in the pins API.
- **Inference for everything else.** For a pin without `changes` (or whose `changes` hit nothing in the commit) the
  server picks the commit's hunks that overlap the pin's range mapped through the commit (its anchor on the new side,
  else the old side; renames followed). If nothing overlaps, the view is the whole commit, as before.
- **API (additive).** `GET /api/revision-diff?pin=<id>` adds `scope: {pin, mode, source, hunks, other, diff, other_diff}`;
  `POST /api/revision-build` accepts `pin` in its body, and `GET /api/revision-build` / `GET /api/revision-pdf` accept
  `&pin=`; build statuses add `scope`, `pin`, `source`, `hunks`, `other` (never stored, so responses without `pin` stay
  as in 0.2.2); the scoped patches are cut at 256 KiB with `truncated` / `other_truncated`.
- **Viewer.** A pin's source diff shows only its hunks, with "N other changes in this commit ▸" folded below (expands in
  place). Its comparison PDF is old + only its hunks, run through the same bwrap latexdiff/latexmk pipeline and cached
  per (pin, commit, hunk set); one toggle [Whole commit] switches to the whole-commit comparison. If the pin's hunks
  alone do not compile, the whole commit is shown with a one-line note. A commit that is entirely the pin's looks as in
  0.2.2, with no extra control.
- Recorded `changes` count only on the commit `close_ref` names (hash, or the squash/merge commit found by PR number);
  on any other commit the view is inferred, and the viewer scopes only the commit it picked for the pin. The
  comparison cache is keyed by (commit, block set) and counts pin-scoped entries apart; transient read failures are
  not cached; symlink and submodule entries are never read as text.
- Rolling back to 0.2.2 is safe: 0.2.2 ignores the `changes` field, and the new cache entries expire on their own.

## 0.2.2 — 2026-09-25

One [Reply], a Trash, and collapsible list sections ([issue #8](https://github.com/dartworklabs/limn/issues/8),
decision record [ADR-0004](docs/adr/0004-one-reply-trash-sections.md)). The `pins.md` format is unchanged and the HTTP
API changes are additive. One agent-visible behaviour changes; it is listed first.

- **A person's reply on a closed pin reopens it (agent-visible).** `POST /api/pins/{id}/reply` decides by one server
  rule: a reply by a person on a pin awaiting review or done reopens it, and the reply becomes the reason
  (`ev:"reopen"`, exactly as `/reopen`), so the pin returns to the open table of `pins.md` with `다시 열림` and
  `다시 연 이유(<name>): <reply>`. A reply that @-tags a person keeps the state (that person gets a `mention`); replies
  on open pins and question pins never change state; an agent's reply (token, headerless loopback, agent role) never
  reopens by the rule. Optional `"reopen": true|false` overrides the rule (`400` if not a boolean); the response adds
  `reopened` and `state`. `/reopen` is kept.
- Viewer: the review card is `[변경 보기] [답글] [확인]` and a done row offers `[답글]`; the `[다시 열기]` buttons are gone.
  A line under the reply box previews the outcome ("Sending will reopen this pin for the agent", "Sending notifies Bob
  Park; state stays", …), with one rarely used override toggle: `[상태 유지]` (Keep state) where the rule reopens,
  `[다시 열기]` (Reopen) where it keeps the state. A reply is sent when its undo toast goes away, so `[되돌리기]` (Undo)
  takes it back before anyone sees it. Tagging an agent-role account is not tagging a person; a reopening reply still
  notifies everyone tagged on the pin before (`replied`).
- **Trash.** Deleted pins leave the list at once (with Undo) and live in `[⋯] → 휴지통 N` (desktop: a link under the
  list) for 30 days, with Restore. Older entries are hidden and purged at startup and on every drop/restore. New
  owner-only `POST /api/pins/{id}/purge` deletes one for good (`purged` audit event). When someone else deletes your pin
  you get a `dropped` notification with Restore. A `#12` that points at a deleted pin reads "#12 deleted pin".
  `GET /api/pins/dropped` adds the computed `expires_ts`. A long-running server also drops expired entries during
  `GET /api/pins` / `GET /pins.md` at most once an hour (the light poll stays write-free).
- Fixed (older than 0.2.1): on an instance with several documents, a `/#doc=<key>&pin=<n>` link lost the pin on load,
  so a notification clicked with no tab open did not open the pin. The boot now reads the link first; the `[되살리기]`
  action of a `dropped` notification opens the link with `&act=restore`, which restores the pin and opens it.
- Open pins, awaiting review and done share one collapsible header (click/Enter/Space, `aria-expanded`), remembered per
  device; done starts collapsed; a collapsed header shows "new N".
- Help defines a pin once: a place in the output + a request or question + its conversation.
- **What the preview says is what happens.** The preview and the request resolve @-tags with the same hints, so an
  autocompleted name edited down to an ambiguous first word previews the server's decision. The override is a switch
  whose label is the non-default outcome, and the preview still names who is notified when it is on; the placeholder
  follows the same outcome. A failed send reopens the box with the draft and an inline error; Ctrl+Enter moves focus to
  [되돌리기]. A `#…&pin=N&act=restore` link runs once (the address is cleaned at once).
- `pins.md`: one more additive line after the token line (`REPLY_GUIDANCE`): an agent sending as a person without a token
  sends `"reopen": false` with replies. The same note is in SKILL and api.md.
- Tests: `tests/test_v022.py` (the rule table, API, Trash with a fake clock, cold deep links, the real input pipeline from
  text and autocomplete to the server's decision, and browser flows on desktop, fold and phone in ko/en). Decision
  record ADR-0004 is accepted.

## 0.2.1 — 2026-09-25

Fixes from the end-to-end QA of 0.2.0. Two changes affect the agent contract; both are listed first.

- **Headerless requests through the tailnet address are refused (contract change).** Under `--auth tailscale`, a request
  without identity headers that came through `tailscale serve` (`Host` `*.ts.net` or a `--public-host`, e.g. from a
  tagged device) used to be treated as the loopback agent, which could do everything but confirm. It now gets `403`
  (a proxied request is recognised by a non-loopback Host or any `X-Forwarded-*`/`Forwarded` header, which
  `tailscale serve` always sets — Host alone can be spoofed because serve routes by the TLS name)
  with a hint to send a token, as 0.1 did when `--allow` was set. **Remote agents on tagged devices or CI must send
  `Authorization: Bearer <token>`**; agents on a machine signed in to the tailnet as a person keep working (they carry
  that person's identity and still send `"review": true` when closing), and loopback agents are unchanged.
  `--tailnet-agent` (`TAILNET_AGENT=1`) restores the 0.2.0 behaviour on purpose (logged as deprecated).
  Decision record: [ADR-0003](docs/adr/0003-tailnet-headerless-and-owner-clear.md).
- Hardening from the security review: `X-Real-IP`, `X-Forwarded-Port` and `Via` also mark a proxied request; under
  `--auth local` a proxied request is `403` instead of the owner; `people.json` is written `0600` and an older file
  that others can write is tightened at startup. A raw TCP forward that adds no header stays indistinguishable from a
  local request (SECURITY.md) — use tokens and `AGENT_LOOPBACK=0` there.
- **`POST /api/clear` is owner-only and needs a confirmation (contract change).** Editors, viewers and every agent get
  `403`; the owner must send `{"confirm": "clear all pins"}` (else `400`). The `.jsonl.bak` archive is kept, the
  response adds `cleared` and `archive`, and a `cleared` event records who did it. The viewer never used it.
- **@mentions notify every time.** A person tagged earlier on a pin got nothing when tagged again in a reply or reopen
  reason. Now every @-tag in a reply or reopen reason is a `mention` for that person (never the poster), everyone else
  involved gets `replied` (`reopened` for the author), and nobody gets both for one post. A note edit notifies people
  whose @-tag occurs more often than before (a typo fix stays quiet; `note_append` with `@name` notifies).
- `pins.md`: a new line after the close instruction shows how to claim a pin (`/api/pins/N/claim` with `eta_min`,
  `409` = taken, `/unclaim` to give up); the token line says remote agents must use a token. Both are additive lines.
- Viewer: the viewer role no longer sees edit/reply/close/drop/reopen/confirm/rebuild/save controls (the server already
  refused them) and the composer says why; `[질문으로 보내기]` keeps focus in the memo and Ctrl+Enter saves from anywhere
  in the composer; the section strip shows the first section at the very top of page 1 instead of the last heading on
  the page (it now uses the heading's position on the page); a browser refused on `GET /` gets a short ko/en page
  instead of raw JSON.
- CLI: `limn member add` rejects logins with whitespace (the server's `valid_login` now does too, the same rule as
  `--local-user`); `limn member list` no longer says a role is "recorded on first visit"; `limn serve --port N` on a
  busy port prints one line and exits 1 instead of a traceback.
- Docs: `limn update` has defaulted to the https source since 0.1.1; 0.1.0 defaulted to SSH, so the first update from
  0.1.0 still fetches over SSH (`docs/handbook/instances.md` §업데이트와 되돌리기 shows the https override). An endpoint audit, the
  principal x entry path x operation matrix and the new behaviour are covered by `tests/test_qa_021.py`.
- Documentation moved into a Korean System Handbook (`docs/handbook/`) with decision records
  (`docs/adr/`). The former `docs/design.md`, `docs/build-sync.md`, `docs/api.md`,
  `docs/operations*.md`, `docs/instances*.md` and `docs/design/access-and-sync*.md` are its chapters
  now; the access-control draft is ADR-0002. The documentation move itself changes neither `pins.md` nor the HTTP API.
- Roadmap for aligning the code with the team coding rules: `docs/handbook/code-style-roadmap.md`.

## 0.2.0 — 2026-09-25

Access control, stage v0.2 of [ADR-0002](docs/adr/0002-access-control.md). An existing
0.1 instance (no `AUTH`, no `tokens.json`, `people.json` without roles) behaves exactly as before; the only
visible difference is a deprecation warning in the server log and one added guidance line in `pins.md`.

- **Identity providers** (`--auth`, config `AUTH=`): `tailscale` (default — the 0.1 behaviour; the
  `Tailscale-User-*` headers are now trusted only from a loopback TCP peer), `local` (a single user on their own
  machine: every loopback request is the owner), `trusted-proxy` (configurable user/name/e-mail headers, trusted
  only from `--trusted-proxies`; everything else is `401`).
- **Agent API tokens**: `limn token create|list|revoke <instance>` (or `--state-dir`). Sent as
  `Authorization: Bearer <token>`, accepted by every provider, stored as SHA-256 hashes in `<state>/tokens.json`
  (mode 0600), shown once, revocable without a restart. Token principals are `agent:<name>` and follow the agent
  contract (close goes to review, never confirm, never recorded in `people.json`).
- **Headerless loopback agent** kept by default under `tailscale` but deprecated (warning at startup and on the
  first such request); `--no-agent-loopback` / `AGENT_LOOPBACK=0` turns it off. Always off under `local`,
  `trusted-proxy` and on a non-loopback bind, where asking for it refuses to start.
- **Member roles** in `people.json` (`owner`, `editor`, `viewer`, `agent`; missing = `editor`), enforced once in
  the handler: viewers may only read and run `/api/pick`/`/api/revision-build`, agents may not confirm.
  `limn member add|list|remove|role <instance>`; changes apply without a restart. `--members-only`
  (`MEMBERS_ONLY=1`) admits only listed people (and `--allow`). Without an allowlist, unknown tailnet people are
  still auto-added as editors. `/api/people` entries and `me` carry an additive `role`.
- **Binding**: `--bind` (`BIND=`, default `127.0.0.1`). A non-loopback address refuses to start unless
  `--auth trusted-proxy`, or `--i-know-this-is-insecure` (loud warning). `--public-host` (`PUBLIC_HOSTS=`) adds
  names accepted as Host/Origin and used as the `pins.md` base URL. The startup log gains an `auth` line.
- **Instance manager**: `limn run` maps and validates the new config keys (a 0.1 config gives the same argv);
  `limn add --auth`; `limn doc add|remove` keep the access keys; `tailscale serve` is refused for `AUTH=local`
  and `AUTH=trusted-proxy`.
- Docs: SECURITY.md threat model, README security note, instances/operations guides, API §Authentication, skill
  (where an agent's token comes from).

## 0.1.1 — 2026-09-25

English UI finished; no change to the agent contract (`pins.md`, HTTP API) or to the Korean UI.

- Composed UI strings (page counts, "awaiting review N", "<name>'s review", relative times, "show N earlier",
  claim and build status, toasts, tooltips, the tab title) go through the message table with parameters and
  plural forms (`tl('{n}쪽', {n})`), so `?lang=en` leaves no Korean chrome. Stored names such as the local agent's
  are shown in the UI language. Document tab names, notes, replies and the manuscript stay as written.
- The desktop toolbar fits one row at the default 348px panel width in both languages (the page field shrinks
  before anything wraps; its English placeholder is "Page").
- New browser test: the real viewer in English against an in-process server must show no Hangul outside user
  content (desktop, fold and phone), the toolbar stays on one row in both languages, and Korean stays as it was.
- Install and `limn update` use the public `git+https://github.com/dartworklabs/limn` source (SSH still works
  through `LIMN_REPO`).

## 0.1.0 — 2026-09-25

First standalone release. Mechanical move of the app and its instance manager into this repository,
with history from both sources preserved (see README, History).

- Package `dartwork-limn` with the `limn` command: `limn serve`, `limn version`, instance management
  (`limn add|start|stop|update|list|status|url|snippet|doc|remove|run`) and `limn migrate`.
- Former names replaced by Limn: systemd unit `limn@<name>`, config `~/.config/limn/<name>.env`,
  data `~/.local/share/limn/`, environment variables `LIMN_*`. `limn migrate` moves instances from the
  former `pin-viewer` install (config copy, optional state move, printed systemd switch commands).
- `limn update` reinstalls through `uv tool` (latest tag or `--ref`), restarts running instances, and
  prints the rollback command; `--dry-run` shows the plan.
- `GET /api/version` and `limn serve --version`.
- Viewer UI: English message table alongside Korean (`?lang=`, saved preference, browser language).
- The `pins.md` format and the HTTP API are unchanged.
