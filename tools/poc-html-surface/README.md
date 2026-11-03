# HTML surface PoC (throwaway)

Throwaway PoC for [the deferred HTML document surface](../../docs/superpowers/specs/2026-10-24-html-document-surface.md).
It exists so the owner can touch the direction on the four device groups. **Not approved; do not merge.** The design
decisions are open in the spec and in the proposed ADR-0025.

What it does: a `--doc` path ending in `.md` is a `markdown` document. The server does not build it; `GET /api/source`
answers its lines as the server numbers them, and the viewer renders them with a vendored markdown-it (raw HTML never
drawn, links limited, images not fetched), each block carrying its source line range. A text selection or a tap on a
block opens the ordinary composer with a ladder of lines -> block -> section; the pin is an ordinary line pin
(`file`, `lo`, `hi`) saved through `POST /api/pin`.

Run it on loopback (replace the placeholders):

```bash
uv run python -m limn serve --manuscript <folder with fixture.md and README.ko.md> \
  --doc 'fixture=Fixture:fixture.md' --doc 'readme=README:README.ko.md' \
  --state-dir <a scratch folder> --port <local port> \
  --auth tailscale --public-host <host>.<tailnet>.ts.net:<https port>
tailscale serve --bg --https=<https port> http://127.0.0.1:<local port>
```

Known PoC shortcuts (each is a decision in the spec, not a design): a Markdown pin still stores `page: 1` (the add
parser's default); `scope` gains `block` and `section` and `kind` gains `md:block`/`md:section`; the startup build
skip, the suggestion gate and the verdict placement read the new kind or capability ad hoc; no search, no change view,
no rendered comparison, no tests.
