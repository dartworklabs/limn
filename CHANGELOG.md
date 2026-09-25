# Changelog

## 0.2.0 — unreleased (tagged after merge)

Access control, stage v0.2 of [docs/design/access-and-sync.md](docs/design/access-and-sync.md). An existing
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
