"""Small text reads at 4.5:1 as it is drawn (docs/handbook/viewer.md §토큰 '흐린 글자는 작은 글자다', issue #277).

FrontendColourRoles checks token pairs - a token on the surfaces named in a list. A rule can still put the muted text
on a surface nobody listed, or dim it with an opacity, and pass: the excerpt's context line numbers drew the muted
text at 70% (3.4:1 in light, 4.0:1 under a dark hover) and the light subtle text sat on a hover's --accent at 3.8:1.
This walks the page as Chromium draws it instead. In each state - cards, done rows, the Trash, notices, the outline,
the documents bar, its popover and the navigation sheet, the composer's excerpt, verdict row and suggestion switch on
the manuscript, the reviewer's PDF and the figure, the page verdict lines, the changes view's commit list and diffs,
with a real mouse on rows and keyboard focus - it reads what the page draws as text: every text node (an SVG text's
fill), the generated text of ::before and ::after, a field's value and its placeholder. It composites each one's colour
with the backgrounds and opacities of the elements under it as the browser paints them, and holds small text to 4.5:1
and large text to 3:1, in the light and the dark theme, on a desktop with a mouse, a phone and an unfolded foldable.
A text inside a disabled control is not held (WCAG 1.4.3 exempts inactive controls). A text over a background image, a
gradient, a mask, a filter or a blend - which this compositing cannot paint - is a failure unless UNPAINTED names the
element that carries it and why.

Every style rule that sets text in the muted or subtle colour (directly or through a custom property that leads to
them), or sets an opacity, is either reached by the walk - it set the colour of, or dimmed, text the walk held - or
listed in NOT_WALKED with the reason its text needs no walk. A new such rule fails the walk's test until it is one or
the other.

Run: LIMN_TEST_REQUIRE_BROWSER=1 uv run pytest -q src/limn/viewer/tests/test_viewer_contrast.py
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

from limn.administration import serve_documents as startup_documents
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.location import source as pick_source
from limn.revisions import core as revisions, execution as revision_execution
from limn.security.access import LOCAL_ACTOR

import helpers_figure
from helpers import add_pin, minimal_pdf, ps
from helpers_access import ALICE, BOB, REPO_NEW, REPO_OLD, actor
from helpers_authority import post_authority
from helpers_browser import VIEWPORTS, BrowserBase, search_shortcut, settle

# The devices the walk runs on: a desktop with a mouse and a phone run every scene; the unfolded foldable's mid band (its
# own nav bar with the page indicator, a side panel over the page) runs the list.
DEVICES = {
    "desktop": VIEWPORTS["desktop 1440x900"],
    "phone": VIEWPORTS["phone 390x844"],
    "fold": VIEWPORTS["fold inner 841x673"],
}
THEMES = ("light", "dark")
# The documents: the LaTeX manuscript, the figure and the reviewer's PDF of helpers_figure, and enough view-only PDFs that
# the desktop's documents bar folds the rest into [+N] and its popover.
EXTRA_DOCS = [
    "sp=보충 자료:sp.pdf",
    "cl=Cover letter:cl.pdf",
    "hl=Highlights:hl.pdf",
    "ga=그래픽 초록:ga.pdf",
    "da=Appendix A data:da.pdf",
    "db=부록 B 유도:db.pdf",
]
WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}]}
OUTLINE = [("Introduction", 1), ("Methods", 1), ("Results", 2)]  # the manuscript PDF's outline: (title, page)


def outline_pdf(entries, pages=2):
    """A PDF.js-readable PDF of `pages` letter pages, each with one Helvetica line, and a top-level outline of entries
    (ASCII title, 1-based page), each pointing at the top of its page."""
    root = 4 + 2 * pages  # objects: catalog, pages, font, then each page and its content, then the outline
    kids = " ".join("%d 0 R" % (4 + 2 * i) for i in range(pages))
    objs = [
        "<< /Type /Catalog /Pages 2 0 R /Outlines %d 0 R >>" % root,
        "<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, pages),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i in range(pages):
        body = "BT /F1 24 Tf 72 700 Td (Page %d) Tj ET" % (i + 1)
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R"
            " /Resources << /Font << /F1 3 0 R >> >> >>" % (5 + 2 * i)
        )
        objs.append("<< /Length %d >>\nstream\n%s\nendstream" % (len(body), body))
    m = len(entries)
    objs.append("<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>" % (root + 1, root + m, m))
    for i, (title, at) in enumerate(entries):
        links = "".join(" /%s %d 0 R" % (k, root + 1 + j) for k, j in (("Prev", i - 1), ("Next", i + 1)) if 0 <= j < m)
        objs.append(
            "<< /Title (%s) /Parent %d 0 R%s /Dest [%d 0 R /XYZ 72 740 0] >>" % (title, root, links, 4 + 2 * (at - 1))
        )
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o.encode("ascii") + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


# PRELUDE: the page's style rules that set a colour or an opacity, as {key, sel, conds, color, opacity, dims}: a rule is
# keyed by its selector after the @media and @supports conditions it sits in, and it dims text (dims) when it sets an
# opacity or its colour leads to the muted or subtle token - directly, or through custom properties defined anywhere on
# the page whose values lead there. resolveAt(e, value) resolves a colour value as it resolves on element e: its custom
# properties as e computes them. Shared by READ and PAIRS, with the colour helpers they use.
PRELUDE = r"""
  const rules = [], defs = [];
  const visit = (list, conds) => { for (const r of list) {
    if (r instanceof CSSMediaRule) visit(r.cssRules, conds.concat('@media ' + r.conditionText));
    else if (r instanceof CSSSupportsRule) visit(r.cssRules, conds.concat('@supports ' + r.conditionText));
    else if (r instanceof CSSStyleRule) { const color = r.style.getPropertyValue('color').trim(), opacity = r.style.getPropertyValue('opacity').trim();
      for (const p of r.style) if (p.startsWith('--')) defs.push([p, r.style.getPropertyValue(p)]);
      if (color || opacity) rules.push({key: conds.concat(r.selectorText).join(' '), sel: r.selectorText, conds, color, opacity}); } } };
  for (const s of document.styleSheets) visit(s.cssRules, []);
  const refs = v => [...String(v).matchAll(/var\(\s*(--[\w-]+)/g)].map(m => m[1]);
  const dim = new Set(['--muted-foreground', '--subtle-foreground']);
  for (let grew = true; grew;) { grew = false;
    for (const [name, value] of defs) if (!dim.has(name) && refs(value).some(n => dim.has(n))) { dim.add(name); grew = true; } }
  for (const r of rules) r.dims = r.opacity !== '' || refs(r.color).some(n => dim.has(n));
  const rgba = s => { let m = /^rgba?\(([^)]+)\)/.exec(s || '');
    if (m) { const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = /^color\(srgb ([^)]+)\)/.exec(s || '');
    if (m) { const p = m[1].split(/[\s\/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1]; }
    return null; };
  const probe = document.createElement('i'); probe.style.display = 'none'; document.body.append(probe);
  const resolve = v => { probe.style.color = ''; probe.style.color = v; return probe.style.color ? getComputedStyle(probe).color : null; };
  const resolveAt = (e, v) => { let s = String(v);
    for (let k = 0; k < 20 && /var\(/.test(s); k++)
      s = s.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*))?\)/g, (_, n, f) => getComputedStyle(e).getPropertyValue(n).trim() || f || 'transparent');
    return resolve(s); };
  const pm = c => [c[0] * c[3], c[1] * c[3], c[2] * c[3], c[3]], over = (a, b) => [0, 1, 2, 3].map(k => a[k] + b[k] * (1 - a[3]));
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
"""

# READ([root, unpainted]): what the page draws as text under root (default the body), as drawn. For every text node with a
# box (an SVG text by its fill), every ::before and ::after whose content is text, every text field's value and every empty
# field's placeholder - outside .sr-only and a disabled control, not hidden and not fully transparent: its colour and
# the colour beside it as painted - each ancestor's background stacked from the page up, a pseudo-element's own background
# on top, every element's opacity fading its own paint and all inside it as a group, as the browser composites them -
# their WCAG ratio and the ratio it needs (4.5, or 3 for large text: 24px, or 18.66px at weight 700). A text with a
# background image, a gradient, a mask, a filter or a blend on an element under it is not composited: unless that element
# matches a selector of unpainted, it comes back in `blind`. With them, the keys of the dimming rules (PRELUDE) and of
# those this text used: among the rules setting the colour of the pseudo-element (::before, ::after, ::placeholder) or
# else of the nearest element that has one, those whose colour, resolved there, is the one drawn; and every rule setting
# an opacity under 1 on what is under the text.
READ = (
    "([root, unpainted]) => {"
    + PRELUDE
    + r"""
  root = root || document.body;
  const css = new Map(), style = (e, p) => { const k = p ? p : ''; let m = css.get(e); if (!m) css.set(e, m = {});
    return m[k] || (m[k] = getComputedStyle(e, p || null)); };
  const live = r => r.conds.every(c => c.startsWith('@media ') ? matchMedia(c.slice(7)).matches : CSS.supports(c.slice(10)));
  const hits = (e, sel) => { try { return e.matches(sel); } catch (x) { return false; } };
  // whether sel (a selector list) selects e's pseudo-element p ('::before', '::after', '::placeholder')
  const parts = sel => { const out = []; let d = 0, s = '';
    for (const ch of sel) { if (ch === '(') d++; if (ch === ')') d--; if (ch === ',' && !d) { out.push(s.trim()); s = ''; } else s += ch; }
    return out.concat(s.trim()); };
  const hitsPseudo = (e, sel, p) => parts(sel).some(x => { const k = x.replace(/:?(:before|:after|:placeholder)$/, m => m.replace(/^::?/, '::'));
    return k.endsWith(p) && hits(e, k.slice(0, -p.length) || '*'); });
  const flat = e => { const c = style(e); return c.backgroundImage !== 'none' ? 'background-image'
    : (c.maskImage && c.maskImage !== 'none') || (c.webkitMaskImage && c.webkitMaskImage !== 'none') ? 'mask'
    : c.filter !== 'none' ? 'filter' : c.mixBlendMode !== 'normal' ? 'mix-blend-mode' : ''; };
  const excused = e => unpainted.some(s => hits(e, s));
  // One pixel under the text (text: its colour) or beside it (text: null): a pseudo-element's background and the text in
  // it, then each element paints its background under what is inside it, and its opacity fades the lot; the canvas is white.
  const paint = (chain, text, pseudo) => { let g = null;
    if (pseudo) { const own = pm(rgba(pseudo.backgroundColor) || [0, 0, 0, 0]); g = (text ? over(pm(text), own) : own).map(v => v * Number(pseudo.opacity)); }
    chain.forEach((e, i) => { const own = pm(rgba(style(e).backgroundColor) || [0, 0, 0, 0]), o = Number(style(e).opacity);
      g = (g === null ? (text ? over(pm(text), own) : own) : over(g, own)).map(v => v * o); });
    return over(g, [255, 255, 255, 1]); };
  const hex = c => '#' + c.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const name = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + [...e.classList].slice(0, 3).map(c => '.' + c).join('');
  const where = e => { const out = [name(e)]; for (let p = e.parentElement; p && out.length < 4 && !/#/.test(out[0]); p = p.parentElement)
    if (p.id || p.classList.length) out.unshift(name(p)); return out.join(' > '); };
  const shown = e => e.getClientRects().length > 0 && style(e).visibility === 'visible';
  const texts = [], blind = [], used = new Set();
  // read(el, words, p, colourOf): one drawn text in element el (in its pseudo-element p, or '' for el's own text).
  const read = (el, words, p, colour) => {
    if (!colour || el.closest('.sr-only,:disabled,[aria-disabled=true]')) return;
    const chain = []; for (let e = el; e; e = e.parentElement) chain.push(e);
    const ps = p && p !== '::placeholder' ? style(el, p) : null;
    if (colour[3] * (ps ? Number(ps.opacity) : 1) * chain.reduce((o, e) => o * Number(style(e).opacity), 1) === 0) return;
    const at = where(el) + (p || '');
    const odd = chain.find(e => flat(e));
    if (odd) { if (!excused(odd)) blind.push(at + " '" + words + "' over " + flat(odd) + ' on ' + where(odd)); return; }
    const cs = ps || style(el, p === '::placeholder' ? p : null);
    const fg = paint(chain, colour, ps), bg = paint(chain, null, ps);
    const size = parseFloat(cs.fontSize), large = size >= 24 || (size >= 18.66 && Number(cs.fontWeight) >= 700);
    texts.push({text: words, where: at, ratio: ratio(fg, bg), need: large ? 3 : 4.5, fg: hex(fg), bg: hex(bg)});
    const drawn = (p ? style(el, p) : style(el)).color;
    let mine = p ? rules.filter(r => r.color && r.color !== 'inherit' && live(r) && hitsPseudo(el, r.sel, p)) : [];
    if (mine.length) mine.filter(r => r.dims && resolveAt(el, r.color) === drawn).forEach(r => used.add(r.key));
    else for (const e of chain) { const own = rules.filter(r => r.color && r.color !== 'inherit' && live(r) && hits(e, r.sel));
      if (!own.length) continue; own.filter(r => r.dims && resolveAt(e, r.color) === style(e).color).forEach(r => used.add(r.key)); break; }
    if (p) rules.filter(r => r.opacity && live(r) && hitsPseudo(el, r.sel, p) && Number(r.opacity) < 1).forEach(r => used.add(r.key));
    for (const e of chain) if (Number(style(e).opacity) < 1)
      rules.filter(r => r.opacity && live(r) && hits(e, r.sel)).forEach(r => used.add(r.key));
  };
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let t; (t = walker.nextNode());) {
    const words = t.textContent.replace(/\s+/g, ' ').trim(), el = t.parentElement;
    if (!words || !el || el.closest('script,style,template,textarea,title')) continue;
    const range = document.createRange(); range.selectNodeContents(t);
    if (![...range.getClientRects()].some(b => b.width >= 1 && b.height >= 1) || style(el).visibility !== 'visible') continue;
    read(el, words.slice(0, 40), '', rgba(el instanceof SVGElement ? style(el).fill : style(el).color));
  }
  for (const el of [root, ...root.querySelectorAll('*')]) {
    if (!shown(el)) continue;
    for (const p of ['::before', '::after']) { const c = style(el, p), words = String(c.content).replace(/"([^"]*)"/g, '$1');
      if (c.content === 'none' || c.content === 'normal' || /url\(/.test(c.content) || !words.trim() || c.display === 'none' || c.visibility !== 'visible') continue;
      read(el, words.trim().slice(0, 40), p, rgba(c.color)); }
    if (el.matches('textarea,input:not([type]),input[type=text],input[type=search],input[type=email],input[type=url],input[type=number],input[type=tel],input[type=password]')) {
      if (el.value.trim()) read(el, el.value.trim().slice(0, 40), '', rgba(style(el).color));
      else if (el.placeholder.trim()) read(el, el.placeholder.trim().slice(0, 40), '::placeholder', rgba(style(el, '::placeholder').color)); }
  }
  probe.remove();
  return {texts, blind, used: [...used], rules: [...new Set(rules.filter(r => r.dims).map(r => r.key))]};
}"""
)

# PAIRS([[key, need]], surfaces): for each dimming rule named, its colour - faded by the opacity of every rule with its
# selector - drawn on each surface token: the lowest ratio under need, as "key: ratio on --surface"; a rule the page lacks
# or one without a colour is reported as such.
PAIRS = (
    "([named, surfaces]) => {"
    + PRELUDE
    + r"""
  const out = [];
  for (const [key, need] of named) { const r = rules.find(x => x.key === key);
    if (!r || !r.color) { out.push(key + ': no colour rule'); continue; }
    const fg = rgba(resolve(r.color)), fade = rules.filter(x => x.sel === r.sel && x.opacity).reduce((o, x) => o * Number(x.opacity), 1);
    fg[3] *= fade;
    for (const s of surfaces) { const bg = rgba(resolve('var(' + s + ')')), x = ratio(over(pm(fg), pm(bg)), bg);
      if (x < need) out.push(key + ': ' + x.toFixed(2) + ' on ' + s); } }
  probe.remove();
  return out;
}"""
)

# The plain surfaces secondary text sits on: the panes, the badge and track fills, and a hover's or a current row's --accent.
SURFACES = (
    "--background",
    "--sidebar",
    "--card",
    "--popover",
    "--field",
    "--code",
    "--muted",
    "--secondary",
    "--accent",
)
# What an excused rule is held to: its text at 4.5:1 (TEXT) or its icon at 3:1 (ICON) on every one of SURFACES in both
# themes, faded by its selector's opacity; or nothing (INACTIVE: a disabled or waiting control, which WCAG 1.4.3 exempts,
# or a drag's passing fade). This is a supplement for what the walk cannot draw: it knows no ancestor's opacity and no
# state's background.
TEXT, ICON, INACTIVE = 4.5, 3.0, None

# The dimming rules the walk does not reach, keyed as READ keys them: what each is held to instead, and why the walk does
# not reach it. A rule here that the walk reaches, or that the page lacks, fails the walk's test, so the list stays true.
NOT_WALKED: dict[str, tuple[float | None, str]] = {
    # icons: non-text, 3:1
    "#more .more-grid button > .ic:last-child:not(:first-child)": (ICON, "[더보기] rows' trailing chevron"),
    "#nav-toc-toggle": (ICON, "the outline toggle, an icon button"),
    "#search-box button": (ICON, "search's previous, next and close, icon buttons"),
    "#search-field .ic": (ICON, "the search field's magnifier"),
    "#search-open": (ICON, "the folded search field's magnifier button"),
    "#status button.nt-x": (ICON, "a status line message's [x]"),
    ".nt-acts button.nt-x": (ICON, "a message's [x]"),
    ".av.agent": (ICON, "an agent's avatar, a bot icon on --accent"),
    ".pin .card-meta .as-chip .ic": (ICON, "the pressable assignee's pencil"),
    ".quote .q-ic": (ICON, "a quote's icon"),
    ".sec-tg > .ic": (ICON, "a section head's chevron"),
    "body.lay-narrow #bar1 #btn-pos .ic": (ICON, "the phone tool bar's location icon"),
    "body.lay-wide #bar1 #btn-more": (ICON, "the desktop tool bar's [더보기], an icon button"),
    # inactive or passing: not held
    "button:disabled": (INACTIVE, "a disabled control"),
    '.vd-btns button[aria-disabled="true"]': (INACTIVE, "a verdict button that cannot be pressed"),
    "#composer:has(#c-body.busy) #c-verdict-row button": (INACTIVE, "the verdict buttons while their save is out"),
    ".busy": (INACTIVE, "a control waiting for the server's answer"),
    '.nt-act[aria-busy="true"]': (INACTIVE, "a message's action while its request is out"),
    "#m-rebuild .m-tail": (
        INACTIVE,
        "[더보기]'s '빌드 중', shown only while its button is disabled by a running build",
    ),
    "body.lay-wide.side-snap-collapse #bar1, body.side-snap-collapse :is(#bar2, #build-err, #banner, #composer, #list, "
    "#c-actions)": (INACTIVE, "the panel fading while a drag is about to collapse it"),
    # a container's default colour that no text takes: each part inside sets its own
    "#outline-items button": (TEXT, "an outline entry's default: its title, number and page set their own colours"),
    "#section-strip": (TEXT, "the section strip's default: its section and page set their own colours"),
    ".pv": (TEXT, "a page verdict line's default: its parts set their own colours"),
    ".msg.ev": (TEXT, "a state record's default: its head sets its own colour, and the walk's records carry no note"),
    # text in a state the walk's fixture does not reach
    "#doc-select-wrap label": (TEXT, "the documents select's label: no rule shows #doc-select-wrap in any band"),
    ".rv-close": (TEXT, "a review card's closing line: no script draws it"),
    "#more .m-l small": (TEXT, "[더보기]'s '지금 밝게' under the system theme: the walk sets the theme"),
    "#revision-more": (TEXT, "the commit list's [더 보기]: needs more commits than one page of the list"),
    ".hint": (TEXT, "the empty pin list's hint: needs an instance with no pins at all"),
    ".m-preview .m-sep": (
        TEXT,
        "the reply preview's separator before an assignee change: the walk changes no assignee",
    ),
    ":is(.as-seg, .m-preview, .card-meta) .ml": (
        TEXT,
        "the login beside a name two people share: the walk's names differ",
    ),
    ".ov-no": (TEXT, "the figure overlay's page number: needs a figure with two builds in the changes view"),
    ".ov-none": (TEXT, "the figure overlay's missing page: needs a figure with two builds in the changes view"),
    ".sg-text[readonly]": (TEXT, "a closed pin's suggested edit in its edit card: the walk edits no closed pin"),
}

# The elements that may carry what READ cannot composite (a background image, a gradient, a mask, a filter, a blend) under
# text, as selectors, and why the text there needs no compositing.
UNPAINTED: dict[str, str] = {}  # none today: the walk found no text over one


def fake_compile(spec, jobdir, timeout):
    """A comparison build that writes a one-page PDF instead of running latexdiff and latexmk."""
    (jobdir / "revision.pdf").write_bytes(minimal_pdf("diff"))
    return revisions.ComparisonBuilt([])


class ContrastWalk(BrowserBase):
    """A Git manuscript of three commits by two authors, served with the figure document, the reviewer's PDF and six more
    view-only PDFs; the manuscript's build carries a PDF with an outline, and the manuscript and the reviewer's PDF have
    verdict words (the PDF's on its pages). The pins draw every list row: an open request assigned to Bob with a thread,
    an open question, a pin an agent closed (awaiting review) whose range is a changed line and the unchanged line above
    it, a done pin and a dropped one. Holds the walk's scenes, none of its tests; the comparison build is faked, and the
    figure's and the PDF's picks go to the real handler."""

    WHO = ALICE
    maxDiff = None  # every short text in the report, not the first

    def setUp(self):
        """Serve the documents, commit the manuscript three times, seed the pins, and fake the comparison build."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        src = ps.APP.C.src
        self.main.write_text(REPO_OLD, encoding="utf-8")
        self.docs = self.serve_documents(src)
        for name, page in (("main", False), ("reviewer", True)):
            (src / ("%s.limnverdicts.json" % name)).write_text(json.dumps({**WORDS, "page": page}), encoding="utf-8")
        patch = mock.patch.object(pick_source, "region_text", return_value="")
        patch.start()
        self.addCleanup(patch.stop)
        A, B = actor(ALICE), actor(BOB)
        ps.APP.people_directory.record(A)
        ps.APP.people_directory.record(B)
        self.repo = self.main.parent.parent
        self.git("init", "--quiet")
        self.commit(REPO_OLD, "Bob Park", "첫 원고")
        store = ps.APP.pin_lifecycle.context
        self.thread = add_pin(
            {
                "file": str(self.main),
                "lo": 6,
                "hi": 7,
                "page": 1,
                "note": "이 문단을 줄여 주세요",
                "assignee": BOB["Tailscale-User-Login"],
            },
            A,
        ).record["id"]
        add_pin(
            {"file": str(self.main), "lo": 13, "hi": 13, "page": 1, "note": "근거가 있나요?", "kind_req": "question"}, B
        )
        self.review = add_pin({"file": str(self.main), "lo": 3, "hi": 4, "page": 1, "note": "첫 문장 보강"}, A).record[
            "id"
        ]
        done = add_pin({"file": str(self.main), "lo": 9, "hi": 9, "page": 1, "note": "오타"}, A).record["id"]
        gone = add_pin({"file": str(self.main), "lo": 10, "hi": 10, "page": 1, "note": "지울 핀"}, A).record["id"]
        fix = self.commit(REPO_NEW, "Alice Kim", "첫 문단 보강")
        self.commit(REPO_NEW.replace("Filler two.", "Filler two, reworded."), "Bob Park", "채움 문장 다듬기")
        ps.APP.pin_lifecycle.close_pin(
            self.review,
            post_authority(store().store, dict(LOCAL_ACTOR), "close", self.review),
            CloseRequest(reply="한 문장을 더했습니다", ref=fix[:8]),
        )
        ps.APP.pin_lifecycle.close_pin(
            done, post_authority(store().store, A, "close", done), CloseRequest(reply="고쳤습니다")
        )
        for who, text in (
            (B, "어느 문장을 뺄까요?"),
            (A, "#%d 와 같은 문제입니다" % gone),
            (B, "둘째 문장을 뺍니다. " * 30),
            (A, "좋습니다"),
        ):  # four entries: the oldest folds under [이전 1건 보기], a long one under [더 보기], a reference to a deleted pin
            ps.APP.pin_lifecycle.reply_pin(self.thread, text, post_authority(store().store, who, "reply", self.thread))
        ps.APP.pin_trash.drop_pin(gone, post_authority(ps.APP.pin_trash.context().store, A, "drop", gone))
        lines = self.main.read_text(encoding="utf-8").splitlines()
        at = (
            lines.index("Filler three.") + 1
        )  # a suggested edit of nine lines for one: its diff folds, with [제안 펼치기]
        suggest = {"base": lines[at - 1], "text": "\n".join("Filler three, part %d." % i for i in range(9))}
        self.suggested = add_pin(
            {"file": str(self.main), "lo": at, "hi": at, "page": 1, "note": "나눠 씁니다", "suggest": suggest}, A
        ).record["id"]
        old = time.time() - 3600  # the sources an hour older than the builds: the builds are current
        for path in src.rglob("*"):
            if ".git" not in path.parts:
                os.utime(path, (old, old))
        patcher = mock.patch.object(revision_execution, "revision_compile", side_effect=fake_compile)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def serve_documents(src):
        """Serve the manuscript (ms), the figure (fig), the reviewer's PDF (rv) and EXTRA_DOCS, each with a two-page build on
        screen; the manuscript's PDF copy has OUTLINE. The documents, in the bar's order."""
        (src / "reviewer.pdf").write_bytes(minimal_pdf("reviewer"))
        for spec in EXTRA_DOCS:
            name = spec.rsplit(":", 1)[1]
            (src / name).write_bytes(minimal_pdf(name.split(".")[0]))
        docs = startup_documents.make_docs(
            ["ms=본문:main.tex", "rv=리뷰어:reviewer.pdf", *EXTRA_DOCS], src, ps.APP.C.paths
        )
        assert isinstance(docs, list), docs
        ms, rv, *extra = docs
        fig = helpers_figure.figure_doc(src, ps.APP.C.paths)
        ps.APP.set_docs([ms, fig, rv, *extra])
        for D in (ms, fig, rv, *extra):
            helpers_figure.viewer_build(
                D, helpers_figure.BUILD1, helpers_figure.viewer_map() if D.has_element_map else None
            )
        (Path(ms.dir) / helpers_figure.BUILD1 / ms.pdf_name).write_bytes(outline_pdf(OUTLINE))
        return [ms, fig, rv, *extra]

    def tearDown(self):
        """Stop serving the documents, then BrowserBase's teardown."""
        ps.APP.set_docs(None)
        super().tearDown()

    def route(self, route):
        """A pick on the figure or the reviewer's PDF goes to the handler; the manuscript's gets BrowserBase's answer."""
        rq = route.request
        if urlparse(rq.url).path == "/api/pick" and json.loads(rq.post_data or "{}").get("doc") in ("fig", "rv"):
            return self.forward(route)
        return super().route(route)

    def git(self, *args):
        """Run Git in the manuscript's repository; its stdout, stripped."""
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, text, author, message):
        """Write text to the manuscript and commit the manuscript's folder as author; the commit's hash."""
        self.main.write_text(text, encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))
        self.git("add", self.main.parent.name)
        self.git("-c", "user.name=" + author, "-c", "user.email=a@example.com", "commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    # ------------------------------------------------------------ reading
    def look(self, page, state, root=None):
        """READ root (a selector, or the whole page) in the light and the dark theme, after the switch has settled;
        each text under its ratio or not composited goes to self.short and each rule a held text used to self.used."""
        for theme in THEMES:
            page.evaluate("t=>setTheme(t)", theme)
            settle(page)
            handle = page.query_selector(root) if root else None
            if root and handle is None:
                self.short.append("%s %s: nothing at %s" % (theme, state, root))
                continue
            out = page.evaluate(READ, [handle, list(UNPAINTED)])
            self.rules.update(out["rules"])
            self.used.update(out["used"])
            self.short.extend("%s %s %s: cannot composite %s" % (theme, self.device, state, b) for b in out["blind"])
            self.short.extend(
                "%s %s %s: %s '%s' %.2f < %s (%s on %s)"
                % (theme, self.device, state, t["where"], t["text"], t["ratio"], t["need"], t["fg"], t["bg"])
                for t in out["texts"]
                if t["ratio"] < t["need"]
            )

    def hover(self, page, sel, state):
        """Move the mouse onto the first visible sel and READ it hovered (desktop only: touch answers no hover)."""
        if self.device != "desktop":
            return
        loc = page.locator(sel).first
        loc.scroll_into_view_if_needed()
        loc.hover()
        settle(page)
        self.assertTrue(loc.evaluate("e=>e.matches(':hover')"), sel)
        self.look(page, state, sel + ":hover")
        page.mouse.move(1, 1)

    def focus(self, page, sel, state):
        """Give the first sel the keyboard's focus (a key press first, so :focus-visible matches) and READ it."""
        page.keyboard.press("Shift")
        page.focus(sel)
        settle(page)
        self.assertTrue(page.evaluate("s=>document.querySelector(s).matches(':focus-visible')", sel), sel)
        self.look(page, state, sel + ":focus-visible")

    def show_doc(self, page, key):
        """Switch the viewer to document key and wait until its pages are there."""
        page.evaluate("k=>switchDoc(k)", key)
        page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p1')", arg=key)
        settle(page)

    # ------------------------------------------------------------ scenes
    def scene_list(self):
        """The pin list with every section open and three cards unfolded (a thread with a folded entry, a long post and a
        deleted pin's reference; the review; a suggested edit folded past five rows); a reply being written, with its
        mention list and its preview naming a stranger; the thread's edit card; a hovered card, done row and section tool;
        a banner of each kind on the list and a message on the status line; [더보기]; the desktop's search field and a
        search; the outline (hovered and focused entries, filtered to nothing) or the navigation sheet (likewise); the
        documents bar's popover, filtered to nothing; the Trash and a hovered trash row."""
        page = self.open(2, **DEVICES[self.device])
        page.evaluate(
            "ids=>{setSide(true); SEC.done=true; SEC.review=true; ids.forEach(i=>OPEN_CARDS.add(i)); drawPins();}",
            [self.thread, self.review, self.suggested],
        )
        settle(page)
        self.look(page, "list")
        card = '#review-pins .pin[data-id="%d"]' % self.review
        page.click(card + " .acts [data-act=reply-open]")
        page.fill(card + " textarea.r-text", "@Bo")
        page.wait_for_selector("#mention-pop:not([hidden]) [data-act=mention-pick]")
        settle(page)
        self.look(page, "mention list", "#mention-pop")
        page.fill(card + " textarea.r-text", "@Bob Park 확인 부탁합니다 @없는사람 도요")
        page.wait_for_selector(card + " .m-preview:not([hidden])")
        settle(page)
        self.look(page, "reply box", card)
        page.evaluate("id=>openEdit(id)", self.thread)
        page.wait_for_selector(".edit .e-xp .xp-row")
        settle(page)
        self.look(page, "edit card", ".edit")
        page.keyboard.press("Escape")
        settle(page)
        self.hover(page, '#pins .pin[data-id="%d"]' % self.thread, "card")
        self.hover(page, "#done-list .arc-row", "done row")
        self.hover(page, "#sec-open .sec-head button:not(.sec-tg)", "section tool")
        for kind in ("err", "warn", "ok", "info"):
            page.evaluate(
                "k=>bannerNote(NOTICE_HOST.LIST,'알림 제목 — 알림 설명',k,{label:'다시 시도',run:()=>{}},{literal:true})",
                kind,
            )
            self.look(page, "banner " + kind, "#list .nt-banner")
        page.evaluate("()=>lineNote('상태 줄 알림 — 설명',NOTICE_KIND.WARN,{label:'보기',run:()=>{}},{literal:true})")
        self.look(page, "status line", "#status")
        page.click("#btn-more")
        page.wait_for_selector("#more[open]")
        settle(page)
        self.look(page, "more", "#more")
        page.keyboard.press("Escape")
        settle(page)
        if self.device == "desktop":
            self.look(page, "search field", "#doc-nav")
            page.click("#p1")
            search_shortcut(page)
            page.fill("#search-q", "Page")
            page.wait_for_function("/^\\d+\\/\\d+$/.test(document.querySelector('#search-count').textContent)")
            settle(page)
            self.look(page, "search", "#doc-nav")
            page.keyboard.press("Escape")
            settle(page)
        if page.locator("#nav-toc-toggle").is_visible():
            if page.get_attribute("#nav-toc-toggle", "aria-expanded") != "true":
                page.click("#nav-toc-toggle")
            page.wait_for_selector("#outline-items button")
            settle(page)
            self.look(page, "outline", "#outline")
            self.hover(page, "#outline-items button:not(.ol-active)", "outline entry")
            self.focus(page, "#outline-items button:not(.ol-active)", "outline entry")
            page.fill("#outline-search", "없는 절")
            page.wait_for_selector("#outline-items.outline-empty")
            settle(page)
            self.look(page, "outline, no match", "#outline")
        if page.locator("#btn-pos").is_visible():
            page.click("#btn-pos")
            page.wait_for_selector("#nav-sheet[open] #ns-outline-items button")
            settle(page)
            self.look(page, "navigation sheet", "#nav-sheet")
            page.fill("#ns-outline-search", "없는 절")
            page.wait_for_selector("#ns-outline-items.outline-empty")
            settle(page)
            self.look(page, "navigation sheet, no match", "#nav-sheet")
            page.keyboard.press("Escape")
            settle(page)
        if page.locator("#doc-more").is_visible():
            page.click("#doc-more")
            page.wait_for_selector("#doc-pop:not([hidden]) .dp-row")
            settle(page)
            self.look(page, "documents popover", "#doc-pop")
            self.hover(page, "#doc-pop .dp-row:not(.on)", "documents popover row")
            page.fill("#doc-pop-in", "없는 문서")
            page.wait_for_selector("#doc-pop-none:not([hidden])")
            settle(page)
            self.look(page, "documents popover, no match", "#doc-pop")
            page.keyboard.press("Escape")
            settle(page)
        page.evaluate("openTrash()")
        page.wait_for_selector("#trash[open] .arc-row")
        self.look(page, "trash", "#trash")
        self.hover(page, "#trash .arc-row", "trash row")
        page.context.close()

    def scene_composer(self):
        """A picked line's composer: on the desktop the selection popover of a real drag first; the excerpt's band and its
        dimmed neighbours, a hovered and a focused neighbour, the hovered [핀 저장] with its shortcut; the verdict row and
        its reason with the kind a question and with [제안 수정] on, and the suggestion's editor; a band widened until it
        folds."""
        page = self.open(2, **DEVICES[self.device])
        if self.device == "desktop":
            box = page.locator("#p1").bounding_box()
            x, y = box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.3
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 120, y + 30, steps=8)
            page.mouse.up()
            page.wait_for_selector("#sel-pop:not([hidden])")
            page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
            settle(page)
            self.look(page, "selection popover", "#sel-pop")
            page.click("#sel-pop [data-act=pop-more]")
        else:
            page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo&&document.querySelector('#c-xp .xp-row.ctx')")
        settle(page)
        self.look(page, "composer")
        self.hover(page, "#c-xp .xp-row.ctx", "excerpt neighbour")
        self.hover(page, "#btn-save", "save button")
        self.focus(page, "#c-xp .xp-row.ctx", "excerpt neighbour")
        page.click('#c-kind button[data-kind="question"]')
        page.wait_for_selector("#c-verdict-row .vd-why")
        settle(page)
        self.look(page, "question's verdict row", "#composer")
        page.click('#c-kind button[data-kind="fix"]')
        page.click("#c-sg-tg")
        page.wait_for_selector("#c-sg:not([hidden]) #c-sg-text")
        settle(page)
        self.look(page, "suggestion on", "#composer")
        page.click("#c-sg-tg")
        settle(page)
        for _ in range(5):  # widen the band downwards past five lines: it folds, and [원문 펼치기] offers the rest
            hi = page.evaluate("COMPOSE.current.hi")
            page.click('#c-xp .xp-row.ctx[data-line="%d"]' % (hi + 1))
            page.wait_for_function("n=>COMPOSE.current.hi===n", arg=hi + 1)
            settle(page)
        page.wait_for_selector("#c-xp .xp-fold")
        self.look(page, "folded excerpt", "#composer")
        page.context.close()

    def scene_documents(self):
        """The reviewer's PDF: its page verdict lines (a hovered word) and a composer on an area of it, where a suggestion cannot go; the figure with a
        composer on one of its elements (the element's path)."""
        page = self.open(2, **DEVICES[self.device])
        self.show_doc(page, "rv")
        page.wait_for_selector("#doc .pv")
        self.look(page, "page verdict lines", "#doc")
        self.hover(page, "#doc .pv button", "page verdict word")
        ptr = "mouse" if self.device == "desktop" else "touch"
        page.evaluate(
            "p=>{LAST_PTR=p; pick({doc:'rv',page:1,pdf_build:META.pages_build,x0:60,y0:60,x1:300,y1:120,frac:[0.1,0.08,0.4,0.08]});}",
            ptr,
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking&&!document.querySelector('#c-sg-why').hidden")
        page.evaluate("setSide(true)")
        settle(page)
        self.look(page, "composer on a PDF area", "#composer")
        page.keyboard.press("Escape")
        self.show_doc(page, "fig")
        page.evaluate(
            "p=>{LAST_PTR='%s'; pick({doc:'fig',page:1,pdf_build:META.pages_build,x0:p[0]*META.pages[0].pt_w,"
            "y0:p[1]*META.pages[0].pt_h,x1:(p[0]+p[2])*META.pages[0].pt_w,y1:(p[1]+p[3])*META.pages[0].pt_h,frac:p});}"
            % ptr,
            list(helpers_figure.CELL_DRAG),
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking&&!document.querySelector('#c-path').hidden")
        page.evaluate("setSide(true)")
        settle(page)
        self.look(page, "composer on a figure element", "#composer")
        page.context.close()

    def scene_changes(self):
        """The changes view: its commit list with the painted range, each commit row hovered; the source diff's added and
        removed rows; the review pin's diff, its range highlighted on an unchanged line, and its comparison with the
        [커밋 전체 비교] toggle off."""
        page = self.open(2, **DEVICES[self.device])
        if page.locator("#view-revisions").is_visible():
            page.click("#view-revisions")
        else:
            page.click("#btn-pos")
            page.locator("#nav-sheet [data-mode=revisions]").click()
        page.wait_for_function(
            "REV.rowsDoc===DOC&&REV.commit!==''&&document.querySelector('#revision-commits .rc-row.in')"
        )
        settle(page)
        self.look(page, "changes", "#revision-view")
        for n in (1, 2, 3):
            self.hover(page, "#revision-commits .rc-row:nth-child(%d)" % n, "commit row %d" % n)
        self.hover(page, "#revision-commits .rc-row.in", "painted commit row")
        page.click("#revision-source-tab")
        page.wait_for_selector("#revision-diff .rd-add")
        settle(page)
        self.look(page, "source diff", "#revision-view")
        page.evaluate("id=>showChange(id)", self.review)
        page.wait_for_selector("#revision-diff .rd-pin.rd-context")
        settle(page)
        self.look(page, "pin's diff", "#revision-view")
        page.click("#revision-pdf-tab")
        page.wait_for_selector("#revision-whole:not([hidden])")
        settle(page)
        self.look(page, "pin's comparison", "#revision-controls")
        page.context.close()

    def walk(self):
        """Run every scene on the desktop and the phone, and the list on the foldable, collecting self.short, self.used and
        self.rules."""
        self.short, self.used, self.rules = [], set(), set()
        for self.device in DEVICES:
            self.scene_list()
            if self.device == "fold":
                continue
            self.scene_composer()
            self.scene_documents()
            self.scene_changes()


class RenderedSecondaryContrast(ContrastWalk):
    """The walk on a desktop, a phone and a foldable, in both themes."""

    def test_small_text_reads_at_4_5_to_1_as_drawn_and_every_rule_that_dims_text_is_accounted_for(self):
        """No text the walk reads is under its ratio or over what it cannot composite; every rule that sets text in the
        muted or subtle colour or sets an opacity was used by text the walk held, or is in NOT_WALKED - which names only
        rules the page has and the walk does not reach, and whose colour, faded by its selector's opacity, reads at 4.5:1
        (an icon's 3:1) on every one of SURFACES in both themes."""
        self.walk()
        with self.subTest("contrast as drawn"):
            self.assertEqual(self.short, [])
        with self.subTest("every dimming rule walked or excused"):
            unwalked = self.rules - self.used
            self.assertEqual(
                sorted(unwalked - set(NOT_WALKED)), [], "walk these rules' text, or excuse them in NOT_WALKED"
            )
            self.assertEqual(sorted(set(NOT_WALKED) - unwalked), [], "excused, but missing from the page or walked")
        with self.subTest("excused rules on the plain surfaces"):
            page = self.open(2)
            named = [[key, need] for key, (need, _) in NOT_WALKED.items() if need]
            low = []
            for theme in THEMES:
                page.evaluate("t=>setTheme(t)", theme)
                settle(page)
                low += ["%s %s" % (theme, x) for x in page.evaluate(PAIRS, [named, list(SURFACES)])]
            self.assertEqual(low, [])


class WalkCatchesDimmedText(ContrastWalk):
    """The walk composites what #277 found it missing, and reads what a text-node walk misses."""

    # The two regressions #277 names: a commit row's hover painted in the text colour, and the excerpt's context line
    # numbers faded to 10% - added after the page's own rules, so they win.
    BROKEN = "@media (hover:hover){button.rc-row:hover{background:var(--foreground)}}.xp-row.ctx .ln{opacity:.1}"
    # Text a text-node walk would miss or misjudge, faint on white: over a gradient and under a mask (not composited),
    # generated by ::before, a field's value and placeholder, an SVG text's fill; and two rules whose colour reaches the
    # subtle and the muted token through custom properties - one aliased, one set on an ancestor over a :root default.
    CASES = """<style>
      #zz-cases{position:fixed;left:0;top:0;z-index:99999;width:320px;padding:8px;background:#fff;color:#000;font-size:12px}
      #zz-grad{background-image:linear-gradient(#fff,#f4f4f4)}
      #zz-mask{-webkit-mask-image:linear-gradient(#000,#000);mask-image:linear-gradient(#000,#000)}
      #zz-before::before{content:'generated text';color:#e0e0e0}
      #zz-value,#zz-ph{display:block;color:#e0e0e0;background:#fff;border:1px solid #000;font-size:12px}
      #zz-ph::placeholder{color:#e8e8e8}
      #zz-svg text{fill:#e4e4e4;font-size:12px}
      #zz-alias{--zz-helper:var(--subtle-foreground)} #zz-alias span{color:var(--zz-helper)}
      :root{--zz-local:#000} #zz-scope{--zz-local:var(--muted-foreground)} #zz-scope span{color:var(--zz-local)}
    </style><div id="zz-cases"><p id="zz-grad">gradient text</p><p id="zz-mask">masked text</p><p id="zz-before"></p>
      <input id="zz-value" value="value text"><input id="zz-ph" placeholder="placeholder text">
      <svg id="zz-svg" width="200" height="20"><text x="0" y="14">svg text</text></svg>
      <p id="zz-alias"><span>alias text</span></p><p id="zz-scope"><span>scoped text</span></p></div>"""

    def open(self, n_open, **kw):
        """Open the viewer with BROKEN appended to its styles."""
        kw["init"] = (
            "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');"
            "s.textContent=%s;document.head.append(s);});" % json.dumps(self.BROKEN)
        )
        return super().open(n_open, **kw)

    def test_a_painted_hover_and_a_faded_line_number_fail_the_walk(self):
        """With BROKEN applied, the desktop walk reports the hovered commit rows' text and the dimmed line numbers."""
        self.short, self.used, self.rules = [], set(), set()
        self.device = "desktop"
        self.scene_composer()
        self.scene_changes()
        self.assertTrue(any("excerpt neighbour" in s and "span.ln" in s for s in self.short), self.short)
        self.assertTrue(any("composer" in s and "xp-row.ctx > span.ln" in s for s in self.short), self.short)
        self.assertTrue(any("commit row" in s and "rc-code" in s for s in self.short), self.short)

    def test_text_beyond_text_nodes_and_colours_behind_custom_properties_are_read(self):
        """CASES on the page: the gradient's and the mask's text are reported as not composited; the generated text, the
        value, the placeholder and the SVG text as under 4.5:1; the aliased rule counts as dimming, and the rule whose
        custom property an ancestor sets counts as used where it draws."""
        self.short, self.used, self.rules = [], set(), set()
        self.device = "desktop"
        page = self.open(2)
        page.evaluate("h=>document.body.insertAdjacentHTML('beforeend',h)", self.CASES)
        self.look(page, "cases", "#zz-cases")
        light = [s for s in self.short if s.startswith("light ")]
        for what, mark in (
            ("gradient", "gradient text' over background-image"),
            ("mask", "masked text' over mask"),
            ("::before", "p#zz-before::before 'generated text'"),
            ("value", "input#zz-value 'value text'"),
            ("placeholder", "input#zz-ph::placeholder 'placeholder text'"),
            ("svg", "text 'svg text'"),
        ):
            with self.subTest(what):
                self.assertTrue(any(mark in s for s in light), light)
        self.assertIn("#zz-alias span", self.rules)
        self.assertIn("#zz-scope span", self.used)
