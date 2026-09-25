# Changelog

## 0.2.1 — 2026-09-25

Fixes from the end-to-end QA of 0.2.0. Two changes affect the agent contract; both are listed first.

- **Headerless requests through the tailnet address are refused (contract change).** Under `--auth tailscale`, a request
  without identity headers that came through `tailscale serve` (`Host` `*.ts.net` or a `--public-host`, e.g. from a
  tagged device) used to be treated as the loopback agent, which could do everything but confirm. It now gets `403`
  with a hint to send a token, as 0.1 did when `--allow` was set. **Remote agents on tagged devices or CI must send
  `Authorization: Bearer <token>`**; agents on a machine signed in to the tailnet as a person keep working (they carry
  that person's identity and still send `"review": true` when closing), and loopback agents are unchanged.
  `--tailnet-agent` (`TAILNET_AGENT=1`) restores the 0.2.0 behaviour on purpose (logged as deprecated).
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
