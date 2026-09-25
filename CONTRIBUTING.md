# Contributing

Thanks for helping with Limn.

## Setup

```bash
uv sync --group dev
uv run playwright install chromium        # browser layout tests; skipped if no Chromium is found
uv run pytest -q                          # Python tests (server, CLI, migrate, naming)
bash tests/test_instances.sh              # instance manager (stubs systemd/tailscale; touches nothing)
uv run ruff check                         # lint (bug-candidate rules, see pyproject.toml)
uv run shellcheck src/limn/instances.sh tests/test_instances.sh
```

The server is stdlib-only Python 3.10+ (`src/limn/server.py`, being split into modules — see the coding roadmap);
the viewer is three build-free files in `src/limn/viewer/`. Please keep it
dependency-free. Rendering needs a TeX distribution with SyncTeX (`latexmk`/`pdflatex`) and Poppler
(`pdftoppm`) at runtime, but the tests do not.

## Design documentation

The System Handbook in [docs/handbook/](docs/handbook/index.md) (Korean) is where the design lives:
purpose and sources of truth, architecture and invariants, the pin domain, the viewer, build and sync,
the HTTP API contract, operations, verification gates, the change workflow, and the roadmap for
aligning the code with our coding rules. Decisions and their reasons are in [docs/adr/](docs/adr/).
Read the chapters that touch your change before you start, and update them in the same pull request
when the current behaviour changes.

## Conventions

- Code, comments, docstrings, test names, commit messages, CLI help and log messages are in
  **English**. The Handbook is Korean. `README.md`/`README.ko.md` and `skill/SKILL.md`/`skill/SKILL.ko.md`
  are pairs; keep both in sync when you change one.
- Coding rules come from our coding skills (`code-implement`, `code-testing`, `code-security`) and take
  precedence over conventions found in the existing code. The order in which the code is brought in
  line is [docs/handbook/code-style-roadmap.md](docs/handbook/code-style-roadmap.md).
- UI strings go through the viewer's message table (Korean and English, `src/limn/ui_en.json`). The Korean
  text in the template is the key. Strings built at run time use `tl('<Korean template>', {params})` with
  `{name}` slots, e.g. `tl('{n}쪽', {n: 3})`; the English value may be plural forms `{"one": ..., "other": ...}`
  chosen by `n`. `tests/test_i18n.py` fails on a template without a translation and on Hangul left in the
  English chrome.
- **The agent contract is stable.** `pins.md` (its columns, markers and Korean header words) and the
  HTTP API (paths, JSON field names, state names) are read by agents in other repositories. Do not
  change them without a versioned migration plan.
- The app is called **Limn** everywhere. `tests/test_naming.py` fails on former names outside the
  README history section and `limn migrate`, and on personal data (real e-mails, home paths, host names).
  Use `alice@example.com` / `bob@example.com` style fixtures.
- Security invariants (see SECURITY.md): bind `127.0.0.1` by default and refuse a non-loopback bind unless
  `--auth trusted-proxy` (or the explicit `--i-know-this-is-insecure`); identity headers only from loopback or a
  configured proxy; tokens stored hashed; a v0.1 instance keeps behaving as v0.1; no public exposure paths.

## Pull requests

Keep changes focused, add or update tests with behaviour changes, and make sure CI is green.

## Contributor license agreement

Contributions are accepted only under [CLA.md](CLA.md). To agree, tick the CLA box in the pull request
template and add this sign-off line to each commit (`git commit -s` adds the `Signed-off-by` part):

```
Signed-off-by: Your Name <you@example.com>
I agree to the Limn CLA (CLA.md).
```
