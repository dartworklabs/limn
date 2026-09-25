# Changelog

## 0.3.0 — unreleased

Pin-scoped [View changes] ([issue #9](https://github.com/dartworklabs/limn/issues/9), decision record
[ADR-0005](docs/adr/0005-pin-scoped-changes.md)). The HTTP API changes are additive. One `pins.md` line changes: the close
instruction; everything else in `pins.md` is byte-for-byte the same.

- **Agents: one commit per pin (agent-visible).** The close instruction in `pins.md` and the skill now ask for one commit
  per pin (one PR may hold several) and `ref` = that pin's commit hash, so the commit is the pin and both diffs are scoped
  for free. Nothing enforces it; old agents keep working.
- **`changes` on close (additive).** `POST /api/pins/{id}/close` takes an optional `changes: [{file, lo, hi}]`, the
  new-side line ranges the agent changed for this pin (`file` relative to the manuscript folder like the `pins.md`
  location column, or absolute inside it). Invalid shapes are `400` and change nothing; `[]` is the old close. Stored on
  the pin as `changes` (absolute paths) on the first close, kept on re-close, cleared by reopen; exposed in the pins API.
- **Inference for everything else.** For a pin without `changes` (or whose `changes` hit nothing in the commit) the
  server picks the commit's hunks that overlap the pin's range mapped through the commit (its anchor on the new side,
  else the old side; renames followed). If nothing overlaps, the view is the whole commit, as before.
- **API (additive).** `GET /api/revision-diff?pin=<id>` adds `scope: {pin, mode, source, hunks, other, diff, other_diff}`;
  `POST /api/revision-build` accepts `pin` in its body, and `GET /api/revision-build` / `GET /api/revision-pdf` accept
  `&pin=`; build statuses add `scope`, `pin`, `source`, `hunks`, `other`. Without `pin` every response is unchanged.
- **Viewer.** A pin's source diff shows only its hunks, with "N other changes in this commit ▸" folded below (expands in
  place). Its comparison PDF is old + only its hunks, run through the same bwrap latexdiff/latexmk pipeline and cached
  per (pin, commit, hunk set); one toggle [Whole commit] switches to the whole-commit comparison. If the pin's hunks
  alone do not compile, the whole commit is shown with a one-line note. A commit that is entirely the pin's looks as in
  0.2.2, with no extra control.
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
