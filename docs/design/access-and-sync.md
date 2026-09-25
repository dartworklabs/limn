# Access control, collaboration boundaries and sync

Status: v0.2 implemented in Limn 0.2.0 (2026-09-25) — identity providers, agent tokens, member roles, bind rule
([api.md](../api.md) §Authentication, [instances.md](../instances.md) §Access). Later stages remain a draft.
Korean version: [access-and-sync.ko.md](access-and-sync.ko.md). The Problem section describes v0.1.

## Problem

Limn has no authentication of its own today. A private network (a Tailscale tailnet) is the gate, and the server trusts the identity headers Tailscale adds on loopback. Anyone who can reach the port is a collaborator, and any unauthenticated loopback request is treated as the agent.

That is fine for one lab on one tailnet. It does not let a user:

- invite a coauthor who is not on the tailnet,
- restrict a project to named people,
- run Limn anywhere other than a machine they control on a private network,
- give an agent access without giving it everything.

## Decision (draft)

Access is enforced **by the application, not the network**. Limn does not build or operate a VPN. A tailnet stays a supported way to self-host, not a requirement.

Three layers, each replaceable on its own:

### 1. Identity: who is this request?

One interface, several providers, chosen per instance:

| Provider | Use | How identity is established |
|---|---|---|
| `local` | single user on their own machine | everything on loopback is the owner |
| `tailscale` | today's lab setup | `Tailscale-User-*` headers, trusted on loopback only |
| `trusted-proxy` | self-hosted behind oauth2-proxy, Cloudflare Access, etc. | configured header names, trusted only from configured proxy addresses |
| `oidc` | self-hosted or hosted, no VPN | GitHub / Google (any OIDC) login, server-side session cookie |

**Agents** authenticate with **per-project API tokens** (scoped, revocable, hashed at rest), not with "no header on loopback". This is the first thing to fix before Limn is reachable from anywhere but loopback.

### 2. Authorization: may they do this, in this project?

- `people.json` grows into a project **member list** with roles:
  - `owner`: settings, members, tokens
  - `editor`: pins, replies, confirm/reopen
  - `viewer`: read only
  - `agent`: token principals with the agent contract's permissions (claim, reply, close into review; never confirm)
- Joining is by email allowlist or an expiring invite link.
- "Only allowed users collaborate" is solved here, whatever the network.

### 3. Sync: where does the truth live?

- **Default: one authoritative server per project.** Browsers and agents talk to it. Polling becomes SSE/WebSocket push for live updates.
- **Later, optional: git-backed pins.** Pins and threads live in the manuscript repo under `.limn/`, one append-only event log merged by id and revision. Collaborators already share the repo, so sync needs no extra service. The cost is that it is not real-time. The existing `events.jsonl` is already append-only, which makes this a small step.
- **Later: replication between instances** over the same event log, if a real need appears.

## Hosted product (Limn Cloud), for later

- Workspaces, members, SSO, notifications and real-time sync, hosted by Dartwork.
- Builds may stay on the user's machine. `limn connect` opens an outbound connection to the cloud, which relays PDFs and pins back through it, the same principle as ngrok or Cloudflare Tunnel. No inbound ports and no VPN, and manuscript sources need not leave the lab.
- Fits the AGPL-3.0 + commercial licence model: self-hosting stays free, the hosted service and commercial licences are the product.

## Roadmap

| Stage | Scope |
|---|---|
| v0.2 (**implemented**, 0.2.0) | identity provider interface (`local`, `tailscale`, `trusted-proxy`); agent API tokens; member roles on `people.json`; startup warning + README warning: never expose without an auth provider. Also: `--bind` refused off loopback unless `trusted-proxy`, `--members-only`, `--public-host`; the headerless loopback agent is kept but deprecated. Invites stay for v1.0; owner-only operations are CLI-level for now |
| v0.3 | live updates over SSE; audit of state-changing endpoints against roles |
| v1.0 | `oidc` provider, sessions, invite links; HTTPS self-hosting guide (Caddy, Cloudflare Tunnel) |
| later | `.limn/` git-backed pins; `limn connect` + Limn Cloud |

## Non-goals

- Running a VPN or coordination server (Headscale, embedded tsnet) as part of the product.
- Multi-tenant hosting inside the open-source server itself; that belongs to the hosted service.

## Compatibility

The agent contract (`pins.md`, HTTP API fields, pin states) does not change in v0.2. Tokens change how an agent authenticates, not what it reads or writes. The paper-repo instructions will gain one line: where the token comes from.
