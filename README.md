English | [한국어](README.ko.md)

# Limn

**Limn** (림, "to depict clearly") closes the revision loop between people and agents on a LaTeX
manuscript. Drag over a spot in the PDF, write what should change, and Limn turns it into a **pin**: the
`.tex` file and line range (recovered with SyncTeX, cross-checked against the text), plus your note.
Agents read the pins as a short work list (`pins.md`, ~35 tokens per pin instead of a 1,500-token
screenshot), edit the source, and close each pin with what they changed; a person confirms. Co-authors
on the same private network pin too, and every pin records who left it.

- Single stdlib-only Python server, browser viewer with vector PDF rendering (bundled PDF.js)
- Several documents per manuscript (manuscript, response letter, view-only reviewer PDFs) as tabs
- Rebuilds on demand or when the upstream branch moves (`--git-pull`)
- Threads, questions, @mentions, assignees, review before done, a diff view per pin
- One long-running **instance** per manuscript as a systemd user unit, exposed with `tailscale serve`

## Install

Requires Python ≥ 3.10, [uv](https://docs.astral.sh/uv/), a TeX distribution with SyncTeX
(`latexmk`/`pdflatex`) and Poppler (`pdftoppm`).

```bash
uv tool install git+ssh://git@github.com/dartworklabs/limn@v0.1.0
limn version
```

## Run one server

```bash
limn serve --manuscript ~/papers/paper2 --main main.tex --port 18300
# several documents as tabs:
limn serve --manuscript ~/papers/paper2 \
  --doc 'ms=Manuscript:manuscript/main.tex' --doc 'rr=Response:submission/review_response/review_response.tex'
```

It listens on `127.0.0.1` only. Open `http://127.0.0.1:18300/`. To share it on your tailnet:
`tailscale serve --bg --https=18200 http://127.0.0.1:18300`. `limn serve --help` lists all options;
state (pins, builds) goes to `--state-dir` or `~/.local/share/limn/serve/<manuscript>-<hash>`.

> **Security:** Limn has no built-in authentication yet. Anyone who can reach its port can read the
> manuscript and create, edit or close pins. Never expose it beyond loopback except through a private
> network you trust (e.g. `tailscale serve` on your tailnet) or an authenticating proxy — never a public
> URL, never `tailscale funnel`. See [SECURITY.md](SECURITY.md).

## Instances (one per manuscript)

```bash
limn add paper2 --manuscript ~/papers/paper2 --git-pull   # ports, config, systemd unit limn@paper2, tailscale serve
limn list                                                  # label, ports, state, open pins, documents
limn status paper2 · limn url paper2 · limn snippet paper2 # details · tailnet URL · block for AGENTS.md
limn update [--dry-run] [--ref vX.Y.Z]                     # reinstall via uv tool, restart running instances
limn stop paper2 · limn start paper2 · limn remove paper2
```

Config lives in `~/.config/limn/<name>.env`, state in `~/.local/share/limn/<name>` by default.
Details: [docs/instances.md](docs/instances.md).

## For agents

An agent reads `pins.md` (`curl -s <base>/pins.md`) or `GET /api/pins`, claims one pin right before
editing it, and closes it with a `reply` and a `ref` (commit/PR); a person confirms. Agents never
confirm, and skip pins claimed by others, awaiting review, or assigned to a person. The full procedure
is [skill/SKILL.md](skill/SKILL.md); the API is [docs/api.md](docs/api.md). The `pins.md` format and
the HTTP API are a stable contract — they do not change with the UI language.

## Documentation

| | |
|---|---|
| [skill/SKILL.md](skill/SKILL.md) | agent procedure (install it as a skill in your agent runtime) |
| [docs/instances.md](docs/instances.md) | instances, updates, ports, security rules |
| [docs/operations.md](docs/operations.md) | running the server, options, state layout, using the viewer |
| [docs/api.md](docs/api.md) | HTTP API and `pins.md` format |
| [docs/design.md](docs/design.md) · [docs/build-sync.md](docs/build-sync.md) | design notes, rebuild and sync |
| [SECURITY.md](SECURITY.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md) | |

Roadmap: [access control, collaboration boundaries and sync](docs/design/access-and-sync.md) (draft).

## License

Limn is licensed under AGPL-3.0-only. Commercial licenses are available from Dartwork (contact via GitHub issues for now).
Bundled third-party components: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Name and logo: [TRADEMARKS.md](TRADEMARKS.md).

## History

Limn started on 2026-09-21 as the `manuscript-pin-picker` skill of the writing-agent-playbook
repository (server `scripts/pin_server.py`), and its per-paper instance manager `bin/pin-viewer.sh`
(systemd units `pin-viewer@<name>`, from 2026-09-23) lived in a dotfiles repository. On 2026-09-25 both moved here with
their history (`git filter-repo`, merged with `--allow-unrelated-histories`) and were renamed Limn.
Personal data in the imported history was replaced with placeholders.

### Migrating from `pin-viewer@<name>`

Nothing is deleted; ports, tailnet addresses and pins carry over.

```bash
uv tool install git+ssh://git@github.com/dartworklabs/limn@v0.1.0
limn migrate --dry-run            # plan: ~/.config/pin-viewer/<name>.env -> ~/.config/limn/<name>.env
limn migrate                      # copy configs (idempotent; old files stay)
# per instance:
systemctl --user disable --now pin-viewer@<name>.service
limn start <name>                 # renders limn@.service, starts limn@<name>, waits for 200; serve entry unchanged
limn status <name>                # active, local 200, tailnet URL, same open-pin count
```

State directories stay where they are (the new config points at them). To also move state from
`~/.local/share/pin-viewer/<name>` to `~/.local/share/limn/<name>`, run
`limn migrate --move-state <name>` after stopping the old unit and before `limn start`. When every
instance runs as `limn@`, `~/.config/systemd/user/pin-viewer@.service`, `~/.config/pin-viewer/` and
the old `~/.local/bin/pin-viewer` can be removed.
