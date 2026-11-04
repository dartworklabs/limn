"""The Content-Security-Policy of the HTML pages Limn serves (docs/adr/0026-viewer-csp.md).

Every response carries a policy (handler.end_headers). A response that is not one of Limn's HTML pages - JSON, a PDF,
a page image, pins.md, a vendored file, the base class's own error pages - carries FRAME_ONLY: nobody may frame it, and
nothing else is said, so a PDF a browser opens in its own viewer is not restricted. An HTML page Limn assembles (the
viewer at GET /, the readable refusal page) carries page_policy(page), computed from the page's own text: its inline
<script> and <style> elements are allowed by their SHA-256 hashes, so the page needs no 'unsafe-inline', and a script
that someone else's text manages to put into the page does not run.

The hashes are taken from the exact text the page is sent with, after every placeholder is filled - the viewer's
template is filled per run (the interface language in a script, the accent in the stylesheet), so its policy is the
run's, never the template's: GET / takes it from the very page it sends (limn.viewer.routes). The HTML tokenizer turns CR LF and a lone CR into
LF before a script's text exists; the hash is taken after the same step.

What the policy allows beyond the page's own origin is one thing: an https: image, for a person's avatar (the
Tailscale-User-Profile-Pic URL, which access.py only takes as https://). Everything else - scripts and the PDF.js and
service workers, styles, fonts, fetches - is the page's own origin ('self').
"""

import base64
import hashlib
import re

HEADER = "Content-Security-Policy"
# Every response that is not one of Limn's HTML pages: no framing (clickjacking), nothing else.
FRAME_ONLY = "frame-ancestors 'none'"

# An inline element whose text the browser runs or applies: <script> or <style> with no attributes - the only form
# Limn's pages write. The text ends at the first closing tag, as the tokenizer's script data state ends it.
_INLINE = re.compile(r"<(script|style)>(.*?)</\1>", re.S)
# Any opening tag of the two, with or without attributes; page_policy refuses a page where they differ in number.
_OPENING = re.compile(r"<(?:script|style)\b", re.I)
# What would make the tokenizer end or escape an inline element's text elsewhere than _INLINE does.
_AMBIGUOUS = re.compile(r"</(?:script|style)|<!--", re.I)


def _digest(text: str) -> str:
    """The CSP hash source of an inline element's text: 'sha256-<base64>' over its UTF-8 bytes after the tokenizer's
    newline normalisation (CR LF and a lone CR become LF)."""
    data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def inline_hashes(page: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(script hashes, style hashes) of page's inline elements, each in page order with repeats removed.

    A page whose elements this cannot read the way the browser does - a <script>/<style> tag with attributes, an
    element whose text holds another closing tag or an HTML comment opener - raises ValueError rather than give a
    policy that blocks the page's own script. That is a packaging defect in Limn's own page: a run changes only an
    escaped label, a #rrggbb accent and ko/en, and web/tests/test_csp.py reads the packaged page under such runs."""
    found = _INLINE.findall(page)
    if len(found) != len(_OPENING.findall(page)) or any(_AMBIGUOUS.search(text) for _, text in found):
        raise ValueError("an inline <script>/<style> of the page cannot be hashed as the browser reads it")
    scripts = dict.fromkeys(_digest(text) for kind, text in found if kind == "script")
    styles = dict.fromkeys(_digest(text) for kind, text in found if kind == "style")
    return tuple(scripts), tuple(styles)


def page_policy(page: str) -> str:
    """The Content-Security-Policy of one of Limn's HTML pages, from its text (inline_hashes; raises like it).

    default-src 'self' covers what needs no exception - connect (fetch), font (Pretendard), worker (PDF.js, the service
    worker, a future parse worker), manifest and media. script-src and style-src add the page's hashes to 'self' (the
    vendored PDF.js and Markdown modules are import()ed from this origin). img-src adds https: for avatars.
    object-src, base-uri, form-action and frame-src are 'none': the viewer has no plugin, <base>, form or frame, so an
    injected one does nothing. frame-ancestors 'none' keeps what FRAME_ONLY says."""
    scripts, styles = inline_hashes(page)
    directives = (
        "default-src 'self'",
        " ".join(("script-src", "'self'", *scripts)),
        " ".join(("style-src", "'self'", *styles)),
        "img-src 'self' https:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-src 'none'",
        "frame-ancestors 'none'",
    )
    return "; ".join(directives)
