# Security

> **Warning:** Never expose Limn beyond loopback without an identity provider in front of it: keep the
> default `127.0.0.1` and share it through a private network you trust (`tailscale serve`), or run it
> behind an authenticating proxy with `--auth trusted-proxy`. Never through `tailscale funnel`.
> The design is [docs/design/access-and-sync.md](docs/design/access-and-sync.md).

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
- Requests that arrive through a `*.ts.net` host without identity headers (e.g. tagged devices) are refused when
  `--allow` or `--members-only` is set.

What it does not: a `local` or `tailscale` instance trusts every process on the same machine that can reach
loopback. On a shared machine, give agents tokens, turn off the loopback agent, and use `--members-only`.

## Reporting a vulnerability

Please report security issues privately via GitHub's "Report a vulnerability" (Security → Advisories)
on this repository rather than in a public issue. Include the Limn version (`limn version`), how the
instance is exposed, and steps to reproduce. We aim to acknowledge reports within a week.
