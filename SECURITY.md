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
- Path traversal: static files are limited to the vendored PDF.js files by name.
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

## Reporting a vulnerability

Please report security issues privately via GitHub's "Report a vulnerability" (Security → Advisories)
on this repository rather than in a public issue. Include the Limn version (`limn version`), how the
instance is exposed, and steps to reproduce. We aim to acknowledge reports within a week.
