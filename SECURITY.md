# Security

> **Warning:** Never expose Limn beyond loopback without an identity provider in front of it: keep the
> default `127.0.0.1` and share it through a private network you trust (`tailscale serve`), or run it
> behind an authenticating proxy with `--auth trusted-proxy`. Never through `tailscale funnel`.
> The design is [ADR-0002](docs/adr/0002-access-control.md) (Korean).

## Threat model in one paragraph

Since v0.2 Limn decides **who a request is** with an identity provider chosen per instance (`--auth`), and
**what they may change** with roles in `people.json`. `tailscale` (the default, identical to v0.1) trusts the
`Tailscale-User-*` headers that `tailscale serve` adds, and only from a loopback TCP peer; everyone on the
tailnet who reaches the port is a collaborator unless `--allow` or `--members-only` narrows it. `local` treats
every loopback request as the owner — for a single user on their own machine, never exposed. `trusted-proxy`
trusts configured identity headers only from `--trusted-proxies` addresses (oauth2-proxy, Cloudflare Access, …)
and refuses everything else with `401`. Agents authenticate with **API tokens** (`limn token create`, sent as
`Authorization: Bearer`, stored as SHA-256 hashes in a `0600` file, revocable without a restart); a valid token
wins over headers and an invalid one is a `401`, never a fallback. Roles: `viewer` may only read (and run
`/api/pick` / `/api/revision-build`), `agent` may do everything except confirm, `editor` and `owner` everything a
person could in v0.1 (a person without a role is an editor). The server binds `127.0.0.1` by default; a
non-loopback `--bind` refuses to start unless the provider is `trusted-proxy` or `--i-know-this-is-insecure` is
given (which prints a loud warning). The v0.1 rule that a headerless loopback request is the agent still holds
under `tailscale` for compatibility, but is deprecated (`--no-agent-loopback` turns it off) and is always off
under `local`, `trusted-proxy` and on a non-loopback bind.

What the server does defend against:

- DNS rebinding and cross-site requests: `Host` and `Origin` are checked (loopback, `*.ts.net`, and names given
  with `--public-host`; `--no-origin-check` turns this off — use it only if a proxy forwards unexpected values).
- Forged identity headers: they are ignored unless the TCP peer is loopback (`tailscale`) or a configured proxy
  (`trusted-proxy`).
- Path traversal: static files are limited by name to the vendored PDF.js modules and the vendored Pretendard font
  slices and stylesheet: one name in the folder, no subpath, with a suffix the folder serves.
- Reading files that are not manuscript: every route that takes a file name (`/api/snippet`, `/api/overlaps`, a new
  pin, an edit's `loc`, a close's `changes`) accepts only files under `--manuscript`, symlinks resolved, and never one
  under a dot-named part of it (`.git`, `.env`, `.ssh`, `.latexmkrc`, …): those hold repository and machine secrets,
  not manuscript text, and a `viewer` could otherwise read `.git/config` through a snippet. The refusal is the one for
  a file outside the manuscript (`400 file_outside_manuscript` / `change_outside_manuscript`).
- The state folder is never manuscript. Keep `--state-dir` outside `--manuscript` (the default and `limn add` do). If
  it points inside, under any name, the routes above refuse every file in it the same way — `people.json`,
  `tokens.json` (hashes), `audit.jsonl`, `events.jsonl` and the pin files — also through a link, the build copy leaves
  it out, and the server prints one warning at startup; keep such a folder out of git and file sync. A state folder
  that would hold a served document's main file (the manuscript folder itself, say) refuses to start.
- Roles, identity providers and how a principal was identified are closed types in the code, so a mistyped comparison
  fails the type check; a `people.json` role Limn does not know is a `viewer`.
- An unusable `people.json` fails closed. If it exists but cannot be read or is not a Limn people file (truncated,
  empty, invalid JSON, wrong shape, no read permission), every person identified by a header is a `viewer`,
  `--members-only` admits no one from it (only `--allow` logins, which do not depend on the file), and the server never
  rewrites it — it used to read such a file as empty and replace it with the one visitor, erasing every role including
  the owner's. One warning goes to stderr; once the file is fixed (content or permissions) the roles apply again on the
  next request, without a restart. Tokens and the `--auth local` owner do not read the file and are unaffected. Keeping
  the roles of an earlier good read was rejected: the result would depend on the process's history, and an unreadable
  `tokens.json` likewise accepts no token.
- Clickjacking: every response carries `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors 'none'`
  (no other CSP directive, so the viewer's inline scripts are unaffected). Page images and PDFs are
  `Cache-Control: private`, never kept by a shared cache.
- Requests that arrive through `tailscale serve` without identity headers (a `*.ts.net` or `--public-host` Host, e.g.
  tagged devices) are refused (`403`) since v0.2.1 — only a request that names this machine (a loopback Host) and
  carries no proxy header (`X-Forwarded-For/-Host/-Proto/-Port`, `X-Real-IP`, `Forwarded`, `Via`) can be the
  headerless agent. Host alone is not trusted for this: `tailscale serve` routes by the TLS name and passes the
  client's Host through, but always sets `X-Forwarded-For`. `--tailnet-agent` restores the v0.2.0 behaviour, and never
  past `--allow` or `--members-only`. Under `--auth local`, a request that came through a proxy is refused too (the
  owner is whoever sits at this machine).
- `people.json` (logins and roles) is written with mode `0600`, like `tokens.json`; an older file that others can
  write is tightened to `0600` at startup.
- Bulk deletion: `POST /api/clear` (archive and empty every pin) is refused to everyone but the `owner` role and
  needs an explicit confirmation body; it keeps a backup and records who did it (since v0.2.1).

Agents on the machine that serves an instance keep its token in a **token file**,
`~/.config/limn/<instance>.token`, written once by `limn token create <instance> --save`: mode `0600` (folder `0700`),
never in a repository (the command refuses a folder inside a git work tree that does not ignore the file), the
token not printed unless `--print`. They send it with `curl -H "Authorization: Bearer $(cat ~/.config/limn/<instance>.token)"`;
the instance manager's own checks pass it to curl on stdin, only when every process listening on the instance's
port belongs to this account (so another account that grabs the port while the instance is down gets nothing), and
skip a token file that is a symlink, belongs to another account, or is open to group/others. Agents face that same
risk while an instance is down: on a machine other accounts use, keep instances up (the unit restarts on failure) or
check that the port's listener is this account's before sending the token
(`lsof -a -u "$(id -u)" -iTCP:<port> -sTCP:LISTEN`). The server only checks that the file exists (it never reads it) to
tell agents about it in `pins.md`. `limn token revoke` removes the file when it held the revoked token. Once the
agents use the file, set `AGENT_LOOPBACK=0` on that instance: only this account's processes can then act as the
agent. A token expanded with `$(cat …)` is visible on that curl's command line while it runs; on a machine other
accounts use, pipe it instead: `printf 'Authorization: Bearer %s\n' "$(cat <file>)" | curl -H @- …`. The design is
[ADR-0007](docs/adr/0007-agent-token-file.md) (Korean).

What it does not: a `local` or `tailscale` instance trusts every process on the same machine that can reach
loopback. On a shared machine, give agents tokens, turn off the loopback agent, and use `--members-only`. A raw TCP
forwarder that adds no header — `tailscale serve --tcp` or `--tls-terminated-tcp`, `ssh -L`/`-R`, a plain port
forward — is indistinguishable from a local request, so whoever reaches it is the loopback agent (or, under
`--auth local`, the owner). The supported path, `limn add`/`limn start`, only uses `tailscale serve --https`. If you
forward the port any other way, give agents tokens and set `AGENT_LOOPBACK=0` (`--no-agent-loopback`), and do not use
`--auth local`.

## The manuscript repository is trusted code

Limn builds the manuscript with the rights of the account that runs the server. The main build runs
`latexmk -pdf -synctex=1 -interaction=nonstopmode` in a copy of the manuscript **without** `-norc` and without a
sandbox, so a `latexmkrc` / `.latexmkrc` in the repository (Perl) runs as that account, and TeX runs with your
distribution's default shell-escape setting. Whoever can push to the manuscript repository can therefore run code on
the server: with `--git-pull`, a push to the remote `main` is fetched and built within about a minute, with no one
pressing rebuild. Only point Limn at repositories whose pushers you trust, and run it under an account that holds
nothing else worth taking (other repositories' credentials, unrelated token files).

Comparison builds (`/api/revision-build`) are different: they compile past commits inside a `bwrap` sandbox with
`latexmk -norc -no-shell-escape`, with no home directory, source repository or network. Running the main build the
same way (`-norc`, a sandbox) may become an opt-in later; this is a possibility, not a promise, and nothing changes
today — some manuscripts rely on their `latexmkrc`. The details are in
[build-sync.md](docs/handbook/build-sync.md) (Korean).

## Reporting a vulnerability

Please report security issues privately via GitHub's "Report a vulnerability" (Security → Advisories)
on this repository rather than in a public issue. Include the Limn version (`limn version`), how the
instance is exposed, and steps to reproduce. We aim to acknowledge reports within a week.
