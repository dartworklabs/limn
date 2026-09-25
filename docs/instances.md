English | [한국어](instances.ko.md)

# Instances — one Limn per manuscript

`limn serve` runs one server in the foreground. For manuscripts you work on for weeks, run each as an
**instance**: a systemd user unit `limn@<name>` with its own ports, state directory and journal.
Papers live in separate repositories and are often worked on at the same time, so each gets its own
instance; all instances share the one installed `limn` package.

| What | Where |
|---|---|
| Unit template | rendered from the package into `~/.config/systemd/user/limn@.service` by `limn add`/`limn start` (instance name = paper slug) |
| Instance config | `~/.config/limn/<name>.env` (`LIMN_CONFIG_DIR`) |
| CLI | `limn` (installed with `uv tool install`) |
| App | the installed `limn` package — upgrade/rollback with `limn update` |
| State (per instance) | `STATE_DIR` from the config, default `~/.local/share/limn/<name>` — pins, `build/`, `build.log`, `pins.md` |
| Logs (per instance) | `journalctl --user -u limn@<name>` · `<STATE_DIR>/build.log` |

## Config keys

One `KEY=VALUE` per line. systemd-style `EnvironmentFile` syntax; `limn` reads it itself and **never
sources it with a shell**, so do not use shell syntax in values. `limn add` refuses quotes, backslashes,
`$`, backticks and newlines.

| Key | Meaning |
|---|---|
| `MANUSCRIPT` | manuscript folder (LaTeX source root, absolute path) |
| `MAIN` | top-level `.tex` file name (at the top of the manuscript folder) |
| `PORT` / `TS_PORT` | local port (on `127.0.0.1` unless `BIND` is set) and tailnet `https` port. **Never auto-picked at run time** — an advertised address must not change |
| `STATE_DIR` | state directory. `limn add` refuses one that another instance uses |
| `GIT_PULL` | `1`: fast-forward (`--ff-only`) the manuscript checkout before every rebuild |
| `LABEL` / `ACCENT` | the viewer's label and accent colour (`#rrggbb`) |
| `EXTRA_ARGS` | further server arguments (split on spaces). `limn add` defaults to `--no-build`; the server builds anyway when there is no output yet |
| `DOCS` | several documents (manuscript, response letter, view-only PDFs, …) switched by tabs. Not together with `MAIN`. See [Multiple documents](#multiple-documents-docs) |

Access control keys (v0.2, all optional — see [Access: tokens and members](#access-tokens-and-members)). Unset keys
add no server flag, so a config without them runs exactly as in v0.1. `limn run` validates them before starting and
stops with a clear error instead of letting the unit restart into the same failure.

| Key | Server flag | Meaning |
|---|---|---|
| `AUTH` | `--auth` | identity provider: `tailscale` (default when unset), `local`, `trusted-proxy`. `limn add --auth <provider>` writes it |
| `AGENT_LOOPBACK` | `0` → `--no-agent-loopback`, `1` → `--agent-loopback` | `0` refuses headerless loopback requests (agents must use a token). `1` only works with `tailscale` on a loopback `BIND` |
| `BIND` | `--bind` | listen address, default `127.0.0.1`. A non-loopback address needs `AUTH=trusted-proxy` (or `--i-know-this-is-insecure` in `EXTRA_ARGS`) |
| `PUBLIC_HOSTS` | `--public-host` | comma-separated `name[:port]` the instance is reached under (accepted as Host/Origin, used as the `pins.md` base URL) |
| `TRUSTED_PROXIES` | `--trusted-proxies` | comma-separated IPs/CIDRs whose identity headers `trusted-proxy` trusts (default `127.0.0.1,::1`) |
| `PROXY_USER_HEADER` / `PROXY_NAME_HEADER` / `PROXY_EMAIL_HEADER` | `--proxy-user-header` / `--proxy-name-header` / `--proxy-email-header` | header names under `trusted-proxy` (defaults `X-Forwarded-User`, `X-Forwarded-Preferred-Username`, none) |
| `MEMBERS_ONLY` | `1` → `--members-only` | admit only people in `people.json` (or `--allow`) |
| `LOCAL_USER` | `--local-user` | the owner's login under `AUTH=local` (default `$USER`) |

## Adding a manuscript

```bash
# 1. add — picks ports, writes the config, enables and starts the unit, sets up tailscale serve,
#    and prints a block for the paper repository's AGENTS.md
limn add paper2 --manuscript ~/papers/paper2 --git-pull --label Paper2
# 2. paste the printed block into that paper repository's AGENTS.md (show it again: limn snippet paper2)
```

Without `--main`/`--doc`, `limn add` detects the documents (next section) or, failing that, the one
top-level `.tex` with `\documentclass`; with several candidates it stops instead of guessing. Without
`--label` it uses the manuscript repository name (end of the `origin` URL). `--no-serve` keeps it local.

If you keep configs in another repository (e.g. a dotfiles repo), set `LIMN_SOURCE_DIR` to that
folder: `limn add` then writes the config there and links it into `~/.config/limn/`.

## Default document tabs

Without `--doc` and `--main`, a manuscript folder with the standard paper-repo layout gets its tabs
automatically:

| Tab | Key | Path | Included when |
|---|---|---|---|
| Manuscript (본문) | `ms` | `manuscript/<latest round>/<main>.tex` | always (if the layout matches). The round is the sub-folder with the largest leading number (`1st`, `2nd`, …; folders not starting with a digit are ignored). With several `\documentclass` files in the round folder, the most recently committed (then modified) one wins; a tie stops with an error |
| Response (답변서) | `rr` | `submission/review_response/review_response.tex` | revision stage and the file exists |
| Highlights (하이라이트) | `hl` | `submission/highlights/highlights.tex` | the file exists |
| Cover letter (커버레터) | `cl` | `submission/cover_letter/cover_letter.tex` | the file exists |

The order is fixed (`ms` → `rr` → `hl` → `cl`). The stage is `--stage auto|initial|revision`
(default `auto` = revision when `<manuscript>/reviews/` exists). The tab names are stored in the
config as written above (Korean by default); edit `DOCS` to rename them.

```bash
limn doc suggest --manuscript ~/papers/paper2      # read-only preview of the detected DOCS
limn add paper2 --manuscript ~/papers/paper2        # writes the same result
```

## Multiple documents (`DOCS=`)

```bash
limn add paper2 --manuscript ~/papers/paper2 --label Paper2 \
  --doc 'ms=Manuscript:manuscript::2nd/main.tex' \
  --doc 'rr=Response:submission/review_response/review_response.tex' \
  --doc 'sub=Submitted PDF:submission/submission_ready/manuscript.pdf'

limn doc add paper2 --doc 'cl=Cover letter:submission/cover_letter/cover_letter.tex' --restart
limn doc list paper2
limn doc remove paper2 cl
```

| Item | Rule |
| --- | --- |
| `--doc` format | `<key>=<display name>:<path>` — key before the first `=`, name up to the next `:`, the rest is the path |
| Key | `[a-z0-9-]{1,24}`, unique. Do not rename keys later (pins record them) |
| Path | relative to `--manuscript` (recommended) or absolute; must be inside `--manuscript` |
| `x/main.tex` | LaTeX; build root `x/` |
| `root::sub/main.tex` | LaTeX; build root `root/` (copies more), main `root/sub/main.tex` |
| `x/file.pdf` | view-only (no rebuild; page/region pins) |
| Count | up to 12 |
| With `MAIN` | never together — `add` and `run` refuse |
| In the config | `DOCS="<key1>=<name1>:<path1>;<key2>=…"` (`;`-separated; quoted because names may contain spaces) |

`limn doc add` on a single-document (`MAIN`) instance moves the main file to the first entry
`main=<name>:<MAIN>`; the key `main` keeps the old state layout, so build history and old pins carry over.
The server-side contract is in [operations.md](operations.md#multiple-documents---doc).

## Running several at once

Each instance has its own ports, state directory, build directory (`<STATE_DIR>/build`) and journal.
The server copies the manuscript into `<STATE_DIR>/build` and builds there, so simultaneous rebuilds do
not touch each other. `limn add` warns when two instances watch the same manuscript folder (their
`--git-pull` would overlap).

## Updating and rolling back

```bash
limn update --dry-run          # show what would be installed and restarted
limn update                    # install the latest v* tag, then restart running instances
limn update --ref v0.1.1       # a specific tag or branch
limn update --from ~/src/limn  # a local checkout (development)
```

`limn update` runs `uv tool install --force git+https://github.com/dartworklabs/limn@<ref>`
(`LIMN_REPO` overrides the source, e.g. `git+ssh://git@github.com/dartworklabs/limn` to use SSH), re-renders the unit template, and restarts every running
`limn@*` instance, waiting for HTTP 200. Running servers keep working during the install; they switch
to the new version when restarted. **State directories are never touched.** To roll back, install the
previous tag: `limn update --ref v<previous>` (the command is printed after every update). There is
no separate app copy any more — the version *is* the installed tag.

## Stopping and removing

- `limn stop <name>` — stops and disables the unit. Config, ports and the serve entry stay; `limn start <name>` brings it back.
- `limn remove <name>` — stops and disables the unit, removes the tailscale serve entry (**only if it points at this instance's local port**), and deletes the config (which releases the ports). **The state directory is kept**; its path is printed.

## Ports

- The config file is the reservation: `limn add` refuses ports that another instance's config uses,
  that are listening on any address, or that `tailscale serve` already uses — also when given explicitly.
- Auto-assignment takes the first free tailnet port in `18005–18099` (`LIMN_TS_MIN`/`LIMN_TS_MAX`)
  and pairs it with local port `+100` (18004 ↔ 18104), so the pair is recognisable from either number.
- Optional machine-wide port ledger: if `~/.config/served/reserved-ports.txt` (`LIMN_LEDGER`) exists,
  its `<port> <owner>` lines are avoided too. With `LIMN_LEDGER_GEN=<script>` (called as
  `<script> <unit dir> <config dir>`, printing `<port> <owner>` lines), `add` and `remove` regenerate
  the ledger. Without a generator the ledger is only read.

## Access: tokens and members

```bash
limn token create paper2 [--name ci]     # prints a new agent token once (stdout); only its hash is stored
limn token list paper2                   # id, name, created — never the token
limn token revoke paper2 <id|name>       # the running server refuses it from the next request
limn member add paper2 alice@example.com [--role editor] [--name "Alice Kim"]
limn member list paper2                  # login, role, name, last seen
limn member role paper2 alice@example.com viewer
limn member remove paper2 alice@example.com
```

Both work on the instance's `STATE_DIR` (`tokens.json`, `people.json`); for a plain `limn serve` pass
`--state-dir <dir>` instead of the name. Changes apply to a running server on its next request — no restart.
Give the token to the agent (e.g. `export LIMN_TOKEN=…`); it sends `Authorization: Bearer $LIMN_TOKEN`.

| Role | May |
|---|---|
| `owner` | everything an editor may. Owner-only operations (members, tokens, settings) are CLI/file level in v0.2 — there are no owner-only HTTP endpoints yet |
| `editor` | everything a person could do in v0.1: pin, reply, edit, close, confirm, reopen, rebuild. **A person without a role is an editor** |
| `viewer` | read only; may still run `/api/pick` and comparison builds (`/api/revision-build`). Every other change is `403` |
| `agent` | the agent contract: claim, reply, close into review — never confirm. Token principals always have this role |

## Security rules

**Default policy (tailnet instances).** With no `AUTH` (or `AUTH=tailscale`) and no allowlist, an instance stays
open to everyone on the tailnet who reaches it, with attribution only: an unknown tailnet login is admitted,
recorded in `people.json` on first visit **without a `role` field** (= editor), and may open the viewer, pin,
reply, close and confirm exactly as in v0.1. Nothing that works today is denied. Roles and allowlists
(`MEMBERS_ONLY=1`, `--allow`, roles set with `limn member`) are strictly opt-in.

- The server binds `127.0.0.1` unless `BIND` says otherwise; a non-loopback `BIND` is refused unless `AUTH=trusted-proxy` (or `--i-know-this-is-insecure` is in `EXTRA_ARGS`, which starts with a loud warning). Tailnet exposure is only `tailscale serve --bg --https=<TS_PORT> http://127.0.0.1:<PORT>`.
- `tailscale serve` only for the tailscale provider: `add` and `start` refuse to serve an `AUTH=local` instance (every loopback request is the owner, so every tailnet member would be) or an `AUTH=trusted-proxy` one (tailnet users could send the proxy headers themselves). Use `--no-serve` and put those behind their own proxy.
- Agents authenticate with tokens. The v0.1 rule "a headerless loopback request is the agent" still works under `tailscale` but is deprecated (the server logs a warning); set `AGENT_LOOPBACK=0` once your agents use tokens.
- **Never funnel.** Manuscripts are unpublished. `add` and `start` re-read the serve config and stop if the port is funneled.
- **No sudo.** `limn` does not change tailscale operator settings; if `serve` fails for lack of rights it stops with an error.
- Other services' serve entries are never overwritten or removed; `serve reset` is never used (it is machine-wide).

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `LIMN_CONFIG_DIR` | `$XDG_CONFIG_HOME/limn` | instance configs |
| `LIMN_DATA_ROOT` | `$XDG_DATA_HOME/limn` | default parent of state directories |
| `LIMN_SOURCE_DIR` | = config dir | where `add` writes configs (then linked into the config dir) |
| `LIMN_USER_UNIT_DIR` | `$XDG_CONFIG_HOME/systemd/user` | where the unit template is rendered |
| `LIMN_UNIT_PATH` | dir of `pdflatex` + `/usr/local/bin:/usr/bin:/bin` | `PATH` inside the unit |
| `LIMN_LEDGER`, `LIMN_LEDGER_GEN` | see [Ports](#ports) | optional port ledger |
| `LIMN_TS_MIN`, `LIMN_TS_MAX`, `LIMN_LOCAL_OFFSET` | `18005`, `18099`, `100` | auto-assigned port range |
| `LIMN_REPO`, `LIMN_UV` | `git+https://github.com/dartworklabs/limn`, `uv` | what `limn update` installs, with which `uv` |
| `LIMN_WAIT` | `240` | seconds to wait for HTTP 200 after start/restart |

Coming from an older install under a former name? See the History section of the [README](../README.md#history)
and `limn migrate --help`.
