# Contributing

Thanks for helping with Limn.

## Setup

```bash
uv sync --group dev
uv run playwright install chromium        # browser layout tests; skipped if no Chromium is found
uv run pytest -q                          # Python tests (server, CLI, migrate, naming)
bash tests/test_instances.sh              # instance manager (stubs systemd/tailscale; touches nothing)
```

The server is a single stdlib-only module (`src/limn/server.py`, Python 3.10+). Please keep it
dependency-free. Rendering needs a TeX distribution with SyncTeX (`latexmk`/`pdflatex`) and Poppler
(`pdftoppm`) at runtime, but the tests do not.

## Conventions

- Code, comments, docstrings, test names, commit messages, CLI help and log/error messages are in
  **English**. User-facing docs have Korean counterparts (`*.ko.md`); keep both in sync when you change one.
- UI strings go through the viewer's message table (Korean and English).
- **The agent contract is stable.** `pins.md` (its columns, markers and Korean header words) and the
  HTTP API (paths, JSON field names, state names) are read by agents in other repositories. Do not
  change them without a versioned migration plan.
- The app is called **Limn** everywhere. `tests/test_naming.py` fails on former names outside the
  README history section and `limn migrate`, and on personal data (real e-mails, home paths, host names).
  Use `alice@example.com` / `bob@example.com` style fixtures.
- Security invariants (see SECURITY.md): bind `127.0.0.1` only; no public exposure paths.

## Pull requests

Keep changes focused, add or update tests with behaviour changes, and make sure CI is green.

## Contributor license agreement

Contributions are accepted only under [CLA.md](CLA.md). To agree, tick the CLA box in the pull request
template and add this sign-off line to each commit (`git commit -s` adds the `Signed-off-by` part):

```
Signed-off-by: Your Name <you@example.com>
I agree to the Limn CLA (CLA.md).
```
