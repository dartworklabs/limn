# Security

> **Warning:** Limn has no built-in authentication yet. Never expose it beyond loopback except through a
> private network you trust or an authenticating proxy. Planned access control is described in
> [docs/design/access-and-sync.md](docs/design/access-and-sync.md).

## Threat model in one paragraph

Limn has **no authentication of its own, by design**. The server binds to `127.0.0.1` only (hard-coded,
no flag to change it). Anyone who can reach the port can read the manuscript PDF and source excerpts
and create, edit or close pins. It is meant to be exposed only through a **private network you trust**,
such as `tailscale serve` on a tailnet — never through a public reverse proxy, never through
`tailscale funnel`. On a tailnet, `tailscale serve` adds identity headers (`Tailscale-User-Login`, ...)
that Limn uses to attribute pins and to require a human for confirming reviews; it does not block
tailnet members (they are trusted collaborators). `--allow` restricts which tailnet logins may use an
instance.

What the server does defend against:

- DNS rebinding and cross-site requests: `Host` and `Origin` are checked (`--no-origin-check` turns
  this off; use it only if `tailscale serve` forwards unexpected values).
- Path traversal: static files are limited to the vendored PDF.js files by name.
- Requests that arrive through a `*.ts.net` host without identity headers (e.g. tagged devices) are refused.

## Reporting a vulnerability

Please report security issues privately via GitHub's "Report a vulnerability" (Security → Advisories)
on this repository rather than in a public issue. Include the Limn version (`limn version`), how the
instance is exposed, and steps to reproduce. We aim to acknowledge reports within a week.
