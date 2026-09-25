English | [한국어](operations.ko.md)

# Operations — running, security, deployment, and the viewer

Open this when standing up the server, exposing it, or running it persistently. Covers the full set of command-line arguments, port avoidance, security constraints, systemd, `tailscale serve`, state files, and how to use the viewer as a user.

## Requirements

Python 3.10+, standard library only (no external packages, CDN, or build step — the viewer's vector renderer, PDF.js, ships inside the package at `src/limn/vendor/pdfjs/` and is served by default). Runs fine on a system Python 3.10 with no virtual environment. External tools: `latexmk`, `synctex`, `pdftoppm`, `pdftotext`, and `rsync` if available.

The regression tests never open a port (they use socketpair): `uv run python3 -m unittest discover -s tests` (from the repository root).

## Command-line arguments

```bash
limn serve \
  --manuscript <manuscript_dir> \
  [--main <main-file>.tex] \
  [--port <port>] \
  [--state-dir <state_dir>] \
  [--dpi 150] \
  [--float-envs figure,table,algorithm,equation,align,itemize,enumerate,minipage] \
  [--build-timeout 900] \
  [--no-build] \
  [--allow <login>,<login>] \
  [--no-origin-check] \
  [--git-pull] \
  [--pdfjs-dir <dir>] \
  [--label <label>] \
  [--accent <#rrggbb>] \
  [--doc <key>=<display name>:<path> ...] \
  [--auth tailscale|local|trusted-proxy] [--no-agent-loopback | --agent-loopback] \
  [--bind <addr>] [--i-know-this-is-insecure] [--public-host <name[:port]>,...] \
  [--trusted-proxies <ip/cidr>,...] [--proxy-user-header <h>] [--proxy-name-header <h>] [--proxy-email-header <h>] \
  [--members-only] [--local-user <login>] \
  [--version]
```

| Argument | Required | Default | Description |
| --- | --- | --- | --- |
| `--manuscript` | Yes | — | The LaTeX source root directory (`<manuscript_dir>`). Never hardcode this — it differs per project. A pin can only point at a file inside this tree |
| `--main` | No | Auto-detected | The top-level `.tex` filename to build. If omitted, looks for a `.tex` file containing `\documentclass` under `--manuscript`. With 0 or 2+ candidates, prints the candidate list and exits with an error — it never guesses. Fails to start if combined with `--doc` |
| `--doc` | No | (none = single document) | A document selectable in the viewer. Repeatable. The first one is the default. Format and rules are in §Multiple documents |
| `--port` | No | Auto-selected | If unspecified, finds and uses a free port per §Port conflict avoidance and prints the chosen port to the startup log |
| `--state-dir` | No | `${XDG_DATA_HOME:-~/.local/share}/limn/serve/<slug>` | `<slug>` is a normalized hash of `--manuscript`'s absolute path — so opening manuscript A and B at once on the same machine never mixes their state (safe for multiple manuscripts/worktrees). A persistent (systemd) instance managed with `limn add` instead defaults to `~/.local/share/limn/<name>` (instances.md) |
| `--dpi` | No | `150` | Page PNG render resolution. The viewer draws the PDF as a vector (§Using the viewer), so the PNG is only used for the first paint and as a fallback |
| `--float-envs` | No | `figure,table,algorithm,equation,align,itemize,enumerate,minipage` | The list of `\begin{...}` names whose default scope level is "environment" (the ladder itself considers every environment, [design.md](design.md) §Scope ladder) |
| `--build-timeout` | No | `900` | The `latexmk` build timeout, in seconds. Past it, the whole process group is killed and it's judged `fail` |
| `--no-build` | No | (off) | Skips the rebuild at startup. Used to bring the server up quickly when output already exists — if there's no PDF or page images yet, it builds regardless of this flag |
| `--allow` | No | (empty = everyone allowed) | A comma-separated allowlist of tailscale logins. If set, a request **with** a `Tailscale-User-Login` header outside the list gets `403`. A header-less request over a loopback `Host` (an agent's `curl`) is always allowed. A header-less request over a `*.ts.net` `Host` gets `403` — tailscale never attaches identity headers to **tagged devices** (or funnel), and treating those as local would bypass the list. With `--allow` empty, a tagged-device request is also recorded as `local/agent` (`로컬/에이전트`) |
| `--no-origin-check` | No | (off) | Turns off `Host`/`Origin` checks (DNS-rebinding/CSRF defense, §Host/Origin checks). **An escape hatch only** — use it only when real `tailscale serve` sends an unexpected `Host`/`Origin` (a MagicDNS short name, a custom user domain that isn't `*.ts.net`) and every UI request comes back `403`. Turning it on logs a warning at startup |
| `--git-pull` | No | (off) | Checks the remote main right after startup and every 60 seconds, fast-forwarding and rebuilding the LaTeX PDF on a new commit. A manual rebuild also pulls upstream `--ff-only` before copying. If auto-sync is blocked by a dirty tree, a divergence, or a missing upstream, the reason is shown on screen ([build-sync.md](build-sync.md) §`--git-pull`) |
| `--pdfjs-dir` | No | The bundled `src/limn/vendor/pdfjs/` (shipped by default) | Only needed to point the viewer's PDF.js directory (`pdf.min.mjs`·`pdf.worker.min.mjs`) somewhere else. If nothing's found at the given path, a warning is logged at startup and the viewer falls back to PNG (behavior otherwise unchanged) |
| `--label` | No | `--manuscript`'s git origin repository name (truncated with `…` past 40 characters), or the folder name if it isn't a git repository | A label to tell multiple manuscript viewers apart when several are open at once (40 characters or fewer if set explicitly — longer fails to start; HTML-escaped). Shown on the toolbar chip, tab title, favicon, and `<state_dir>/pins.md`'s header line (§Running multiple manuscript instances at once) |
| `--accent` | No | A fixed-palette color chosen by hashing the label string | The label's accent color. Only accepts `#rrggbb` format (fails to start otherwise). The same `--label` always gets the same default color unless overridden |
| `--version` | No | — | Prints the installed version and exits (matches `GET /api/version`) |

Access control (v0.2, [design](design/access-and-sync.md)). Without any of these the server behaves exactly as in v0.1.

| Argument | Default | Description |
| --- | --- | --- |
| `--auth` | `tailscale` | Identity provider. `tailscale`: `Tailscale-User-*` headers, trusted only when the TCP peer is loopback (`tailscale serve`). `local`: a single user on their own machine — every loopback request is the owner (a person, may confirm), Tailscale headers are ignored, other peers get `401`; agents must use a token. `trusted-proxy`: the `--proxy-*-header` headers, trusted only from `--trusted-proxies`; everything else without a valid token gets `401`. Every provider accepts `Authorization: Bearer <token>` (`limn token create`); a valid token wins over headers, an invalid or revoked one is `401` |
| `--no-agent-loopback` / `--agent-loopback` | on under `tailscale` | Whether a loopback request with neither identity header nor token is the agent (`로컬/에이전트`, the deprecated v0.1 behaviour; the server logs a deprecation warning at startup and on the first such request). `--no-agent-loopback` turns it off (`401`). It is always off under `local`, `trusted-proxy` and on a non-loopback `--bind`; asking for it there (`--agent-loopback`) refuses to start |
| `--bind` | `127.0.0.1` | Listen address (IPv4, IPv6 or `localhost`). A non-loopback address refuses to start unless `--auth trusted-proxy` or `--i-know-this-is-insecure`; any non-loopback bind prints a `warning` line naming the provider |
| `--i-know-this-is-insecure` | off | Start on a non-loopback `--bind` with `tailscale`/`local` anyway, with a loud warning. Only for a network you fully trust |
| `--public-host` | (none) | Public host names (repeatable or comma-separated, `name[:port]`) accepted as `Host` and as same-origin `Origin` (`https`, port 443 unless given), and used as the base URL in `GET /pins.md` |
| `--trusted-proxies` | `127.0.0.1,::1` | IPs/CIDRs whose identity headers `trusted-proxy` trusts |
| `--proxy-user-header` / `--proxy-name-header` / `--proxy-email-header` | `X-Forwarded-User` / `X-Forwarded-Preferred-Username` / none | Header names under `trusted-proxy`. The user header is required; with an e-mail header, the e-mail (when present) is the login |
| `--members-only` | off | Admit only people in `people.json` (`limn member add`) or `--allow`; others get `403` and are not recorded. Tokens and the local owner are always admitted |
| `--local-user` | `$USER`, then `owner` | The owner's login under `--auth local` |

The startup log prints an `auth` line (provider, token count, loopback agent on/off, members-only). Roles
(`people.json`): `viewer` may only read and run `/api/pick`·`/api/revision-build`; `agent` may do everything but
confirm; `editor` (the default for a person without a role) and `owner` everything. Owner-only operations —
members, tokens, settings — are CLI/file level in v0.2 (`limn member`, `limn token`); there are no owner-only HTTP
endpoints yet. Details: [instances.md](instances.md#access-tokens-and-members), [api.md](api.md#authentication).

### Differences from the design draft

This tool's design draft called for a separate `--allow-host HOST` (repeatable) to individually allow domains other than `*.ts.net`, a separate `--no-host-check` to turn off Host/Origin checks independently, and a `--log-headers` to log request headers. The actual implementation never built those three, substituting the `--allow` (a login-based allowlist) and `--no-origin-check` (turns off Host/Origin checks together) above. The allowed-Host set is `127.0.0.1`·`localhost`·`::1`·`*.ts.net` plus, since v0.2, the names given with `--public-host` — which covers what `--allow-host` was meant for.

## Multiple documents (`--doc`)

When one paper repository has several documents (body, response letter, cover letter, highlights, a view-only reviewer-comments PDF), they're served from one viewer, one address, with a document switcher. Desktop uses a picker above the PDF area; narrow mobile screens use the existing toolbar's document button. Design and rationale are in [design.md](design.md) §Multiple documents.

```bash
# The actual document list for a second paper repository (label DEMO-B)
limn serve \
  --manuscript <repository root> --state-dir <state_dir> --port <port> --git-pull --label DEMO-B \
  --doc 'ms=본문:manuscript::2nd/2nd_manuscript_en.tex' \
  --doc 'rr=답변서:submission/review_response/review_response.tex' \
  --doc 'cl=커버레터:submission/cover_letter/cover_letter.tex' \
  --doc 'hl=하이라이트:submission/highlights/highlights.tex' \
  --doc 'sub=제출본 PDF:submission/submission_ready/manuscript.pdf'
```

The body reads figures from a sibling folder via `\graphicspath{{./images/}{../1st/images/}}`, so the build root is widened to `manuscript/` (`::`) while the build itself runs in `2nd/`. Every other document just needs the one folder its `.tex` lives in. On 2026-09-23, all four LaTeX documents built cleanly (0 errors) on this machine's TeX Live 2025 — body 43 pages in 24s, response letter 111 pages in 44s, cover letter 1 page in 4s, submission PDF 27 pages rendered in 10s.

| Item | Rule |
| --- | --- |
| Format | `<key>=<display name>:<path>`. The key is everything before the first `=`; the name is everything up to the next `:`; the rest is the path |
| Key | `[a-z0-9-]{1,24}`, no duplicates. Used in the URL hash (`#doc=<key>`), the API (`doc=<key>`), and pins.md section headers. It's stored on pin records, so **a key, once set, never changes** |
| Name | Shown on the tab, in the picker list, and at the top of a pins.md section. 40 characters or fewer, no `:` |
| Path | Relative to `--manuscript` (recommended) or absolute. Either way it must be inside `--manuscript` (outside it fails to start — a pin can only point at a file inside the manuscript tree) |
| `x/main.tex` | A LaTeX document. Build root (the range copied into the build copy) = `x/`, and the build runs there too |
| `root::sub/main.tex` | A LaTeX document. Build root = `root/`, main = `root/sub/main.tex`, and the build runs in `root/sub/`. Use this when the main file reads other folders inside the build root via `../`. `::` appears at most once, and the main file must be inside the build root |
| `x/file.pdf` | View-only. No rebuild; the pages redraw when the file changes (checked every 3 seconds). Pins are page + region |
| Count | Up to 12. Alt+1…9 map to the first nine |
| No `--doc` | Behaves exactly as before — a single document (key `main`) from `--manuscript`·`--main`, with the same state-folder layout (§State file layout) |
| Startup build | With multiple documents, each builds in the background and the server comes up immediately. One document failing doesn't block startup (that tab shows an error panel). `--no-build` still skips only documents that already have pages |
| `--git-pull` | Once per repository. Rebuilding two documents at once still fetches/merges only once — the other reuses that result (`pull.shared: true`) |

**Adding a document to a single-document instance**: put the body first, as `--doc main=<name>:<body path>`. A LaTeX document with key `main` reuses the state folder's root (the old location), so build history and page images carry over, and an old pin with no `doc` field is still read as the first document (=the body). Using a different key instead means the body builds fresh under `docs/<key>/`, and old pins' marks get flipped to dotted (estimated) once.

### Contract with the instance manager

Running and managing several papers persistently (auto-wiring ports, state directories, and systemd units) is the job of the **instance manager**, not this document — `limn add|start|stop|update|list|status|url|snippet|doc|remove`, backed by systemd user units `limn@<name>`. Per-paper configuration keys (`MANUSCRIPT`·`MAIN`·`DOCS`·`PORT`·`STATE_DIR`·`LABEL`·`ACCENT`·`GIT_PULL`·`EXTRA_ARGS`, and the access keys `AUTH`·`AGENT_LOOPBACK`·`BIND`·`PUBLIC_HOSTS`·`TRUSTED_PROXIES`·`PROXY_*_HEADER`·`MEMBERS_ONLY`·`LOCAL_USER`, in `~/.config/limn/<name>.env`), how they map onto server arguments, and the procedures for adding, updating, and removing a paper are all authoritative in [instances.md](instances.md). The table above remains the source of truth for the server's own `--doc`/`--main` argument contract (format, key rules, path rules), which is unchanged.

## Port conflict avoidance (mandatory)

Always check whether a process is already using that port first. Never attempt to bind without checking.

```bash
ss -ltnp 2>/dev/null | grep ":<port> " || lsof -i tcp:<port>
```

- If it's occupied: (a) if `--port` wasn't specified, let the server try the next free port automatically, or (b) check whether the occupying process is an earlier instance of this same tool and reuse it (with the same `--manuscript`, use the existing server instead of starting a new one).
- Never kill the server with `pkill -f "limn serve"` — it can match its own command line and kill an unrelated session. Find the PID by port instead: `pid=$(lsof -ti tcp:<port>); [ -n "$pid" ] && kill $pid`.
- Leave the state directory as-is when switching to a new version. The old layout (`pages/`, `pins.jsonl`, `built_at.txt`, `head.txt`) is read fine even with `--no-build`, no rebuild needed. At startup, `pages.cur` (pointing at `pages`) and `pins.seq` (seeded from the existing max id) are created, and `<state_dir>/pins.md` is regenerated. The old `pages/` directory is replaced by the next rebuild's `pages-<build_id>/`, kept around for one more rebuild, then removed.
- **Deployment path**: `limn` is a standalone package installed with `uv tool install git+https://github.com/dartworklabs/limn@v0.2.0` — it's never run by checking out the repository and executing a script directly. `vendor/pdfjs/` installs alongside it inside the package, with nothing extra to place next to it. To move to a new version, install that version again (or run `limn update`, see instances.md) and restart persistent instances — pulling a new repo checkout without reinstalling leaves the old version running.

## Running multiple manuscript instances at once

It's expected that each paper eventually runs its own instance — a different repository, port, and tailnet address per paper. Since a single server process only ever handles one `--manuscript`, watching N papers at once means N processes.

### Concurrent execution conditions — three things that must not overlap

| Resource | Rule |
| --- | --- |
| Port | A different `--port` per instance (auto-assigned if unset, §Port conflict avoidance). Two instances can never share a port |
| State directory (`--state-dir`) | A different path per instance. The default (`<slug>` = a hash of the manuscript path) diverges automatically whenever `--manuscript` differs, but opening the same manuscript twice from different branches/worktrees gets the same slug and mixes pins — separate them explicitly with `--state-dir` in that case |
| Build folder (`<state_dir>/build/`) | Follows automatically once `--state-dir` is separated. Two `latexmk` processes hitting the same `build/` overwrite each other's `.aux` (§Build locking) |

Using `limn add <name> --manuscript <dir>` (the instance manager, instances.md) automatically separates the port and state directory per paper —
only reconcile the table above by hand when running `limn serve` directly.

### `--label` and `--accent` — telling instances apart

With several instances open, identical-looking screens are easy to mix up. `--label` (a label, defaulting to `--manuscript`'s git
origin repository name, then the folder name) and `--accent` (an accent color `#rrggbb`, defaulting to a fixed-palette
color chosen by hashing the label — the same label always gets the same color) appear in the following spots.

| Location | What's shown |
| --- | --- |
| The toolbar (the desktop sidebar header, shared across unfolded/collapsed fold as `#bar1`) | A label chip with an accent background, up front. Its width shrinks on a narrow screen but never disappears |
| The very top of the screen | A thin accent-colored stripe (4px) |
| The browser tab title | `<label> · manuscript pins · N open` |
| The favicon | The label's first character inside an accent-colored circle |
| `GET /api/meta` | The `label`·`accent`·`repo` fields (the git origin URL, or `null`) |
| `<state_dir>/pins.md`'s header (both on disk and via `GET /pins.md`) | One line after `원고:` ("manuscript:"): `논문: <label> · 저장소: <repo or (없음)>` ("paper: … · repository: … or (none)"). When `저장소` ("repository") is present, the instructions paragraph adds "confirm `git remote get-url origin` before processing, stop if it differs" (preventing the mistake of processing the wrong paper's pins) |

`--label` is truncated to 40 characters and HTML-escaped. `--accent` only accepts a 6-digit hex value after `#`; any other
format halts startup.

| Item | Rule |
| --- | --- |
| Bind address | `127.0.0.1` by default. A non-loopback `--bind` (e.g. `0.0.0.0`) only with `--auth trusted-proxy` behind an authenticating proxy; otherwise the server refuses to start (`--i-know-this-is-insecure` overrides, loudly) |
| External exposure | `tailscale serve` (provider `tailscale`) or an authenticating reverse proxy (`--auth trusted-proxy`). **`tailscale funnel` is forbidden** — funnel exposes it to the public internet |
| Verify after exposing | (1) confirm `curl` against that URL from inside the tailnet returns `200`. (2) confirm a connection from a public IP or outside the tailnet fails (i.e. `tailscale serve status` reads "tailnet only," not "Funnel") — only report it "exposed" once both are confirmed |
| Authentication | An identity provider per instance (`--auth`, default `tailscale`: the tailnet is the boundary and the headers attribute). Agents use API tokens (`limn token create`). Restrict who may enter with `--allow`/`--members-only` and what they may change with roles (`limn member`) |
| Request boundaries | The body is always read to completion before any response, and the connection is closed after an error (blocking request smuggling); `Transfer-Encoding` is rejected; a cross-origin `Origin` or unrecognized `Host` gets `403`; a POST with a body must be JSON — [api.md](api.md) §Request format and boundaries, §Host/Origin checks below |
| Paths | Pins and snippets can only ever point at a file inside the `--manuscript` tree (outside it is `400`) |
| Shutting down | Take exposure down at the end of a session with something like `tailscale serve --https=<port> off`. Whether to leave the server process running is a judgment call (reuse benefit vs. idle resource cost) |

### Host/Origin checks

- Cross-origin requests: when `Origin` is present, it's checked **based on the kind of Host** (otherwise `403`).
  - If Host is loopback, Origin must also be a loopback name (`127.0.0.1`·`localhost`·`::1`), and **the port is never checked** (behind SSH `-L`, the Origin/Host port differs from the server's own port — measured: a forwarder mapping 18110→18106 got `200` on `/api/pick`·`/api/pin`·`/close`).
  - A `*.ts.net` Origin on a loopback Host is never accepted — `tailscale serve` preserves Host, so this isn't a legitimate path, and accepting it would let another tailnet's public Funnel page send a bodyless POST like `close`·`clear` to a local user's browser with no preflight (measured: `200` before the fix, `403` now).
  - If Host is `*.ts.net`, Origin must match that host's name and port exactly (an omitted port normalizes to the scheme default — `https://h.ts.net` = `https://h.ts.net:443`).
- The `Host` on **every request** must be a loopback name (`127.0.0.1`·`localhost`·`::1`, **port never checked**) or `*.ts.net` — so DNS rebinding can never leak a pin note or manuscript snippet. `Tailscale-User-*` headers don't exempt a request from this: a rebinding page can attach that same-origin GET's headers with no preflight. `tailscale serve` preserves the original `Host` (`<device>.<tailnet>.ts.net>`), so legitimate tailnet requests pass through fine.
- If a co-author's browser gets `403` ("Host not allowed"/"different origin") on first deployment, record that message's value and temporarily work around it with `--no-origin-check`.
- Why Host ignores the port: forwarding to a different local port with SSH `-L 9000:127.0.0.1:<port>` makes the browser send a `Host` like `localhost:9000` — the forwarder's own port. Requiring a port match there would make every such request `403`. The Host name itself (is it a loopback name?) is what actually defends against DNS rebinding, and that's independent of the port — dropping the port check doesn't weaken it, since a rebinding attack's `Host` was never a loopback name to begin with. Cross-origin defense is `Origin`'s job.
- Known limitation: since a loopback Origin's port is never checked, a POST sent by another local web app on the same device (`http://localhost:3000`) through the user's browser isn't blocked — the tradeoff for supporting SSH `-L`.

## Behind `tailscale serve` (measured)

`tailscale serve` attaches identity headers to every request and forwards the `*.ts.net` Host as-is. These values were measured on 2026-09-21.

| Request | Result |
| --- | --- |
| `GET /` from the tailnet | `200`. `GET /api/meta`'s `me` is filled in as `{login, name, pic}` |
| A `POST` with `Origin: https://<host>.ts.net:<port>` (as a browser would send) | `200` |
| A `POST` from a different origin (`Origin: https://evil.example`) | `403` |
| A `POST` with a spoofed identity header sent to an unrecognized `Host` | `403` — a header never lets a request skip the Host check |
| Access from a public IP | Connection fails |

Under `--auth tailscale` the identity headers are **trusted only from a loopback TCP peer** — `tailscale serve` connects from loopback, so from any other peer (possible only with a non-loopback `--bind`) they are ignored. A request that hits `127.0.0.1` directly with a `Tailscale-User-Login` header attached is still recorded as that person (measured 2026-09-24, `/api/meta`'s `me`); regression and browser tests impersonate two people this way (Playwright `extra_http_headers`). A local process on the same device can attach the header itself, and a headerless local request is the agent while the loopback agent is on — so on a shared machine give agents tokens, set `--no-agent-loopback`, and use `--members-only`/roles. With the default bind, any request that didn't go through the tailnet can only have come from that device.

## Running persistently — systemd user units

A persistent instance is managed as the systemd user unit `limn@<name>`. Creating and configuring the unit (`~/.config/limn/<name>.env`), starting, stopping, and restarting it are all handled by the instance manager's `limn add|start|stop|update`. The exact unit-file format and details like setting the TeX distribution's PATH are authoritative in [instances.md](instances.md).

The server itself uses only the standard library, but **rebuilding depends on external commands** — `latexmk`·`pdftoppm`·`pdftotext`·`synctex`. systemd never sources a login shell's rc, so if the TeX distribution lives outside the default PATH (e.g. `/usr/local/texlive/...`), the unit has to state that path explicitly (instances.md handles this) — otherwise **the viewer comes up fine but only the rebuild fails**.

Verifying this takes two lines:

```bash
tr '\0' '\n' < /proc/$(pgrep -f 'limn serve' | head -1)/environ | grep ^PATH=
curl -s -X POST http://127.0.0.1:<port>/api/rebuild | head -c 200   # state should be ok
```

## State file layout

Single document (no `--doc` — same layout as the legacy state folder):

```
<state_dir>/
├── build/                    # rsync copy + latexmk output (not the original checkout)
├── pages.cur                 # the current page-image directory name (a pointer, atomically swapped)
├── builds.json               # build history (build id, manuscript fingerprint, seq, last result) — source of position estimation and build_seq
├── pages-<build_id>/         # page-*.png plus a matching PDF and synctex copy (keeps only the current one and the previous one)
├── pages/                    # legacy layout — used as-is if pages.cur is absent
├── pins.jsonl                # every current pin (rewritten atomically on every change)
├── pins.seq                  # the last id issued
├── pins.dropped.jsonl        # dropped pins (the source for restore)
├── pins.jsonl.corrupt-*.bak  # the original file preserved right before the first write when a corrupt line was found (conditional)
├── pins_<ts>.jsonl.bak       # an /api/clear archive
├── pins.md                   # the agent entry point — the one file to read
├── people.json               # @mention candidates and members — people who've opened this viewer or were added with `limn member` (optional `role`; excludes agents, atomically swapped)
├── tokens.json               # agent API tokens — SHA-256 hashes only, mode 0600, written by `limn token` (absent until the first token)
├── .people.lock · .tokens.lock   # cross-process locks for the two files above (the server and the CLI may write at once)
├── events.jsonl               # mention·review_requested·replied·reopened log (append-only, never sent externally)
├── build.log
├── built_at.txt
├── built_src_mtime.txt       # src_mtime at build start — basis for the auto-sync badge (build-sync §Auto-sync, works fine without this file)
└── head.txt                  # the commit built (short hash) — if the manuscript repo is git
```

Multiple documents (`--doc`): one pin file at the root, with per-document build output under `docs/<key>/`. Only the LaTeX document with key `main` uses the single-document location above (the root).

```
<state_dir>/
├── pins.jsonl · pins.seq · pins.dropped.jsonl · pins.md   # one set for the whole set of documents (pin numbers are unique across documents)
└── docs/
    ├── rr/                   # build/ · pages.cur · pages-<build_id>/ · builds.json · built_at.txt · head.txt … (same names as above)
    └── rv/                   # view-only: pages.cur · pages-<id>/ (page PNGs + a PDF copy) · builds.json · pdf_sig.txt (the rendered PDF's mtime:size)
```

## Using the viewer (for users)

| Action | How |
| --- | --- |
| Pick a location | Drag over the PDF → a dashed "new pin" box stays until you save or cancel. Dragging again doesn't clear the note |
| Adjust the range | The panel's one-row level control (dragged line / paragraph / environment name · line count) and a one-line stepper `위 [+][−] 아래 [+][−]` ("top [+][−] bottom [+][−]"). Source text collapses to 4 lines; open it with [원문 펼치기] ("[expand source]") |
| Save | [핀 저장] ("[save pin]") pinned to the bottom of the panel, or ⌘↵ / Ctrl+Enter from the note field (ignored mid-IME composition). Or the toast's [되돌리기] ("[undo]") |
| Edit | Click a card's note, or [수정] ("[edit]") → edit note/range, [위치 다시 잡기] ("[relocate]") to pick a new spot on the PDF |
| Question · reply | Choose `[수정 요청 | 질문]` ("[fix request | question]") before saving. [답글] ("[reply]") on a card adds to the thread (⌘/Ctrl+Enter). `@` mentions a person — a mentioned pin is skipped by the agent, and mentioned people are gathered under the list header's [나를 부른 핀 N] ("[pins addressed to me, N]") |
| Pending review | A pin an agent closed lands in the `검토 대기` ("pending review") section. [변경 보기] ("[view changes]") to see the fix, then [확인] ("[confirm]") — done — or [다시 열기] ("[reopen]") with a one-line reason |
| Done · dropped | [완료] ("[done]")·[삭제] ("[delete]") — both can be undone instantly via the toast's [되돌리기] ("[undo]"). A closed pin can be reopened from the `완료 N` ("done N") section below the open list, a dropped one restored from the `삭제 N` ("dropped N") section below that. Both sections are dim, flat rows with a sticky header ([design.md](design.md) §Archive). If someone else drops your own pin (a co-author or agent), the notification distinguishes it from being done: "#N was dropped by 〈name〉 [restore]" instead of "#N is done" |
| Click a mark badge | Clicking a green numbered badge on the PDF scrolls to that card and gives it `.cur` (an emphasis border) and `.flash` (a 1.2-second blink) — it never starts a new selection. The emphasis clears itself after 1.2 seconds (a static style, so it doesn't linger until the next click). Dragging the mark box itself (outside the badge) starts a new selection as usual |
| A card's [보기] ("[view]") | Scrolls that pin's mark to 30% down the screen and briefly flashes its border. A dashed border (`.est`) means the PDF the pin was picked on and the current PDF come from different manuscripts, or lines shifted, so the coordinates are estimated (server-decided, [build-sync.md](build-sync.md) §Position estimation) |
| Rebuild PDF | Compiles the manuscript asynchronously (tens of seconds) — returns immediately on click, and a progress chip shows the phase (with `--git-pull`: pulling remote main → copying the manuscript → compiling LaTeX → rendering pages) and elapsed time. A build someone else already started shows on the same chip. The completion notification gets one line about the pull result (with `--git-pull`) — what was pulled, or why it was skipped. [Re-read pins] just re-reads the pin list immediately (auto-sync usually does this within a few seconds anyway, §Auto-sync) |
| In-progress badge | A pin an agent has `claim`ed gets an amber dot in the card header and a `처리 중 · 약 15분 · 20:40쯤` ("in progress · ~15 min · around 20:40") badge. Past the estimate: `예상보다 늦어짐 (+5분)` ("later than expected (+5 min)"); claimed with no estimate: `처리 중 · 20:02부터 (23분째)` ("in progress · since 20:02 (23 min so far)"). Who claimed it and the lock auto-release time are in the badge's tooltip ([api.md](api.md) §In-progress marker). The viewer has no way to set a claim — only [풀기] ("[unclaim]") to clear the marker (e.g. if that agent stalled) |
| Theme | [◐] system → [☀] light → [☾] dark. Saved in the browser |
| Width | [폭] ("[width]", Ctrl/⌘ 0) fits the page width to the left screen. On a first visit with no saved width, it fits automatically if wider than the screen |
| Zoom | Ctrl/⌘+wheel or trackpad pinch over the PDF (anchored to the pointer), Ctrl/⌘ + `=`·`−`, [＋]·[−]. Only the PDF page grows — panel and toolbar stay put. 0.5–5× fit-width. Overflow scrolls horizontally, only within the PDF area. Ctrl+wheel with an input field focused, or over the panel, is browser zoom instead ([design.md](design.md) §PDF-area-only zoom) |
| Sharpness | Pages render as vectors via PDF.js, matched to screen resolution (crisp text even zoomed in). A PNG shows first for a few hundred ms. If it can't render as a vector, a "PNG view" chip appears next to the toolbar and it falls back to PNG |
| Panel width | Drag the handle between the body and the panel (280px, leaving at least 480px for the body). Double-click to cycle narrow → normal → wide, or focus it and use ←/→. Remembered in the browser ([design.md](design.md) §Panel cleanup and width adjustment) |
| Switching documents (multiple documents) | Click a tab over the PDF. A collapsed fold uses the toolbar's [문서 이름 ▾] ("[document name ▾]") → a list. Ctrl+PgUp/PgDn·Alt+1…9 (outside input fields). Each document remembers its own viewing spot and zoom, and `#doc=<key>` in the address bar makes links/refresh work. A tab's dot means the manuscript changed (needs a rebuild), a spinner means building, `PDF` means view-only |
| Re-read pins | [다시 읽기] ("[reread]") at the top of the open-pin list — re-reads the pin file immediately (doesn't wait for the 5-second auto-sync). Inside `[더보기]` ("[more]") on a collapsed or unfolded foldable |
| All documents | [모든 문서] ("[all documents]") at the top of the pin list — shows open pins from other documents too, with a document chip on each card. That card's `#number`·[보기]·[수정] switches to that document first, then jumps there |
| View-only PDF | Dragging or long-pressing to pick a region shows "page N region" and the region's text (no scope levels). Attach a note and save. [PDF rebuild] is hidden — the pages redraw themselves automatically when the file changes |
| Help | The `?` key or [?] — the flow, shortcuts, terminology, and the `<state_dir>/pins.md` path |
| Esc | Closes whatever's open, innermost first: help → tooltip → relocate → edit → selection. While in an input field, it never spends one press just closing a tooltip (one Esc in the note field cancels the selection directly) |

### Phones and tablets (touch)

At 700px or narrower (a collapsed foldable, a phone), the sidebar becomes a **bottom sheet**; at 700–1100px on a touch screen (an unfolded foldable, a tablet), it becomes a **narrow panel**. Design and rationale are in [design.md](design.md) §Mobile layout.

| Action | How |
| --- | --- |
| Open/close the panel or sheet | The toolbar's [핀 N ▴/▾] button (sheet) or [핀 N ▸/◂] button (panel). N is the open-pin count. The sheet starts collapsed, showing only the toolbar. Its collapsed state on an unfolded screen is remembered |
| Pick one paragraph | **Long-press** the PDF. Scrolling works as usual |
| Zoom | **Pinch with two fingers** over the PDF. Only the PDF page grows — sheet, panel, and toolbar stay put. Moving two fingers while zoomed drags along |
| Pick a region | Turn on [선택] ("[select]", the button turns blue, "selecting") and drag with one finger. A tap selects that spot's paragraph. Two-finger zoom (PDF only) still works while it's on. Saving or canceling a pin turns it off automatically (so scrolling resumes) |
| Save | Picking expands the sheet, with the note field above the source-text snippet. [취소]·[핀 저장] ("[cancel]"·"[save pin]") are pinned to the bottom of the sheet. Tapping the note field is what opens the keyboard (never opened automatically) |
| Pin card | Collapsed to a summary (number, line, page on one line + a two-line note preview). Tapping expands it, revealing [보기]·[수정]·[완료]·[삭제] ("[view]"·"[edit]"·"[done]"·"[delete]"). Tapping a numbered badge on the PDF also expands that card |
| [더보기] ("[more]") | Reread pins, theme, zoom out/in, fit width, panel width (sheet height on a sheet), page navigation, closed pins, dropped pins, help. File, page count, commit, build time, and author are listed at the top |
| Panel width (unfolded) | Drag the panel's left-edge handle (300px to 60% of the screen). Tap to cycle narrow → normal → wide. Remembered separately from the desktop width |
| Sheet height (collapsed) | Drag the top-edge handle. Dragging it all the way down collapses it; tapping cycles low → normal → high. Remembered |
| See a tooltip | Long-press a button (that press doesn't also activate the button) |
| Relocate | [수정] → [위치 다시 잡기] ("[edit]" → "[relocate]") turns on selection mode and collapses the sheet. Drag or tap, then [이 위치로 바꾸기] ("[use this location]") on the banner above the collapsed toolbar |
