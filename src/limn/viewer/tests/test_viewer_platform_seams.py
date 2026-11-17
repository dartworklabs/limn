"""Platform's seams (docs/handbook/viewer.md §모듈 경계): platform knows no feature, so where a platform module reads
from or calls into one, it declares a seam - a typed registration function, a store and an accessor - and js/main.ts
registers every seam once (a list of handlers once per handler), before boot() runs. A feature that calls the features
above it does the same (documents/state-seams.ts, whose calls test_viewer_documents_seams.py holds; layout/flow.ts,
whose calls FrameSeams below holds).

The tests hold the three promises a seam makes. The entry point wires every seam the viewer declares (read from the
source, so a new seam cannot stay unwired), once, before boot(). An unregistered seam throws, naming itself, instead of
doing nothing. And a platform function calls the registered functions at the point, with the arguments and in the
order it called the feature functions directly - checked under node against the served code wired by js/main.ts's own
registration, with recording stand-ins under the feature functions' names, so a member wired to the wrong function
fails here too.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_platform_seams.py
"""

import json
import re
import unittest

from helpers import (
    VIEWER,
    extract_js_fn,
    js_const,
    js_i18n,
    js_registrations,
    js_seam,
    js_seam_wired,
    platform_seams,
    run_node,
    viewer_seams,
)
from helpers_browser import BrowserBase, settle
from helpers_notices import node_or_skip

MAIN = VIEWER / "js" / "main.ts"


class Wiring(unittest.TestCase):
    """js/main.ts registers every seam the viewer declares, once (a list of handlers once per handler), before boot()."""

    def test_the_platform_declares_its_seams(self):
        """The seams are found by their shape in platform's source - the list the other tests use is not empty, and
        each seam's store, setter and accessor are distinct names."""
        self.assertGreaterEqual(len(platform_seams()), 5)
        seams = viewer_seams()
        self.assertGreaterEqual(len([s for s in seams if s.module.startswith("layout/")]), 2)
        for seam in seams:
            self.assertEqual(len({seam.setter, seam.store, seam.accessor}), 3, seam)

    def test_main_registers_every_seam_once_before_boot(self):
        """Each seam's setter is called at the top level of js/main.ts exactly once (a list's at least once), before its
        boot() call."""
        src = MAIN.read_text(encoding="utf-8")
        boot = re.search(r"^boot\(\);$", src, re.M)
        self.assertIsNotNone(boot, "main.ts calls boot() at its top level")
        for seam in viewer_seams():
            with self.subTest(seam=seam.setter):
                calls = [m.start() for m in re.finditer(r"^%s\(\{" % seam.setter, src, re.M)]
                if seam.listed:
                    self.assertGreaterEqual(len(calls), 1, "%s is registered at main.ts's top level" % seam.setter)
                else:
                    self.assertEqual(len(calls), 1, "%s is registered once at main.ts's top level" % seam.setter)
                self.assertLess(calls[-1], boot.start(), "%s is registered before boot()" % seam.setter)

    def test_no_other_module_registers_a_seam(self):
        """No module but js/main.ts registers a seam (a call of its setter with the registered object)."""
        for seam in viewer_seams():
            for path in sorted((VIEWER / "js").rglob("*.ts")):
                if path == MAIN:
                    continue
                with self.subTest(seam=seam.setter, module=path.name):
                    self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?<![\w.])%s\(\s*\{" % seam.setter)


class Unregistered(unittest.TestCase):
    """A seam called before its registration throws, naming the seam."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_each_accessor_throws_by_name(self):
        """Every accessor, before its setter ran, throws an Error whose message names the setter."""
        for seam in viewer_seams():
            with self.subTest(seam=seam.setter):
                script = js_seam(seam.setter) + (
                    "\ntry{%s(); console.log(JSON.stringify('returned'));}"
                    "catch(e){console.log(JSON.stringify(e instanceof Error ? e.message : 'not an Error'));}"
                    % seam.accessor
                )
                self.assertIn(seam.setter + "()", json.loads(run_node(script)))

    def test_a_request_before_its_registration_rejects(self):
        """api() before setRequestFallback() rejects with that error, before any request goes out."""
        script = "\n".join(
            [
                js_i18n("ko"),
                "let FETCHED=0; globalThis.fetch=()=>{FETCHED++; return Promise.reject(new Error('no'));};",
                "function sourceOk(){} function apiFailed(){}",
                js_const("API_WAIT"),
                js_const("API_OUT"),
                js_seam("setRequestFallback"),
                extract_js_fn("endpointUrl"),
                extract_js_fn("isExpected"),
                extract_js_fn("apiUnanswered"),
                extract_js_fn("api"),
                "api('GET /api/x',{}).then(()=>console.log(JSON.stringify('answered')),"
                "e=>console.log(JSON.stringify({why:e.message,fetched:FETCHED})));",
            ]
        )
        got = json.loads(run_node(script))
        self.assertIn("setRequestFallback()", got["why"])
        self.assertEqual(got["fetched"], 0)


# Recording stand-ins for the offline code, under the names js/main.ts registers (offline/flow.ts).
REQUEST_SCOPE = r"""
const LOG=[]; let KEY='k', SERVE=false, KEPT=null, FETCH=()=>Promise.resolve({status:200,json:()=>Promise.resolve({a:1})});
function offReadKey(endpoint,url){LOG.push(['readKey',endpoint,url]); return KEY;}
function offlineMayServe(){LOG.push(['mayServe']); return SERVE;}
function offStashed(endpoint,url){LOG.push(['stashed',endpoint,url]); return Promise.resolve(KEPT);}
function offStaleSaid(at){LOG.push(['staleSaid',at]);}
function offlineBack(){LOG.push(['back']);}
function offStash(endpoint,url,data,status){LOG.push(['stash',endpoint,url,data,status]);}
function sourceOk(source){LOG.push(['sourceOk',source]);} function apiFailed(){LOG.push(['apiFailed']);}
globalThis.fetch=(url)=>{LOG.push(['fetch',url]); return FETCH(url);};
"""


class RequestFallback(unittest.TestCase):
    """api() and apiUnanswered() call the copies kept while cut off (setRequestFallback) where they called the offline
    code directly: the read's key first, the store only for a read while the last request went unanswered, the
    connection back and the answer kept after the network answered."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def run_api(self, setup):
        script = "\n".join(
            [
                js_i18n("ko"),
                REQUEST_SCOPE,
                js_const("API_WAIT"),
                js_const("API_OUT"),
                js_seam_wired("setRequestFallback"),
                extract_js_fn("endpointUrl"),
                extract_js_fn("isExpected"),
                extract_js_fn("apiUnanswered"),
                extract_js_fn("api"),
                setup,
                "api('GET /api/x',{}).then(r=>LOG.push(['answer',r.status,r.data]),e=>LOG.push(['threw',e.message]))"
                ".then(()=>console.log(JSON.stringify(LOG)));",
            ]
        )
        return json.loads(run_node(script))

    def test_a_read_the_network_answers(self):
        """Connected: the key, the request, then the source cleared, the connection back and the answer kept, in that
        order and with the read's url, source, body and status."""
        self.assertEqual(
            self.run_api(""),
            [
                ["readKey", "GET /api/x", "/api/x"],
                ["fetch", "/api/x"],
                ["sourceOk", "GET /api/x"],
                ["back"],
                ["stash", "GET /api/x", "/api/x", {"a": 1}, 200],
                ["answer", 200, {"a": 1}],
            ],
        )

    def test_a_read_while_the_last_request_went_unanswered_is_served_from_the_store(self):
        """The key, whether the store may serve, the stored answer, saying how old it is - and no request."""
        got = self.run_api("API_OUT=true; SERVE=true; KEPT={data:['kept'],status:200,at:5};")
        self.assertEqual(
            got,
            [
                ["readKey", "GET /api/x", "/api/x"],
                ["mayServe"],
                ["stashed", "GET /api/x", "/api/x"],
                ["staleSaid", 5],
                ["sourceOk", "GET /api/x"],
                ["answer", 200, ["kept"]],
            ],
        )

    def test_a_read_the_network_does_not_answer_falls_back_on_the_store(self):
        """Unanswered (apiUnanswered): after the request, whether the store may serve, the stored answer, how old."""
        got = self.run_api(
            "SERVE=true; KEPT={data:['kept'],status:200,at:7}; FETCH=()=>Promise.reject(new Error('down'));"
        )
        self.assertEqual(
            got,
            [
                ["readKey", "GET /api/x", "/api/x"],
                ["fetch", "/api/x"],
                ["mayServe"],
                ["stashed", "GET /api/x", "/api/x"],
                ["staleSaid", 7],
                ["sourceOk", "GET /api/x"],
                ["answer", 200, ["kept"]],
            ],
        )


# What the notice store reads and draws into, as recording stand-ins under the names js/main.ts registers: the status
# line (view-status.ts: drawStatus puts the newest message on top, as the real one does), the panel's open state, the
# pin list's day lines and review pins, the focus's places, the composer's save label.
NOTICE_SCOPE = r"""
const LOG=[];
class HTMLElement {}
const stub=()=>({open:false,hidden:true,dataset:{},addEventListener(){},getClientRects:()=>[],matches:()=>false,
  closest:()=>null,querySelector:()=>null,querySelectorAll:()=>[],remove(){}});
const ELS={}; const $=s=>ELS[s]||(ELS[s]=stub());
const BODY=new Set();
const document={body:{classList:{add:c=>BODY.add(c),remove:c=>BODY.delete(c),contains:c=>BODY.has(c)}},
  activeElement:null,querySelectorAll:()=>[],addEventListener(){},contains:()=>false};
const window={addEventListener(){}};
function setTimeout(){return 0;} function clearTimeout(){}
let SIDE_OPEN=false, STATUS_TOP=0, STATUS_SIG='', REVIEW_ALL=[], READING_LINE_PAGE=4, REPLY=null;
const EDITOR={current:null}, SECTION_OPEN={}, TIP_TEXT={undo:'되돌리기'};
const NOTICES=new Map(),LINE=[],BANNERS=new Map(),DEFERRED=new Set(),GROUPS=new Map();
let NOTICE_SEQ=0,LINE_HOVER=false,LAST_POINTER_AT=null,DIGEST=null;
function announce(text){LOG.push(['announce']);} function drawOffer(){} function drawBanners(){} function tipFollow(){}
function drawStatus(){LOG.push(['draw']); STATUS_TOP=LINE.length?LINE[0].n:0;}
function setStatusSig(signature){LOG.push(['setSignature',signature]); STATUS_SIG=signature; return signature;}
function toggleStatusList(){LOG.push(['toggleList']);}
function placeRow(box,notice,row){LOG.push(['placeRow',notice.n]);}
function dropBareDayLines(){LOG.push(['dropBareDayLines']);}
function pageVerdictsOn(){LOG.push(['pageLinesOn']); return LINES_ON;}
function focusLine(page){LOG.push(['focusLine',page]); return false;}
function isReasonField(target){LOG.push(['isReasonField']); return false;}
function searchToPage(){LOG.push(['searchToPage']);}
function saveButtonLabel(){LOG.push(['saveButtonLabel']); return '다시 저장';}
function setHtml(element,markup){LOG.push(['setHtml',String(markup)]);}
let LINES_ON=true;
"""
NOTICE_FNS = [
    "splitMessage", "noticeDupe", "noticeDot", "makeNotice", "lineNote", "endNotice", "noticeText", "armNotice",
    "noticeHeld", "lineHeld", "holdLine", "releaseLine", "lineHoverOut", "lineVisible", "sourceEntry", "sameWords",
    "lineCap", "digestHold", "noticeDots", "holdsDot", "newsDupe", "foldedNews", "gatheredDupe", "gatheredLess",
    "dotHeld", "newsSlot", "isUndo", "noticeFocusBack", "syncSaveButton", "dropStaleReview", "reviewNewsStale",
    "foldedGone", "gatheredGone", "regroup", "focusedElement", "findClosest",
]  # fmt: skip
NOTICE_SEAMS = ("setNoticeStatusLine", "setNoticePanel", "setNoticeFocus", "setNoticeComposer")


class NoticeSeams(unittest.TestCase):
    """The notice store calls the status line, the panel, the focus and the composer through their seams at the
    points, with the arguments and in the order it called them directly."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def run_store(self, body):
        consts = "\n".join(dict.fromkeys(js_const(n) for n in ("NOTICE_MS", "NOTICE_HOLD_MAX", "LINE_MAX")))
        script = "\n".join(
            [js_i18n("ko"), NOTICE_SCOPE, consts]
            + [js_seam_wired(s) for s in NOTICE_SEAMS]
            + [extract_js_fn(n) for n in NOTICE_FNS]
            + [body, "console.log(JSON.stringify({log:LOG,body:[...BODY]}));"]
        )
        return json.loads(run_node(script))

    def test_a_status_line_message_draws_the_line_then_reads_its_top(self):
        """lineNote draws the line, then asks which message is on top: the one it just drew, so it is not read out again
        (read before the draw it would be someone else's and the message would be announced)."""
        got = self.run_store("lineNote('소식',NOTICE_KIND.INFO);")
        self.assertEqual(got["log"], [["draw"]])

    def test_a_message_said_again_forgets_the_lines_signature_then_redraws(self):
        """regroup clears the line's signature, then draws the line, then reads its top - the message it moved up is on
        top, so its new words are not read out a second time."""
        got = self.run_store(
            "const n=lineNote('하나',NOTICE_KIND.INFO); LOG.length=0;"
            "regroup(n,{msg:'둘',kind:NOTICE_KIND.INFO,act:null,o:{}});"
        )
        self.assertEqual(got["log"], [["setSignature", ""], ["draw"]])

    def test_the_panels_open_state_decides_a_messages_dot(self):
        """The [핀 N] dot is kept while the panel is closed and dropped while it is open (the panel's state read at the
        message)."""
        closed = self.run_store("lineNote('소식',NOTICE_KIND.INFO,null,{dot:NOTICE_DOT.SIDE});")
        opened = self.run_store("SIDE_OPEN=true; lineNote('소식',NOTICE_KIND.INFO,null,{dot:NOTICE_DOT.SIDE});")
        self.assertIn("dot-side", closed["body"])
        self.assertNotIn("dot-side", opened["body"])

    def test_a_row_that_ends_takes_its_bare_day_lines_and_a_line_message_redraws(self):
        """endNotice of a row asks the pin list to drop the day lines it left bare; of a line message, redraws the line."""
        got = self.run_store(
            "const row=makeNotice({msg:'r',kind:NOTICE_KIND.OK,place:NOTICE_PLACE.ROW}); LOG.length=0; endNotice(row,false);"
            "const line=lineNote('소식',NOTICE_KIND.INFO); LOG.push(['--']); endNotice(line,false);"
        )
        self.assertEqual(got["log"], [["dropBareDayLines"], ["draw"], ["--"], ["draw"]])

    def test_stale_review_messages_read_the_review_pins(self):
        """dropStaleReview reads the review section's pins through the panel."""
        got = self.run_store(
            "REVIEW_ALL=Object.assign([],{map(f){LOG.push(['reviewPins']); return [];}}); dropStaleReview();"
        )
        self.assertEqual(got["log"], [["reviewPins"]])

    def test_the_focus_goes_back_to_the_reading_line_in_the_old_order(self):
        """noticeFocusBack's return, once the message's own button lost the focus to nothing: is an edit card or a reply
        open, are page lines drawn, then the line of the message's page - or, with none, the reading line's page - and,
        failing that, the reading area."""
        body = r"""
        const line=()=>Object.assign(new HTMLElement(),{dataset:{page:PAGE}});
        const own=Object.assign(new HTMLElement(),{closest:s=>s.startsWith('[data-act^="notice-"]')?{}:s==='#doc .pv'?line():null});
        let PAGE='3'; document.activeElement=own; let back=noticeFocusBack({n:1});
        document.activeElement=document.body; back(); LOG.push(['--']);
        PAGE='0'; document.activeElement=own; back=noticeFocusBack({n:1});
        document.activeElement=document.body; back(); LOG.push(['--']);
        document.activeElement=own; back=noticeFocusBack({n:1}); EDITOR.current={}; document.activeElement=document.body; back();
        """
        got = self.run_store(body)
        self.assertEqual(
            got["log"],
            [
                ["pageLinesOn"],
                ["focusLine", 3],
                ["searchToPage"],
                ["--"],
                ["pageLinesOn"],
                ["focusLine", 4],
                ["searchToPage"],
                ["--"],
            ],
        )

    def test_the_save_button_reads_its_label_when_its_banner_turns(self):
        """syncSaveButton asks the composer for the label only when the save banner came or went, then draws it."""
        body = r"""
        ELS['#btn-save']={dataset:{}};
        BANNERS.set(NOTICE_HOST.COMPOSER,{save:true}); syncSaveButton(); LOG.push(['--']); syncSaveButton();
        """
        got = self.run_store(body)
        self.assertEqual(got["log"], [["saveButtonLabel"], ["setHtml", "다시 저장"], ["--"]])


if __name__ == "__main__":
    unittest.main()


# The frame's own steps and the features' functions it reaches, as recording stand-ins under the names js/main.ts
# registers and the frame calls; the page's elements are inert stand-ins (any property, any call), and so is what
# platform/dom.ts's checked lookups find in them.
FRAME_SCOPE = r"""
const LOG=[], rec=(name)=>(...a)=>{LOG.push(a.length?[name,...a]:[name]);};
const ANY=new Proxy(function(){},{get:(t,k)=>k===Symbol.toPrimitive?()=>'':k==='length'?0:ANY,apply:()=>ANY,set:()=>true});
const ELS={}; const $=s=>ELS[s]||ANY, $$=()=>[];
const findElement=()=>ANY, findMaybe=()=>ANY, findAll=()=>[]; class HTMLElement {}
const document={body:ANY,activeElement:null}; function setTimeout(fn){TIMERS.push(fn); return 1;} function clearTimeout(){}
const TIMERS=[];
let SIDE_OPEN=false, BAND=null, LAYOUT=null;
let META={}, CHANGED=true, PINS=[], REVIEW_ALL=[], SIDE_SLIDE=null, SHEET_KEPT=false, REPICK=null, REPLY=null;
const COMPOSE={current:{}}, EDITOR={current:null}, REVISION_VIEW={target:null,rows:[]}, SEARCH={open:false};
for (const name of ['topAnchor','applySideWidth','applyOutlineState','restoreAnchor','hideTip','stickTop',
  'keepFieldInView','drawPins','autoFitWidth','keepReadingSpot','renderComposer','updateSectionStrip','fitBarWords',
  'gripAria','syncBackLayer','updateReviewCount','syncBuildErrChip','placeStatus','drawPinGuideActions',
  'renderCommitList','stickSoon','drawZoom','renderSizeSegment','placeMore','showSheet','footInk','setHash',
  'endSideSlide','setSheetKept','refit']) globalThis[name]=rec(name);
function applyLayout(){LOG.push(['applyLayout']); return CHANGED;}
function draftOpen(){return false;} function translate(t){return t;} function translateTemplate(t){return t;}
"""


class FrameSeams(unittest.TestCase):
    """The frame calls the features through onRelayout and setFrameHost at the points, with the arguments and in the
    order it called them directly - wired by js/main.ts's own registrations, so a listener or a member wired to the
    wrong function, or registered in another order, fails here."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def run_frame(self, fns, body):
        script = "\n".join(
            [FRAME_SCOPE, js_seam_wired("onRelayout"), js_seam_wired("setFrameHost")]
            + [extract_js_fn(n) for n in fns]
            + [body, "console.log(JSON.stringify(LOG));"]
        )
        return json.loads(run_node(script))

    def test_a_relayout_takes_its_steps_and_the_features_in_the_old_order(self):
        """relayout(): the anchor, the layout, the pin list (the layout changed), the widths, the pages' fit, the anchor
        back, the Markdown reading spot, the tooltip, the composer (a selection held), the bar stuck, the section strip,
        the field in view, the bar's words - one after the other, as the direct calls ran."""
        self.assertEqual(
            [step[0] for step in self.run_frame(["relayout"], "relayout();")],
            [
                "topAnchor", "applyLayout", "drawPins", "applySideWidth", "applyOutlineState", "autoFitWidth",
                "restoreAnchor", "keepReadingSpot", "hideTip", "renderComposer", "stickTop", "updateSectionStrip",
                "keepFieldInView", "fitBarWords",
            ],
        )  # fmt: skip

    def test_the_relayout_listeners_are_registered_in_the_order_of_their_first_step(self):
        """js/main.ts registers each relayout listener in the order its first step comes in a relayout, so two
        listeners of one step are called in the order their direct calls ran: the pin list, the pages, the Markdown
        surface, the composer."""
        source = (VIEWER / "js" / "layout" / "flow.ts").read_text(encoding="utf-8")
        interface = re.search(r"interface RelayoutListener \{(.*?)\}", source, re.S).group(1)
        steps = re.findall(r"(\w+)\?\(\)", interface)
        firsts = [min(steps.index(m) for m in re.findall(r"(\w+):", call)) for call in js_registrations("onRelayout")]
        self.assertEqual(firsts, sorted(firsts))
        self.assertEqual(len(set(firsts)), len(firsts))

    def test_a_relayout_keeps_its_guards(self):
        """The pin list draws only when the layout changed and a document is open; the composer only while it holds a
        selection."""
        got = self.run_frame(
            ["relayout"],
            "CHANGED=false; COMPOSE.current=null; relayout(); LOG.push(['--']);CHANGED=true; META=null; relayout();",
        )
        names = [step[0] for step in got]
        self.assertNotIn("drawPins", names)
        self.assertNotIn("renderComposer", names)

    def test_the_panels_toggles_ask_for_the_counts_then_the_chip(self):
        """applySide(): the sheet let go (nothing is being written), the grip's names, the pin counts, the back layer, the
        build error chip, in that order."""
        got = [s[0] for s in self.run_frame(["applySide"], "ELS['#composer']={hidden:true}; applySide();")]
        self.assertEqual(got, ["setSheetKept", "gripAria", "updateReviewCount", "syncBackLayer", "syncBuildErrChip"])

    def test_a_new_layout_places_the_status_line_then_redraws_the_changes_view(self):
        """applyLayout(): the bar's tools, the panel, the bar stuck, the status line's place, the open more sheet's
        segment and place, then the changes view's pin guide and commit list - the status line and the changes view at
        the points their direct calls had."""
        body = (
            "let BAND_IN={w:1200,h:800,coarse:false}, MID_OVERLAY=false; const BAND_MODE={x:'wide'};"
            "function layoutFor(){return 'x';} function prefs(){return {};}"
            "REVISION_VIEW.target={}; REVISION_VIEW.rows=[1]; LOG.push(['result', applyLayout()]);"
        )
        names = ["placeBarTools", "applySide", "setBand", "setLayout", "setMidOverlay", "setOutlineMidOpen",
                 "setZoomed", "setSideOpen", "setBandIn"]  # fmt: skip
        got = self.run_frame(["applyLayout"], "".join(f"var {n}=rec('{n}');" for n in names) + body)
        tail = [s[0] for s in got][-9:]
        self.assertEqual(
            tail,
            [
                "placeBarTools", "applySide", "stickTop", "placeStatus", "renderSizeSegment", "placeMore",
                "drawPinGuideActions", "renderCommitList", "result",
            ],
        )  # fmt: skip

    def test_more_draws_the_zoom_after_the_tooltip_goes(self):
        """openMore(): the tooltip goes, the zoom is drawn, then the size segment and the sheet's place."""
        got = [s[0] for s in self.run_frame(["openMore"], "ELS['#more']={open:false}; openMore();")]
        self.assertEqual(got[:4], ["hideTip", "drawZoom", "renderSizeSegment", "placeMore"])

    def test_the_changes_view_draws_only_what_it_shows(self):
        """The frame's drawChangesView keeps the two guards of the calls it stands for: the pin guide when the changes
        view has a target, the commit list when it has rows."""
        got = self.run_frame(
            [],
            "frameHost().drawChangesView(); LOG.push(['--']); REVISION_VIEW.target={}; REVISION_VIEW.rows=[1];"
            "frameHost().drawChangesView();",
        )
        self.assertEqual([s[0] for s in got], ["--", "drawPinGuideActions", "renderCommitList"])

    def test_a_settling_band_sticks_the_verdict_line_when_its_wait_ends(self):
        """bandSettle(): a band still moving waits; when the wait ends the verdict line is stuck again first."""
        body = (
            "let BAND_IN={w:1,h:1,coarse:false}, BAND_TIMER=0; const BAND_SETTLE_MS=1;"
            "function bandInput(){return {w:2,h:2,coarse:false};} function settleBand(){return BAND_STEP.WAIT;}"
            "function typingNow(){return true;} bandSettle(); TIMERS[0]();"
        )
        got = self.run_frame(["bandSettle"], body)
        self.assertEqual([s[0] for s in got], ["stickSoon"])

    def test_the_hosts_members_are_the_features_functions(self):
        """Each member js/main.ts gives the frame calls the feature function of its name, with the argument given."""
        got = self.run_frame(
            [],
            "const h=frameHost(); h.placeStatus(); h.updateReviewCount(); h.syncBuildErrorChip(); h.stickSoon();"
            "h.drawZoom(); h.fitBarWords(); h.setHash('b'); SEARCH.open=true; LOG.push(['searchOpen', h.searchOpen()]);",
        )
        self.assertEqual(
            got,
            [
                ["placeStatus"], ["updateReviewCount"], ["syncBuildErrChip"], ["stickSoon"], ["drawZoom"],
                ["fitBarWords"], ["setHash", "b"], ["searchOpen", True],
            ],
        )  # fmt: skip


class FrameSeamsInTheBrowser(BrowserBase):
    """The frame's seam calls on the real page where no other browser test walks them."""

    CHIP = "()=>document.querySelector('#build-err-chip').hidden"

    def test_the_build_error_chip_follows_the_panel_as_it_folds_and_opens(self):
        """A failed build on the desktop: while the panel shows the error the chip is hidden; folding the panel
        (Ctrl+\\) shows the chip, opening it again ([핀 N]) hides it - applySide asks the build error chip through the frame's
        host each time."""
        page = self.open(0)
        page.evaluate("showBuildErr({state: 'fail', log_tail: 'x'})")
        self.assertTrue(page.evaluate(self.CHIP))
        page.keyboard.press("Control+Backslash")
        settle(page)
        self.assertEqual(page.evaluate("[SIDE_OPEN, document.querySelector('#build-err-chip').hidden]"), [False, False])
        page.click("#nav-side")
        settle(page)
        self.assertEqual(page.evaluate("[SIDE_OPEN, document.querySelector('#build-err-chip').hidden]"), [True, True])


# Each request api() sends by an endpoint key against the URL and method the call sent before it took one: the old
# address is built by the old expression (withDocQuery over the whole path, a pin's number concatenated in), the same
# withDocQuery serving both. One row per endpoint of ApiAnswers, and one per query shape a call site builds.
ENDPOINT_CASES = r"""
const ID=7, DOCKEY='nt', COMMIT='a'.repeat(40);
const CASES=[
  ['GET /api/meta',{query:withDocQuery('')},withDocQuery('/api/meta'),'GET'],
  ['GET /api/meta',{query:withDocQuery('',DOCKEY)},withDocQuery('/api/meta',DOCKEY),'GET'],
  ['GET /api/meta',{query:withDocQuery('?light=1')+'&ev=4'},withDocQuery('/api/meta?light=1')+'&ev=4','GET'],
  ['GET /api/docs',{},'/api/docs','GET'],
  ['GET /api/people',{},'/api/people','GET'],
  ['GET /api/build',{query:withDocQuery('?log=1')},withDocQuery('/api/build?log=1'),'GET'],
  ['POST /api/rebuild',{query:withDocQuery('?async=1'+'&force=1')},withDocQuery('/api/rebuild?async=1'+'&force=1'),'POST'],
  ['POST /api/hold',{query:withDocQuery('',DOCKEY),body:{build:'pages-1',days:7}},withDocQuery('/api/hold',DOCKEY),'POST'],
  ['GET /api/outline-labels',{query:withDocQuery('',DOCKEY)},withDocQuery('/api/outline-labels',DOCKEY),'GET'],
  ['GET /api/source',{query:withDocQuery('')},withDocQuery('/api/source'),'GET'],
  ['GET /api/version',{},'/api/version','GET'],
  ['GET /api/snippet',{query:withDocQuery('?file='+encodeURIComponent('a b.tex')+'&lo='+3+'&hi='+4+'&levels=1',DOCKEY)},
    withDocQuery('/api/snippet?file='+encodeURIComponent('a b.tex')+'&lo='+3+'&hi='+4+'&levels=1',DOCKEY),'GET'],
  ['POST /api/pick',{body:{page:1,x0:0}},'/api/pick','POST'],
  ['GET /api/pins',{query:'?all=1'},'/api/pins?all=1','GET'],
  ['GET /api/pins/dropped',{},'/api/pins/dropped','GET'],
  ['GET /api/pins/{id}',{id:ID},'/api/pins/'+ID,'GET'],
  ['POST /api/pin',{body:{note:'n',lo:1}},'/api/pin','POST'],
  ['POST /api/pins/{id}/edit',{id:ID,body:{note:'',base_rev:2}},'/api/pins/'+ID+'/edit','POST'],
  ['POST /api/pins/{id}/close',{id:ID},'/api/pins/'+ID+'/close','POST'],
  ['POST /api/pins/{id}/reopen',{id:ID},'/api/pins/'+ID+'/reopen','POST'],
  ['POST /api/pins/{id}/confirm',{id:ID,body:{done_at:'t'}},'/api/pins/'+ID+'/confirm','POST'],
  ['POST /api/pins/{id}/reply',{id:ID,body:{text:'r'}},'/api/pins/'+ID+'/reply','POST'],
  ['POST /api/pins/{id}/unclaim',{id:null},'/api/pins/'+null+'/unclaim','POST'],
  ['POST /api/pins/{id}/drop',{id:ID},'/api/pins/'+ID+'/drop','POST'],
  ['POST /api/pins/{id}/restore',{id:ID},'/api/pins/'+ID+'/restore','POST'],
  ['POST /api/pins/{id}/purge',{id:ID},'/api/pins/'+ID+'/purge','POST'],
  ['GET /api/revisions',{query:withDocQuery('?before='+encodeURIComponent(COMMIT)+'&limit='+50,DOCKEY)},
    withDocQuery('/api/revisions?before='+encodeURIComponent(COMMIT)+'&limit='+50,DOCKEY),'GET'],
  ['GET /api/revision-diff',{query:withDocQuery('?commit='+encodeURIComponent(COMMIT)+'&pin='+ID,DOCKEY)},
    withDocQuery('/api/revision-diff?commit='+encodeURIComponent(COMMIT)+'&pin='+ID,DOCKEY),'GET'],
  ['GET /api/revision-source',{query:withDocQuery('?commit='+COMMIT+'&base='+COMMIT,DOCKEY)},
    withDocQuery('/api/revision-source?commit='+COMMIT+'&base='+COMMIT,DOCKEY),'GET'],
  ['GET /api/revision-build',{query:withDocQuery('?commit='+COMMIT+'&pin='+ID,DOCKEY)},
    withDocQuery('/api/revision-build?commit='+COMMIT+'&pin='+ID,DOCKEY),'GET'],
  ['POST /api/revision-build',{body:{commit:COMMIT,pin:ID}},'/api/revision-build','POST'],
];
const SENT=[];
globalThis.fetch=(url,init)=>{SENT.push([url,init.method,init.body===undefined?null:init.body,init.headers]);
  return Promise.resolve({status:200,json:()=>Promise.resolve({})});};
(async()=>{const out=[];
  for(const [endpoint,options,url,method] of CASES){SENT.length=0; await api(endpoint,options);
    const body=options.body===undefined?null:JSON.stringify(options.body);
    out.push({endpoint,sent:SENT[0],was:[url,method,body,body===null?{}:{'Content-Type':'application/json'}]});}
  console.log(JSON.stringify(out));})();
"""


class EndpointRequests(unittest.TestCase):
    """api() sends the request it sent before it took an endpoint key: for each endpoint the viewer calls (ApiAnswers)
    the URL its path, pin number and query make, the endpoint's method, and the body as JSON, byte for byte the same as
    the address the call built itself (withDocQuery over the whole path) with the method it named."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def requests(self, doc):
        """The [endpoint, sent, was] of every ENDPOINT_CASES row, with DOC (the document on screen) set to doc."""
        script = "\n".join(
            [
                js_i18n("ko"),
                REQUEST_SCOPE.replace("let KEY='k'", "let KEY=null"),
                js_const("API_WAIT"),
                js_const("API_OUT"),
                js_seam_wired("setRequestFallback"),
                extract_js_fn("endpointUrl"),
                extract_js_fn("isExpected"),
                extract_js_fn("apiUnanswered"),
                extract_js_fn("api"),
                "let DOC=%s;" % json.dumps(doc),
                extract_js_fn("withDocQuery"),
                ENDPOINT_CASES,
            ]
        )
        return json.loads(run_node(script))

    def test_every_endpoint_sends_what_its_call_sent_before(self):
        """With a document on screen and without one (withDocQuery then adds nothing): URL, method, body and headers."""
        for doc in ("ms", ""):
            with self.subTest(doc=doc):
                got = self.requests(doc)
                self.assertEqual([row["sent"] for row in got], [row["was"] for row in got])
                self.assertIn("/api/meta?doc=ms" if doc else "/api/meta", [row["sent"][0] for row in got])

    def test_every_endpoint_of_api_answers_has_a_row(self):
        """A new endpoint gets its row: every ApiAnswers key is sent by some case."""
        text = (VIEWER / "types" / "api.d.ts").read_text(encoding="utf-8")
        block = re.search(r"^interface ApiAnswers \{\n(.*?)^\}", text, re.M | re.S)
        assert block
        keys = set(re.findall(r"^  '([A-Z]+ /[^']+)':", block.group(1), re.M))
        self.assertEqual(sorted(keys - {row["endpoint"] for row in self.requests("ms")}), [])
