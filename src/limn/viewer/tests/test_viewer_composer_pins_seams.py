"""What the composer and the pin list ask the features above them (composer/state-seams.ts, pins/state-seams.ts,
docs/handbook/viewer.md §모듈 경계): the composer draws the verdict row and saves a verdict through the verdict's part,
reads the pin list again and takes a saved pin back through the pin list, keeps a pin cut off through the queue, and
draws the edit card and the reply through their own fields; the pin list draws what a verdict adds - its badge, its
figure, its old mark, its page lines - through the verdicts.

test_viewer_platform_seams.py holds that js/main.ts registers every seam once before boot() and that an unregistered one
throws by name. These tests run the composer's and the pin list's own functions under node, wired by js/main.ts's own
registration (js_seams_wired) with recording stand-ins under the names it registers, and hold that each call reaches the
feature at the point it stood, with the same arguments, its answer used the same way, and in the same order among its
neighbours - so a member wired to the wrong function, or a call moved, fails here.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_composer_pins_seams.py
"""

import json
import unittest

from helpers import JS_OFFLINE_STUBS, extract_js_fn, js_i18n, js_icons, js_markup, js_seams_wired, run_node
from helpers_notices import node_or_skip

COMPOSER_SEAMS = "composer/state-seams.ts"
PIN_SEAMS = "pins/state-seams.ts"

# Recording stand-ins under the names js/main.ts registers for the composer's seams: the verdict's part
# (verdict/flow-line.ts), the pin list (pins/flow-list.ts, pins/flow-actions.ts), the queue (offline/flow.ts) and the
# edit card and reply (pins/flow-edit.ts, pins/flow-reply.ts). JS_OFFLINE_STUBS comes first; these replace its queue.
COMPOSER_FEATURES = r"""
const LOG=[];
function renderVerdictRow(){LOG.push(['drawRow']);}
let FIGURE_BODY=null, FIGURE_ROOT=null;
function figureVerdictBody(selection){LOG.push(['figureBody',selection.page]); return FIGURE_BODY;}
function figureVerdictRoot(selection){LOG.push(['figureRoot',selection.page]); return FIGURE_ROOT;}
function figureShort(page,root){LOG.push(['figureShort',page,root]); return 'short-'+root;}
function verdictUndo(id){LOG.push(['undo',id]); return async()=>true;}
function verdictDropped(){LOG.push(['dropped']);}
function loadPins(){LOG.push(['load']); return Promise.resolve(true);}
function dropPin(id,undoSave,again){LOG.push(['drop',id,undoSave,typeof again]); return Promise.resolve(true);}
let KEYED=false;
OFF.idem=false;
function offlineQueueSave(selection,note,out,mentions,tried){LOG.push(['queueSave',selection.page,note,out.kind,mentions,tried||null]); return Promise.resolve(true);}
function offlineKey(){LOG.push(['key']); return 'k1';}
function offlinePick(drag){LOG.push(['queuePick',drag.page]); return Promise.resolve();}
function renderEdit(){LOG.push(['drawEdit']);}
function editSnip(withLevels){LOG.push(['snipEdit',withLevels]); return Promise.resolve();}
function renderReplyOutcome(){LOG.push(['drawReplyOutcome']);}
"""

# What savePin reads and calls besides the seams, as stand-ins (the save of composer/flow-save.ts).
SAVE_SCOPE = r"""
let DOC='a',SWITCHSEQ=1,KIND_NEW='fix',PINS=[],OPEN_ALL=[],META=null,CUT_OFF=false,BODY=null,ANSWER=null;
const DEFAULT_DOC='a';
const COMPOSE={current:null,box:null,saving:false,picking:false,intent:1,retryVerdict:null};
const SECTION_SEEN={open:null},ASSIGN_NEW={v:'agent'},BANNERS=new Map();
function setComposeSaving(v){COMPOSE.saving=v;} function setComposeBox(v){COMPOSE.box=v;}
function setComposeRetryVerdict(v){COMPOSE.retryVerdict=v;}
function offlineNow(){return CUT_OFF;}
function $(name){return name==='#note'?{value:'note'}:{disabled:false,hidden:false};}
const document={querySelectorAll:()=>[]};
class HTMLButtonElement {}
function isRegion(){return false;} function kindFor(){return 'line';} function figureFields(b){return b;}
function figureRung(){return null;} function wireScope(s){return s;}
function mentionHints(){return [];} function composeAsk(mode){return {mode};}
function assignOutcome(){return {kind:KIND_NEW,assignee:ASSIGN_NEW.v};}
function selectionSnapshot(){return {};} function composeFields(){return {};}
function composeOwns(){return true;} function cancelSelection(){COMPOSE.current=null;} function syncDraft(){}
function savedDraftSnapshot(){return null;} function restoredDraftOwns(){return false;} function clearSavedDraft(){}
function restoreSelection(){} function focusClosed(){return null;} function focusPlace(){}
function focusRun(){return {away:()=>false,stop(){}};}
function translateTemplate(s){return s;} function translate(s){return s;} function endNotice(){}
function bannerNote(){LOG.push(['banner']);} function apiFailed(){} function sourceOk(){}
let UNDO=null;
function undoNote(place,msg,act){UNDO=act.fn; LOG.push(['chip']); return null;} function settleChip(){}
function verdictLabel(k){return k;} function verdictOf(){return null;} function isMe(){return true;}
function api(url,ask){BODY=ask.body; LOG.push(['api']); return ANSWER;}
const SUGGEST_DRAFT={on:false}; function suggestOff(){return null;} function suggestForSave(){return null;}
function suggestPending(){return false;}
function topPinId(){return 0;}
"""


def run_save(setup: str, act: str) -> object:
    """savePin wired as js/main.ts wires the composer's seams, after `setup`; `act` prints its result as JSON."""
    return json.loads(
        run_node(
            "\n".join(
                [
                    JS_OFFLINE_STUBS,
                    COMPOSER_FEATURES,
                    js_seams_wired(COMPOSER_SEAMS),
                    *(extract_js_fn(n) for n in ("captureVisit", "currentVisit", "samePlace")),
                    extract_js_fn("syncComposeSaveButtons"),
                    extract_js_fn("findAll"),
                    extract_js_fn("isApiError"),
                    extract_js_fn("isRefusal"),
                    extract_js_fn("savePin"),
                    SAVE_SCOPE,
                    "COMPOSE.current={doc:'a',file:'a.tex',name:'a.tex',page:3,lo:1,hi:2};",
                    setup,
                    "(async()=>{" + act + "})();",
                ]
            )
        )
    )


class ComposerSave(unittest.TestCase):
    """savePin asks the verdict's part, the pin list and the queue at the points it called them directly."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_a_verdict_save_asks_the_verdict_part_in_the_old_order(self):
        """A verdict press: the verdict row waits (drawRow), the figure body is asked before the request, then the
        verdict's [되돌리기], the figure it names and its short name come before the chip, and the pin list is read
        again after it; the row comes back last."""
        got = run_save(
            "FIGURE_ROOT='F1'; ANSWER=Promise.resolve({status:200,data:{id:8}});",
            "await savePin('adopt'); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(
            got,
            [
                ["drawRow"], ["figureBody", 3], ["api"], ["undo", 8], ["figureRoot", 3], ["figureShort", 3, "F1"],
                ["chip"], ["load"], ["drawRow"],
            ],
        )  # fmt: skip

    def test_a_figure_verdict_is_saved_with_the_figures_body(self):
        """The figure body the verdict's part answers is what goes to the server, with the verdict on it."""
        got = run_save(
            "FIGURE_BODY={page:3,el:{path:['F1']}}; ANSWER=Promise.resolve({status:200,data:{id:8}});",
            "await savePin('adopt'); console.log(JSON.stringify(BODY));",
        )
        self.assertEqual((got["el"], got["verdict"], got["kind_req"]), ({"path": ["F1"]}, "adopt", "fix"))

    def test_a_verdict_save_that_failed_after_a_change_says_the_verdict_was_dropped(self):
        """The request fails while the composer's ask has changed: the verdict's part says the verdict was dropped."""
        got = run_save(
            "ANSWER=Promise.reject(Object.assign(new Error('x'),{status:500})).finally(()=>{COMPOSE.intent++;});",
            "await savePin('adopt'); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(got, [["drawRow"], ["figureBody", 3], ["api"], ["dropped"], ["drawRow"]])

    def test_a_plain_save_goes_with_a_key_only_where_the_server_knows_one(self):
        """A plain pin asks the queue whether writes go with a key, and only then for a key, which the body carries."""
        keyed = run_save(
            "OFF.idem=true; ANSWER=Promise.resolve({status:200,data:{id:8}});",
            "await savePin(); console.log(JSON.stringify([LOG.filter(e=>e[0]==='key').length, BODY.idem]));",
        )
        plain = run_save(
            "ANSWER=Promise.resolve({status:200,data:{id:8}});",
            "await savePin(); console.log(JSON.stringify([LOG.filter(e=>e[0]==='key').length, BODY.idem||null]));",
        )
        self.assertEqual((keyed, plain), ([1, "k1"], [0, None]))

    def test_a_plain_saves_undo_takes_the_pin_back_through_the_pin_list(self):
        """The [되돌리기] of a plain pin takes it back as this person's own save, with itself as what a retry runs."""
        got = run_save(
            "ANSWER=Promise.resolve({status:200,data:{id:8}});",
            "await savePin(); LOG.length=0; await UNDO(); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(got, [["drop", 8, True, "function"]])

    def test_a_save_cut_off_goes_into_the_queue(self):
        """Cut off, the pin is kept in the queue with its selection, note, kind and hints; no request goes out."""
        got = run_save("CUT_OFF=true;", "await savePin(); console.log(JSON.stringify(LOG));")
        self.assertEqual(got, [["drawRow"], ["queueSave", 3, "note", "fix", [], None], ["drawRow"]])


class ComposerRows(unittest.TestCase):
    """The verdict row is drawn, and the edit card redrawn, where the composer drew them directly."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_the_save_buttons_wait_then_the_verdict_row_follows(self):
        """syncComposeSaveButtons: the buttons take the save's state first, then the verdict row is drawn."""
        got = json.loads(
            run_node(
                "\n".join(
                    [
                        JS_OFFLINE_STUBS,
                        COMPOSER_FEATURES,
                        js_seams_wired(COMPOSER_SEAMS),
                        extract_js_fn("syncComposeSaveButtons"),
                        extract_js_fn("findAll"),
                        "const COMPOSE={saving:true}; function suggestPending(){return false;}",
                        "class HTMLButtonElement { set disabled(v) { LOG.push(['disabled', v]); } }",
                        "const document={querySelectorAll:()=>[new HTMLButtonElement()]};",
                        "syncComposeSaveButtons(); console.log(JSON.stringify(LOG));",
                    ]
                )
            )
        )
        self.assertEqual(got, [["disabled", True], ["drawRow"]])

    def test_an_excerpt_redraws_the_panel_it_belongs_to(self):
        """excerptRedraw: the composer's own selection redraws the composer, the open edit card's the edit card through
        its field, and a stale owner nothing."""
        got = json.loads(
            run_node(
                "\n".join(
                    [
                        JS_OFFLINE_STUBS,
                        COMPOSER_FEATURES,
                        js_seams_wired(COMPOSER_SEAMS),
                        extract_js_fn("excerptRedraw"),
                        "const COMPOSE={current:{n:1}}, EDITOR={current:{n:2}};",
                        "function renderComposer(){LOG.push(['composer']);}",
                        "excerptRedraw(COMPOSE.current); excerptRedraw(EDITOR.current); excerptRedraw({});",
                        "console.log(JSON.stringify(LOG));",
                    ]
                )
            )
        )
        self.assertEqual(got, [["composer"], ["drawEdit"]])


# Recording stand-ins under the names js/main.ts registers for the pin list's seam (verdict/flow-line.ts).
PIN_FEATURES = r"""
const LOG=[];
function drawPageVerdicts(){LOG.push(['drawLines']);}
function isShownOnLine(pin){LOG.push(['shownOnLine',pin.id]); return pin.id===6;}
function jumpToPageLine(id){LOG.push(['jumpToLine',id]); return id===3;}
function verdictBadge(pin){LOG.push(['badge',pin.id]); return null;}
function verdictTarget(pin){LOG.push(['target',pin.id]); return null;}
function verdictOldMarker(pin){LOG.push(['oldMarker',pin.id]); return null;}
function dropPageLineOverlaps(pin){LOG.push(['dropOverlaps',pin.id]); return pin;}
"""


class PinListVerdicts(unittest.TestCase):
    """The pin list asks the verdicts at the points it called them directly."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_the_page_lines_are_drawn_before_the_marks_and_a_pin_they_show_draws_no_box(self):
        """marks(): the page verdict lines first, then for each pin whether a line shows it; the pin a line shows draws
        no mark, the others do."""
        got = json.loads(
            run_node(
                "\n".join(
                    [
                        PIN_FEATURES,
                        r"""
            const DOC='d', DEFAULT_DOC='d', markBadgeSides=()=>{}, drawChips=()=>{}; let PINS=[], REVIEW_ALL=[];
            const isMarkdownDoc=()=>false;
            const $$=()=>[]; const esc=s=>String(s);
            const page1={appendChild:m=>LOG.push(['mark',m.dataset.pin])};
            const document={getElementById:id=>id==='p1'?page1:null,
              createElement:()=>({dataset:{},style:{},className:'',set innerHTML(v){}})};""",
                        js_markup(),
                        js_i18n(),
                        js_seams_wired(PIN_SEAMS),
                        *(
                            extract_js_fn(n)
                            for n in ("isFrac", "hasMark", "pinPlace", "isElementLost", "isEstimated", "pinState")
                        ),
                        extract_js_fn("pdoc"),
                        extract_js_fn("marks"),
                        "const good=[0.1,0.2,0.3,0.4]; PINS=[{id:5,page:1,frac:good},{id:6,page:1,frac:good}];",
                        "marks(); console.log(JSON.stringify(LOG));",
                    ]
                )
            )
        )
        self.assertEqual(got, [["drawLines"], ["shownOnLine", 5], ["mark", "5"], ["shownOnLine", 6]])

    def test_a_pin_a_page_line_shows_is_jumped_to_on_its_line(self):
        """jumpPin(): once the changes view is left, a pin a page line shows is jumped to on its line and nothing else
        happens; another pin goes on to the marks."""
        got = json.loads(
            run_node(
                "\n".join(
                    [
                        PIN_FEATURES,
                        js_seams_wired(PIN_SEAMS),
                        extract_js_fn("jumpPin"),
                        "let DOC='d', PINS=[{id:3},{id:4}], REVIEW_ALL=[], LAYOUT='wide';",
                        "function viaDoc(){return false;} function pdoc(){return 'd';} function isMarkdownDoc(){return true;}",
                        "const document={body:{classList:{contains:()=>true}}};",
                        "function setViewMode(mode){LOG.push(['setViewMode',mode]);} function marksShow(){LOG.push(['marksShow']);}",
                        "function jumpToPinLines(id){LOG.push(['pinLines',id]);}",
                        "jumpPin(3); jumpPin(4); console.log(JSON.stringify(LOG));",
                    ]
                )
            )
        )
        self.assertEqual(
            got,
            [
                ["setViewMode", "manuscript"], ["jumpToLine", 3],
                ["setViewMode", "manuscript"], ["jumpToLine", 4], ["marksShow"], ["pinLines", 4],
            ],
        )  # fmt: skip

    def test_a_result_row_asks_the_badge_the_old_mark_and_the_target(self):
        """resultRow(): the badge, the old mark and the target, in that order, for the pin the row is for."""
        got = json.loads(
            run_node(
                "\n".join(
                    [
                        PIN_FEATURES,
                        js_seams_wired(PIN_SEAMS),
                        js_i18n(),
                        js_icons(),
                        extract_js_fn("resultRow"),
                        "let REVIEW_PICK=null; const TIP_TEXT={question:'',change:''}; const esc=(text)=>String(text);",
                        "function showsResult(){return true;} function pinPlace(){return {page:1};} function isMarkdownPin(){return false;}",
                        "function isQuestion(){return false;} function suggestBadge(){return null;} function fmtText(t){return t;}",
                        "function verdictOf(){return null;} function changedLinesText(){return '';} function messageBody(){return '';}",
                        "function locText(){return '';} function docChip(){return '';} function pdoc(){return 'd';}",
                        "resultRow({id:4,note:'n'}); console.log(JSON.stringify(LOG));",
                    ]
                )
            )
        )
        self.assertEqual(got, [["badge", 4], ["oldMarker", 4], ["target", 4]])


if __name__ == "__main__":
    unittest.main()
