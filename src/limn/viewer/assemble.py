"""The viewer page as one HTML string: index.html, its parts, the icons and the message table put together.

viewer_html() is the whole assembly. It reads index.html and the parts parts.txt lists from the viewer folder and
fills the page's build-time placeholders from its arguments - nothing else (no settings, no clock, no process state),
so the same folder and arguments give the same string, byte for byte. The run-time placeholders (__LABEL__,
__ACCENT__, __ACCENT_KEY__, __FAVICON_HREF__) are left for server.py's build_html(), which knows the run arguments.

Placeholders filled here:
- __APP_CSS__ / __APP_JS__: the parts listed under each marker in parts.txt, joined in order (load_viewer_html).
- __PDFJS_VERSION__: the vendored PDF.js version, the ?v= that busts the browser cache for /vendor/pdfjs/.
- __LIMN_MARK__: the Limn mark's inline SVG (limn.mark), by the label and in the help header.
- __LUCIDE_JSON__: the icon table, for the viewer's JS ic().
- __UI_EN_JSON__: the ko -> en message table (ui_en.json), for the viewer's I18N_EN.
- {{ic:<name>}}: one icon as an inline <svg> (icon_svg), the same markup the JS ic() builds.

The service worker (sw.js, GET /sw.js) is read from the same folder by service_worker(); it is served on its own,
not inlined.

A missing or malformed viewer file is a packaging defect and raises (OSError / ValueError): the server fails at import
rather than serve a broken page.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TypeAlias

# One entry of the message table: an English string, or plural forms {"one": ..., "other": ...} for a key with {n}.
Message: TypeAlias = str | dict[str, str]

VIEWER_DIR = Path(__file__).resolve().parent                     # this package's folder: index.html, parts.txt, css/, js/
VIEWER_MARKERS = ("__APP_CSS__", "__APP_JS__")
VIEWER_MANIFEST = "parts.txt"                                    # the ordered list of parts, beside index.html
VIEWER_PART_RE = re.compile(r"[a-z0-9-]+/[a-z0-9-]+\.[a-z]+")    # folder/name.ext: never leaves the viewer folder
# The service worker GET /sw.js serves, beside index.html. A script of its own, never a part of the page.
SERVICE_WORKER = "sw.js"

# PDF.js renders the PDF as vectors in the viewer (vendor/pdfjs/README.md). The version is also the ?v= value that busts the browser cache.
PDFJS_VERSION = "6.3.289"

# Viewer icons - Lucide (ISC, vendor/lucide/README.md). Only the <svg> inner elements of the icons in use are
# copied verbatim from the npm lucide-static source (only whitespace trimmed). Emoji/default character icons
# (e.g. hourglass, chevron, moon, pencil) are avoided since they render differently across devices and fonts.
LUCIDE_VERSION = "1.47.0"
LUCIDE = {
    "bell": '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 '
            '13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
    "bell-off": '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 '
                '.258-1.742"/><path d="m2 2 20 20"/><path d="M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05"/>',
    "bot": '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m16 9-5.5 5.5L8 12"/>',
    "circle-question-mark": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
                            '<path d="M12 17h.01"/>',
    "circle-x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
            '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "at-sign": '<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>',
    "ellipsis": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "eye": '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/>'
           '<circle cx="12" cy="12" r="3"/>',
    "message-square": '<path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 '
                      '2-2h16a2 2 0 0 1 2 2z"/>',
    "minus": '<path d="M5 12h14"/>',
    "moon": '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268'
            'c.344-.215.825-.004.803.401"/>',
    "move-vertical": '<path d="M12 2v20"/><path d="m8 18 4 4 4-4"/><path d="m8 6 4-4 4 4"/>',
    "move-horizontal": '<path d="m18 8 4 4-4 4"/><path d="M2 12h20"/><path d="m6 8-4 4 4 4"/>',
    "panel-left": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "pencil": '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 '
              '.623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "refresh-cw": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
                  '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "rotate-ccw": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "square-dashed": '<path d="M5 3a2 2 0 0 0-2 2"/><path d="M19 3a2 2 0 0 1 2 2"/><path d="M21 19a2 2 0 0 1-2 2"/>'
                     '<path d="M5 21a2 2 0 0 1-2-2"/><path d="M9 3h1"/><path d="M9 21h1"/><path d="M14 3h1"/><path d="M14 21h1"/>'
                     '<path d="M3 9v1"/><path d="M21 9v1"/><path d="M3 14v1"/><path d="M21 14v1"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/>'
           '<path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/>'
           '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "sun-moon": '<path d="M12 2v2"/><path d="M14.837 16.385a6 6 0 1 1-7.223-7.222c.624-.147.97.66.715 1.248a4 4 0 0 0 '
                '5.26 5.259c.589-.255 1.396.09 1.248.715"/><path d="M16 12a4 4 0 0 0-4-4"/>'
                '<path d="m19 5-1.256 1.256"/><path d="M20 12h2"/>',
    "text-wrap": '<path d="m16 16-3 3 3 3"/><path d="M3 12h14.5a1 1 0 0 1 0 7H13"/><path d="M3 19h6"/><path d="M3 5h18"/>',
    "trash-2": '<path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
               '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
                      '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
}

ICON_TOKEN_RE = re.compile(r"\{\{ic:([a-z0-9-]+)\}\}")


def icon_svg(name: str, icons: Mapping[str, str] = LUCIDE) -> str:
    """One icon of the table as an inline <svg>. Attributes are kept as-is; size is set by CSS (.ic).
    Produces the same shape as the viewer's JS ic() (the regression tests compare them). An unknown name raises
    KeyError: a {{ic:...}} token the table lacks is a packaging defect."""
    return ('<svg class="ic ic-%s" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">%s</svg>'
            % (name, icons[name]))


def load_ui_messages(path: Path) -> dict[str, Message]:
    """The viewer's English message table (ui_en.json at path): Korean UI string -> English.

    The Korean strings in the HTML template stay the source; in English mode the viewer swaps every
    UI string it finds in this table (text, tooltips, aria labels, toasts). pins.md and the API are
    not translated — they are a language-stable contract for agents. The one other kind of key is
    `reason:<code>`: the English the viewer shows for an API error body with that reason (errText).
    A missing or unreadable file gives an empty table; an entry that is neither a non-empty string nor
    well-formed plural forms is dropped."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    def ok(v: object) -> bool:   # a string, or plural forms {"one": ..., "other": ...} for a template key with {n}
        """Whether v is a usable table value: a non-empty string, or plural forms with a string "other"."""
        if isinstance(v, str):
            return bool(v)
        return (isinstance(v, dict) and set(v) <= {"one", "other"} and isinstance(v.get("other"), str)
                and all(isinstance(x, str) and x for x in v.values()))
    return {k: v for k, v in d.items() if isinstance(k, str) and k and ok(v)}


def viewer_manifest(directory: Path) -> dict[str, tuple[str, ...]]:
    """The viewer's part files per marker, in page order, as listed in directory/parts.txt.

    The manifest is a marker line (__APP_CSS__, __APP_JS__) followed by the paths of its parts, relative to the
    folder; "#" starts a comment and blank lines are skipped. Every marker has a non-empty list, and a path appears
    once. Anything else is a packaging defect and raises ValueError (a missing manifest raises OSError).
    """
    parts: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in (directory / VIEWER_MANIFEST).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line in VIEWER_MARKERS and line not in parts:
            current = parts[line] = []
        elif current is not None and VIEWER_PART_RE.fullmatch(line):
            current.append(line)
        else:
            raise ValueError("viewer manifest %s: unexpected line %r" % (VIEWER_MANIFEST, raw))
    names = [n for ns in parts.values() for n in ns]
    if set(parts) != set(VIEWER_MARKERS) or not all(parts.values()) or len(names) != len(set(names)):
        raise ValueError("viewer manifest %s must list each of %s once, with parts, and no part twice"
                         % (VIEWER_MANIFEST, ", ".join(VIEWER_MARKERS)))
    return {m: tuple(parts[m]) for m in VIEWER_MARKERS}


def load_viewer_html(directory: Path) -> str:
    """The viewer page with its stylesheet and main script inlined, as one HTML string.

    index.html carries one __APP_CSS__ and one __APP_JS__ marker. The parts listed under each marker in parts.txt
    (viewer_manifest) are joined in that order, byte for byte, and put where the marker was - the CSS parts into the
    one <style>, the JS parts into the one <script>, so no build step or module loader is involved. Inlining keeps
    GET / a single response with no extra routes. A missing or malformed file is a packaging defect and raises
    (OSError / ValueError).
    """
    page = (directory / "index.html").read_text(encoding="utf-8")
    for marker, names in viewer_manifest(directory).items():
        text = "".join((directory / name).read_text(encoding="utf-8") for name in names)
        if page.count(marker) != 1 or any(m in text for m in VIEWER_MARKERS):
            raise ValueError("viewer template marker %s must appear exactly once in index.html" % marker)
        page = page.replace(marker, text)
    return page


def service_worker(directory: Path) -> str:
    """The service worker script GET /sw.js serves: directory/sw.js as it is, no placeholders.

    It shows the viewer's browser notifications (showNotification - Chrome on Android blocks the page's own new
    Notification()) and, on a click, brings the viewer tab forward and opens that pin - or, for the [되살리기] action
    on a 'dropped' notification, asks the tab to restore it; with no tab open, the new window's link carries
    &act=restore. It has no fetch handler, so app data and page images are never cached. A missing file is a
    packaging defect and raises OSError, like the page's parts."""
    return (directory / SERVICE_WORKER).read_text(encoding="utf-8")


def viewer_html(directory: Path, messages: Mapping[str, Message], *, pdfjs_version: str, mark: str,
                icons: Mapping[str, str]) -> str:
    """The viewer page served at GET /, before the run-time placeholders: build_html() fills those per instance.

    The page and its parts come from directory (load_viewer_html); pdfjs_version, the mark's SVG, the icon table and
    the message table fill their placeholders, in that order, and every {{ic:<name>}} token becomes its icon's <svg>.
    The JSON forms are sorted by key so the page does not depend on the table's order; the message table's "</" is
    escaped so a string can never close the <script> it sits in. Raises like load_viewer_html, and KeyError for an
    icon token the table lacks.
    """
    page = load_viewer_html(directory)
    page = page.replace("__PDFJS_VERSION__", pdfjs_version)
    page = page.replace("__LIMN_MARK__", mark)
    page = page.replace("__LUCIDE_JSON__", json.dumps(dict(icons), sort_keys=True))
    table = json.dumps(dict(messages), ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    page = page.replace("__UI_EN_JSON__", table)
    return ICON_TOKEN_RE.sub(lambda m: icon_svg(m.group(1), icons), page)
