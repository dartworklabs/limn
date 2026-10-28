"""Small text reads at 4.5:1 as it is drawn (docs/handbook/viewer.md §토큰 '흐린 글자는 작은 글자다', issue #277).

FrontendColourRoles checks token pairs - a token on the surfaces named in a list. A rule can still put the muted text
on a surface nobody listed, or dim it with an opacity, and pass: the excerpt's context line numbers drew the muted
text at 70% (3.4:1 in light, 4.0:1 under a dark hover) and the light subtle text sat on a hover's --accent at 3.8:1.
This walks the page as Chromium draws it instead: in each state - cards, done rows, the Trash, notices, the composer's
excerpt, the changes view's commit list and diff, with a real mouse on rows and keyboard focus - it reads every text
run's computed colour and the backgrounds and opacities of the elements under it, composites them as the browser
paints them, and holds small text to 4.5:1 and large text to 3:1, in the light and the dark theme, on a desktop with
a mouse and a phone. A text inside a disabled control is not held (WCAG 1.4.3 exempts inactive controls).

Every style rule that sets text in the muted or subtle colour, or sets an opacity, is either reached by the walk -
it set the colour of, or dimmed, text the walk held - or listed in NOT_WALKED with the reason its text needs no walk.
A new such rule fails the walk's test until it is one or the other.

Run: LIMN_TEST_REQUIRE_BROWSER=1 uv run pytest -q src/limn/viewer/tests/test_viewer_contrast.py
"""

import os
import shutil
import subprocess
import time
from unittest import mock

from limn.pins.lifecycle.rules import CloseRequest
from limn.revisions import core as revisions, execution as revision_execution
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, minimal_pdf, ps
from helpers_access import ALICE, BOB, REPO_NEW, REPO_OLD, actor
from helpers_authority import post_authority
from helpers_browser import VIEWPORTS, BrowserBase, settle

DEVICES = {"desktop": VIEWPORTS["desktop 1440x900"], "phone": VIEWPORTS["phone 390x844"]}
THEMES = ("light", "dark")

# RULES: the page's style rules that set a colour or an opacity, as {key, sel, conds, color, opacity, dims}: a rule is keyed by
# its selector after the @media and @supports conditions it sits in, and it dims text (dims) when its colour uses the muted
# or subtle token or it sets an opacity. Shared by READ and PAIRS, with the colour helpers they use.
PRELUDE = r"""
  const TOKEN = /--(muted|subtle)-foreground\b/, rules = [];
  const visit = (list, conds) => { for (const r of list) {
    if (r instanceof CSSMediaRule) visit(r.cssRules, conds.concat('@media ' + r.conditionText));
    else if (r instanceof CSSSupportsRule) visit(r.cssRules, conds.concat('@supports ' + r.conditionText));
    else if (r instanceof CSSStyleRule) { const color = r.style.getPropertyValue('color').trim(), opacity = r.style.getPropertyValue('opacity').trim();
      if (color || opacity) rules.push({key: conds.concat(r.selectorText).join(' '), sel: r.selectorText, conds, color, opacity,
        dims: TOKEN.test(color) || opacity !== ''}); } } };
  for (const s of document.styleSheets) visit(s.cssRules, []);
  const rgba = s => { let m = /^rgba?\(([^)]+)\)/.exec(s || '');
    if (m) { const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = /^color\(srgb ([^)]+)\)/.exec(s || '');
    if (m) { const p = m[1].split(/[\s\/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1]; }
    return null; };
  const probe = document.createElement('i'); probe.style.display = 'none'; document.body.append(probe);
  const resolve = v => { probe.style.color = ''; probe.style.color = v; return probe.style.color ? getComputedStyle(probe).color : null; };
  const pm = c => [c[0] * c[3], c[1] * c[3], c[2] * c[3], c[3]], over = (a, b) => [0, 1, 2, 3].map(k => a[k] + b[k] * (1 - a[3]));
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
"""

# READ(root): the text under root (default the body) as drawn. For every text run with a box, outside .sr-only and a
# disabled control, not hidden and not fully transparent: its colour and the colour beside it as painted - each ancestor's
# background stacked from the page up, every element's opacity fading its own paint and all inside it as a group, as the
# browser composites them - their WCAG ratio, and the ratio it needs (4.5, or 3 for large text: 24px, or 18.66px at
# weight 700). With them, the keys of the dimming rules (PRELUDE) on the page and of those this text used: among the
# rules setting the colour of the nearest element that has one, those whose colour is the one drawn; and every rule
# setting the opacity of an element under the text whose opacity is under 1.
READ = (
    "root => {"
    + PRELUDE
    + r"""
  root = root || document.body;
  const css = new Map(), style = e => { let c = css.get(e); if (!c) { c = getComputedStyle(e); css.set(e, c); } return c; };
  const live = r => r.conds.every(c => c.startsWith('@media ') ? matchMedia(c.slice(7)).matches : CSS.supports(c.slice(10)));
  const hits = (e, sel) => { try { return e.matches(sel); } catch (x) { return false; } };
  const drawn = new Map(), colourOf = r => { if (!drawn.has(r)) drawn.set(r, resolve(r.color)); return drawn.get(r); };
  // One pixel under the text (text: its colour) or beside it (text: null): each element paints its background, then what is
  // inside it, and its opacity fades the lot; the page's canvas is white.
  const paint = (chain, text) => { let g = null;
    chain.forEach((e, i) => { const own = pm(rgba(style(e).backgroundColor) || [0, 0, 0, 0]), o = Number(style(e).opacity);
      g = (i === 0 ? (text ? over(pm(text), own) : own) : over(g, own)).map(v => v * o); });
    return over(g, [255, 255, 255, 1]); };
  const hex = c => '#' + c.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const name = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + [...e.classList].slice(0, 3).map(c => '.' + c).join('');
  const where = e => { const out = [name(e)]; for (let p = e.parentElement; p && out.length < 4 && !/#/.test(out[0]); p = p.parentElement)
    if (p.id || p.classList.length) out.unshift(name(p)); return out.join(' > '); };
  const texts = [], used = new Set(), walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let t; (t = walker.nextNode());) {
    const words = t.textContent.replace(/\s+/g, ' ').trim(), el = t.parentElement;
    if (!words || !el || el.closest('script,style,template,.sr-only,:disabled,[aria-disabled=true]')) continue;
    const range = document.createRange(); range.selectNodeContents(t);
    if (![...range.getClientRects()].some(b => b.width >= 1 && b.height >= 1)) continue;
    const cs = style(el), colour = rgba(cs.color); if (cs.visibility !== 'visible' || !colour) continue;
    const chain = []; for (let e = el; e; e = e.parentElement) chain.push(e);
    if (colour[3] * chain.reduce((o, e) => o * Number(style(e).opacity), 1) === 0) continue;
    const fg = paint(chain, colour), bg = paint(chain, null);
    const size = parseFloat(cs.fontSize), large = size >= 24 || (size >= 18.66 && Number(cs.fontWeight) >= 700);
    texts.push({text: words.slice(0, 40), where: where(el), ratio: ratio(fg, bg), need: large ? 3 : 4.5, fg: hex(fg), bg: hex(bg)});
    for (const e of chain) { const own = rules.filter(r => r.color && r.color !== 'inherit' && live(r) && hits(e, r.sel));
      if (!own.length) continue; own.filter(r => r.dims && colourOf(r) === style(e).color).forEach(r => used.add(r.key)); break; }
    for (const e of chain) if (Number(style(e).opacity) < 1)
      rules.filter(r => r.opacity && live(r) && hits(e, r.sel)).forEach(r => used.add(r.key));
  }
  probe.remove();
  return {texts, used: [...used], rules: [...new Set(rules.filter(r => r.dims).map(r => r.key))]};
}"""
)

# PAIRS([[key, need]], surfaces): for each dimming rule named, its colour drawn on each surface token - the lowest ratio
# under need, as "key: ratio on --surface"; a rule the page lacks or one without a colour is reported as such.
PAIRS = (
    "([named, surfaces]) => {"
    + PRELUDE
    + r"""
  const out = [];
  for (const [key, need] of named) { const r = rules.find(x => x.key === key);
    if (!r || !r.color) { out.push(key + ': no colour rule'); continue; }
    const fg = rgba(resolve(r.color));
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
# themes; or nothing (INACTIVE: a disabled or waiting control, which WCAG 1.4.3 exempts, or a drag's passing fade).
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
    "body.lay-wide.side-snap-collapse #bar1, body.side-snap-collapse :is(#bar2, #build-err, #banner, #composer, #list, "
    "#c-actions)": (INACTIVE, "the panel fading while a drag is about to collapse it"),
    # text on a plain surface, in a state the walk's one-document manuscript without a PDF does not draw
    "input::placeholder, textarea::placeholder": (TEXT, "a field's placeholder, no text node"),
    "#c-path": (TEXT, "a figure element's path in the composer: needs a figure document"),
    "#doc-links .doc-link-count": (TEXT, "a document's page count in the nav bar: needs a second document"),
    "#doc-links button": (TEXT, "a document link: needs a second document"),
    '#doc-links button[aria-current="page"] .doc-link-count': (
        TEXT,
        "the current document's count: needs a second document",
    ),
    "#doc-pop-none": (TEXT, "the documents list's no-match line: needs a filtered documents list"),
    "#doc-select-wrap label": (TEXT, "the documents select's label: needs several documents"),
    ".dcnt.z": (TEXT, "a zero count in the documents list: needs several documents"),
    ".dm-item .ph": (TEXT, "a document's path in the documents menu: needs several documents"),
    ".dp-row :is(.dp-p, .dp-k)": (TEXT, "the documents popover's counts: needs several documents"),
    "h3": (TEXT, "the navigation sheet's headings: needs several documents"),
    "#nav-sheet .ns-h": (TEXT, "the navigation sheet's headings: needs several documents"),
    "#m-rebuild .m-tail": (TEXT, "[더보기]'s '빌드 중', while a build runs"),
    "#more .m-l small": (TEXT, "[더보기]'s '지금 밝게' under the system theme: the walk sets the theme"),
    "#nav-page": (TEXT, "the page indicator of the mid and tablet-sheet bands: the walk is a desktop and a phone"),
    "#section-strip": (TEXT, "the section strip's default: each of its parts sets its own colour"),
    "#outline-items button": (TEXT, "an outline entry: needs a PDF outline"),
    "#outline-items button .ol-page": (TEXT, "an outline entry's page: needs a PDF outline"),
    "#outline-items button:is(.ol-active, :focus-visible) .ol-page": (
        TEXT,
        "the current outline entry's page: needs a PDF outline",
    ),
    "@media (hover: hover) #outline-items button:hover .ol-page": (
        TEXT,
        "a hovered outline entry's page: needs a PDF outline",
    ),
    "#ns-outline-items button .ol-no": (TEXT, "the navigation sheet's outline numbers: needs a PDF outline"),
    "#ns-outline-items button .ol-page": (TEXT, "the navigation sheet's outline pages: needs a PDF outline"),
    "#ns-outline-items.outline-empty": (TEXT, "the navigation sheet's empty outline note: needs a PDF"),
    ".pl-row .pl-s": (TEXT, "the page list's section names: needs a PDF outline"),
    "#ns-search": (TEXT, "the navigation sheet's search button: offered with a PDF to search"),
    "#search-hint, #search-count": (TEXT, "search's shortcut hint and count: offered with a PDF to search"),
    "#revision-more": (TEXT, "the commit list's [더 보기]: needs more commits than one page of the list"),
    '#sel-pop [data-act="pop-more"]': (TEXT, "the selection popover's [자세히]: opens after a mouse drag, not a pick"),
    "#sel-pop kbd": (TEXT, "the selection popover's [Esc]: opens after a mouse drag, not a pick"),
    ".assign-row .as-lab": (TEXT, "the edit card's '담당' label: the walk opens no edit card"),
    ".q-hint": (
        TEXT,
        "the edit card's question hint and the viewer role's note: the walk is an editor with no edit card",
    ),
    ".hint": (TEXT, "the empty list's hint: the walk's list has pins"),
    ".m-preview .m-sep": (
        TEXT,
        "the reply preview's separator before an assignee change: the walk changes no assignee",
    ),
    ":is(.as-seg, .m-preview, .card-meta) .ml": (
        TEXT,
        "the login beside a name two people share: the walk's names differ",
    ),
    ".msg.ev": (TEXT, "a state record's note in a thread: the walk's records carry none"),
    ".rv-close": (TEXT, "a review card's closing line"),
    ".ov-no": (TEXT, "the figure overlay's page number: needs a figure document"),
    ".ov-none": (TEXT, "the figure overlay's missing page: needs a figure document"),
    ".pv": (TEXT, "a page verdict line: needs a verdict document"),
    ".pv .pv-s.pv-none": (TEXT, "a page verdict line with no verdict: needs a verdict document"),
    ".vd-l": (TEXT, "the composer's verdict row: needs a verdict document"),
    ".vd-why": (TEXT, "the composer's verdict note: needs a verdict document"),
    'button.tg[aria-pressed="false"]': (
        TEXT,
        "an off toggle ([커밋 전체 비교], the suggestion's toggle): the walk shows none",
    ),
    ".sg-diff .rd-fold .rd-code": (TEXT, "a suggested edit's folded lines: the walk suggests no edit"),
    ".sg-foot button": (TEXT, "a suggested edit's footer buttons: the walk suggests no edit"),
    ".sg-text[readonly]": (TEXT, "a suggested edit's read-only text: the walk suggests no edit"),
    ".sg-why": (TEXT, "a suggested edit's note: the walk suggests no edit"),
}


def fake_compile(spec, jobdir, timeout):
    """A comparison build that writes a one-page PDF instead of running latexdiff and latexmk."""
    (jobdir / "revision.pdf").write_bytes(minimal_pdf("diff"))
    return revisions.ComparisonBuilt([])


class ContrastWalk(BrowserBase):
    """A Git manuscript of three commits by two authors and the pins that draw every list row: an open request assigned to
    Bob with a thread, an open question, a pin an agent closed (awaiting review) whose range is a changed line and the
    unchanged line above it, a done pin and a dropped one. Holds the walk's scenes; the comparison build is faked."""

    WHO = ALICE
    maxDiff = None  # every short text in the report, not the first

    def setUp(self):
        """Commit the manuscript three times, seed the pins, and fake the comparison build."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
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
        patcher = mock.patch.object(revision_execution, "revision_compile", side_effect=fake_compile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args):
        """Run Git in the manuscript's repository; its stdout, stripped."""
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, text, author, message):
        """Write text to the manuscript and commit it as author; the commit's hash."""
        self.main.write_text(text, encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))
        self.git("add", "-A")
        self.git("-c", "user.name=" + author, "-c", "user.email=a@example.com", "commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    # ------------------------------------------------------------ reading
    def look(self, page, state, root=None):
        """READ root (a selector, or the whole page) in the light and the dark theme, after the switch has settled;
        each text under its ratio goes to self.short and each rule a held text used to self.used."""
        for theme in THEMES:
            page.evaluate("t=>setTheme(t)", theme)
            settle(page)
            handle = page.query_selector(root) if root else None
            if root and handle is None:
                self.short.append("%s %s: nothing at %s" % (theme, state, root))
                continue
            out = page.evaluate(READ, handle)
            self.rules.update(out["rules"])
            self.used.update(out["used"])
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

    # ------------------------------------------------------------ scenes
    def scene_list(self):
        """The pin list with every section open and two cards unfolded (a folded thread, a long post, a deleted pin's
        reference); a reply being written with its mention list and its preview naming a stranger; a hovered card, done
        row and section tool; a banner of each kind on the list and a message on the status line; [더보기], the phone's
        navigation sheet; the Trash and a hovered trash row."""
        page = self.open(2, **DEVICES[self.device])
        page.evaluate(
            "ids=>{setSide(true); SEC.done=true; SEC.review=true; ids.forEach(i=>OPEN_CARDS.add(i)); drawPins();}",
            [self.thread, self.review],
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
        if self.device != "desktop":
            page.click("#btn-pos")
            page.wait_for_selector("#nav-sheet[open]")
            settle(page)
            self.look(page, "navigation sheet", "#nav-sheet")
            page.keyboard.press("Escape")
        page.evaluate("openTrash()")
        page.wait_for_selector("#trash[open] .arc-row")
        self.look(page, "trash", "#trash")
        self.hover(page, "#trash .arc-row", "trash row")

    def scene_composer(self):
        """A picked line's composer: the excerpt's band and its dimmed neighbours, a hovered and a focused neighbour, and the
        hovered [핀 저장] with its shortcut."""
        page = self.open(2, **DEVICES[self.device])
        ptr = "mouse" if self.device == "desktop" else "touch"
        page.evaluate("p=>{LAST_PTR=p; pick({page:1,x0:10,y0:10,x1:200,y1:60});}", ptr)
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo&&document.querySelector('#c-xp .xp-row.ctx')")
        settle(page)
        self.look(page, "composer")
        self.hover(page, "#c-xp .xp-row.ctx", "excerpt neighbour")
        self.hover(page, "#btn-save", "save button")
        self.focus(page, "#c-xp .xp-row.ctx", "excerpt neighbour")
        for _ in range(5):  # widen the band downwards past five lines: it folds, and [원문 펼치기] offers the rest
            hi = page.evaluate("COMPOSE.current.hi")
            page.click('#c-xp .xp-row.ctx[data-line="%d"]' % (hi + 1))
            page.wait_for_function("n=>COMPOSE.current.hi===n", arg=hi + 1)
            settle(page)
        page.wait_for_selector("#c-xp .xp-fold")
        self.look(page, "folded excerpt", "#composer")

    def scene_changes(self):
        """The changes view: its commit list with the painted range, each commit row hovered; the source diff's added and
        removed rows; and the review pin's diff, its range highlighted on an unchanged line."""
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
        return page

    def walk(self):
        """Run every scene on each device, collecting self.short, self.used and self.rules; the last scene's page."""
        self.short, self.used, self.rules = [], set(), set()
        for self.device in DEVICES:
            self.scene_list()
            self.scene_composer()
            page = self.scene_changes()
        return page


class RenderedSecondaryContrast(ContrastWalk):
    """The walk on a desktop and a phone, in both themes."""

    def test_small_text_reads_at_4_5_to_1_as_drawn_and_every_rule_that_dims_text_is_accounted_for(self):
        """No text the walk reads is under its ratio; every rule that sets text in the muted or subtle colour or sets an
        opacity was used by text the walk held, or is in NOT_WALKED - which names only rules the page has and the walk
        does not reach, and whose colour reads at 4.5:1 (an icon's 3:1) on every one of SURFACES in both themes."""
        page = self.walk()
        with self.subTest("contrast as drawn"):
            self.assertEqual(self.short, [])
        with self.subTest("every dimming rule walked or excused"):
            unwalked = self.rules - self.used
            self.assertEqual(
                sorted(unwalked - set(NOT_WALKED)), [], "walk these rules' text, or excuse them in NOT_WALKED"
            )
            self.assertEqual(sorted(set(NOT_WALKED) - unwalked), [], "excused, but missing from the page or walked")
        with self.subTest("excused rules on the plain surfaces"):
            named = [[key, need] for key, (need, _) in NOT_WALKED.items() if need]
            low = []
            for theme in THEMES:
                page.evaluate("t=>setTheme(t)", theme)
                settle(page)
                low += ["%s %s" % (theme, x) for x in page.evaluate(PAIRS, [named, list(SURFACES)])]
            self.assertEqual(low, [])


class WalkCatchesDimmedText(ContrastWalk):
    """The walk composites what #277 found it missing: a hover's background and an opacity on the text."""

    # The two regressions #277 names: a commit row's hover painted in the text colour, and the excerpt's context line
    # numbers faded to 10% - added after the page's own rules, so they win.
    BROKEN = "@media (hover:hover){button.rc-row:hover{background:var(--foreground)}}.xp-row.ctx .ln{opacity:.1}"

    def open(self, n_open, **kw):
        """Open the viewer with BROKEN appended to its styles."""
        css = self.BROKEN.replace("'", "\\'")
        kw["init"] = (
            "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.textContent='%s';document.head.append(s);});"
            % css
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
