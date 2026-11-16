"""Platform's seams (docs/handbook/viewer.md §모듈 경계): platform knows no feature, so where a platform module reads
from or calls into one, it declares a seam - a typed registration function, a store and an accessor - and js/main.ts
registers every seam once, before boot() runs.

The tests hold the three promises a seam makes. The entry point wires every seam the platform declares (read from the
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

from helpers import VIEWER, extract_js_fn, js_const, js_i18n, js_seam, js_seam_wired, platform_seams, run_node
from helpers_notices import node_or_skip

MAIN = VIEWER / "js" / "main.ts"


class Wiring(unittest.TestCase):
    """js/main.ts registers every seam platform declares, once, before boot()."""

    def test_the_platform_declares_its_seams(self):
        """The seams are found by their shape in platform's source - the list the other tests use is not empty, and
        each seam's store, setter and accessor are distinct names."""
        seams = platform_seams()
        self.assertGreaterEqual(len(seams), 5)
        for seam in seams:
            self.assertEqual(len({seam.setter, seam.store, seam.accessor}), 3, seam)

    def test_main_registers_every_seam_once_before_boot(self):
        """Each seam's setter is called at the top level of js/main.ts exactly once, before its boot() call."""
        src = MAIN.read_text(encoding="utf-8")
        boot = re.search(r"^boot\(\);$", src, re.M)
        self.assertIsNotNone(boot, "main.ts calls boot() at its top level")
        for seam in platform_seams():
            with self.subTest(seam=seam.setter):
                calls = [m.start() for m in re.finditer(r"^%s\(\{" % seam.setter, src, re.M)]
                self.assertEqual(len(calls), 1, "%s is registered once at main.ts's top level" % seam.setter)
                self.assertLess(calls[0], boot.start(), "%s is registered before boot()" % seam.setter)

    def test_no_other_module_registers_a_seam(self):
        """No module but js/main.ts registers a seam (a call of its setter with the registered object)."""
        for seam in platform_seams():
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
        for seam in platform_seams():
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
                extract_js_fn("apiUnanswered"),
                extract_js_fn("api"),
                "api('/api/x',{}).then(()=>console.log(JSON.stringify('answered')),"
                "e=>console.log(JSON.stringify({why:e.message,fetched:FETCHED})));",
            ]
        )
        got = json.loads(run_node(script))
        self.assertIn("setRequestFallback()", got["why"])
        self.assertEqual(got["fetched"], 0)


# Recording stand-ins for the offline code, under the names js/main.ts registers (offline/flow.ts).
REQUEST_SCOPE = r"""
const LOG=[]; let KEY='k', SERVE=false, KEPT=null, FETCH=()=>Promise.resolve({status:200,json:()=>Promise.resolve({a:1})});
function offReadKey(url,options){LOG.push(['readKey',url,options.source]); return KEY;}
function offlineMayServe(){LOG.push(['mayServe']); return SERVE;}
function offStashed(url){LOG.push(['stashed',url]); return Promise.resolve(KEPT);}
function offStaleSaid(at){LOG.push(['staleSaid',at]);}
function offlineBack(){LOG.push(['back']);}
function offStash(url,data,status){LOG.push(['stash',url,data,status]);}
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
                extract_js_fn("apiUnanswered"),
                extract_js_fn("api"),
                setup,
                "api('/api/x',{}).then(r=>LOG.push(['answer',r.status,r.data]),e=>LOG.push(['threw',e.message]))"
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
                ["readKey", "/api/x", "GET /api/x"],
                ["fetch", "/api/x"],
                ["sourceOk", "GET /api/x"],
                ["back"],
                ["stash", "/api/x", {"a": 1}, 200],
                ["answer", 200, {"a": 1}],
            ],
        )

    def test_a_read_while_the_last_request_went_unanswered_is_served_from_the_store(self):
        """The key, whether the store may serve, the stored answer, saying how old it is - and no request."""
        got = self.run_api("API_OUT=true; SERVE=true; KEPT={data:['kept'],status:200,at:5};")
        self.assertEqual(
            got,
            [
                ["readKey", "/api/x", "GET /api/x"],
                ["mayServe"],
                ["stashed", "/api/x"],
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
                ["readKey", "/api/x", "GET /api/x"],
                ["fetch", "/api/x"],
                ["mayServe"],
                ["stashed", "/api/x"],
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
    "foldedGone", "gatheredGone", "regroup",
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
        const own={closest:s=>s.startsWith('[data-act^="notice-"]')?{}:s==='#doc .pv'?{dataset:{page:PAGE}}:null};
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
