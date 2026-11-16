"""What documents asks the features above it (documents/state-seams.ts, docs/handbook/viewer.md §모듈 경계): documents
decides which document is open and when it is drawn, saved, left and refreshed, and calls the pages, their outline and
page list, the Markdown surface, the changes view, the drafts and edits on the page, the pins and their notifications,
the verdict's hold on the reading line and the queued pins through seams js/main.ts registers.

test_viewer_platform_seams.py holds that js/main.ts registers every seam once before boot() and that an unregistered one
throws by name. These tests run documents' own functions under node, wired by js/main.ts's own registration
(js_seams_wired) with recording stand-ins under the names it registers, and hold that each call reaches the feature at
the point it stood, with the same arguments, its answer used the same way, and in the same order among its neighbours -
so a member wired to the wrong function, or a call moved, fails here.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_documents_seams.py
"""

import json
import unittest

from helpers import JS_UPDATE_STUBS, extract_js_fn, js_seams_wired, run_node
from helpers_notices import node_or_skip

DOCUMENT_SEAMS = "documents/state-seams.ts"

# Recording stand-ins under the names js/main.ts registers for documents' seams: the pages (pdf/view-pages.ts,
# pdf/flow-open.ts, pdf/view-draw.ts), the outline, page list and search (pdf/view-outline.ts, pdf/view-page-list.ts,
# pdf/flow.ts), the Markdown surface (markdown/view.ts) and the changes view (revisions/flow.ts).
SURFACES = r"""
const LOG=[];
function buildDoc(){LOG.push(['build']);}
function autoFitWidth(){LOG.push(['fitWidth']);}
function widestPagePoints(){LOG.push(['widestPoints']); return 600;}
function startScale(){LOG.push(['startScale']); return 1.25;}
function reapplyScale(){LOG.push(['reapplyScale']);}
function pageSrc(page){LOG.push(['pageSource',page.n]); return 'png-'+page.n;}
function openVectorDocument(){LOG.push(['openVector']);}
function releaseAllVectorPages(){LOG.push(['releaseVector']);}
function searchLeave(){LOG.push(['leaveSearch']);}
function searchFit(){LOG.push(['fitSearch']);}
function closePageList(back){LOG.push(['closePageList',back]);}
let OUTLINE_ACTIVE_PAGE=7;
function markOutline(){LOG.push(['markOutline']);}
function drawSheetPages(){LOG.push(['drawSheetPages']);}
function revealPageRow(list){LOG.push(['revealPageRow',list.id]);}
function tipCutTitles(list){LOG.push(['tipCutTitles',list.id]);}
const MARKDOWN_VIEW={doc:'a',shown:'a',mtime:5,asked:null,at:12,lines:['x','y','z'],want:null};
function buildMarkdownDoc(){LOG.push(['markdownBuild',MARKDOWN_VIEW.asked]);}
function checkTreeImages(){LOG.push(['checkTreeImages']); return Promise.resolve(0);}
function readingAnchor(){LOG.push(['readingAnchor']); return {line:3,off:4,top:5};}
function markdownPositionLabel(...a){LOG.push(['positionLabel',...a]); return {name:'N',pages:'12/3',label:'L'};}
function showMarkdownHint(){LOG.push(['showHint']);}
const LEAVES=[{id:'l1',classList:{add(c){LOG.push(['tint','l1',c]);}}},{id:'l2',classList:{add(c){LOG.push(['tint','l2',c]);}}}];
function lineLeaves(first,last){LOG.push(['lineLeaves',first,last]); return LEAVES;}
function showLines(elements){LOG.push(['showLines',elements.map(e=>e.id)]);}
const REVISION_VIEW={want:null,target:{id:9}};
function setViewMode(mode){LOG.push(['setMode',mode,REVISION_VIEW.want,REVISION_VIEW.target]);}
function loadRevisions(){LOG.push(['load',REVISION_VIEW.want,REVISION_VIEW.target]);}
"""


def run(*parts: str) -> object:
    """parts joined after the stand-ins and the wiring; the script prints its result as JSON."""
    return json.loads(run_node("\n".join([SURFACES, js_seams_wired(DOCUMENT_SEAMS), *parts])))


# What the document switch and the screen redraw read and call besides the seams, as recording stand-ins.
SWITCH_SCOPE = r"""
let DOC='a',SWITCHSEQ=0,NAVGEN=0,LAYOUT='wide',PAGE_SCALE=1,ZOOMED=false,META={pages:[{}]},REVISION_OPEN=true;
let OPEN_ALL=[],DONE_ALL=[],PINS=[],DONE=[];
const COMPOSE={current:null},EDITOR={current:null},VIEW_BY=new Map(),META_BY=new Map([['b',{pages:[{}],pages_build:'v1'}]]);
const document={activeElement:null,body:{classList:{contains:(c)=>c==='revision-open'&&REVISION_OPEN}}};
const ELS={}; function $(sel){return ELS[sel]||(ELS[sel]={hidden:true,scrollTop:3,textContent:''});}
var LAYOUT_MODE={WIDE:'wide'},VIEW_MODE={MANUSCRIPT:'manuscript',REVISIONS:'revisions'};
function setSwitchseq(v){SWITCHSEQ=v; return v;} function setDoc(v){DOC=v;} function setMeta(v){META=v;}
function setPins(v){PINS=v;} function setDone(v){DONE=v;}
function setPageScale(v){LOG.push(['pageScale',v]); PAGE_SCALE=v;} function setZoomed(v){ZOOMED=v;}
function docInfo(k){return {key:k};} function pdoc(p){return p.doc;}
function saveView(){LOG.push(['saveView']);} function parkDraft(){LOG.push(['parkDraft']);}
function cancelRepick(){LOG.push(['cancelRepick']);} function cancelSelection(){LOG.push(['cancelSelection']);}
function editDirty(){return false;} function cancelEdit(){LOG.push(['cancelEdit']);}
function restoreDraft(){LOG.push(['restoreDraft']);} function openDraftDoc(){LOG.push(['openDraft']);}
function savePrefs(){} function setHash(){LOG.push(['setHash']);} function hideTip(){LOG.push(['hideTip']);}
function checkDocUpdate(){LOG.push(['checkDocUpdate']);}
function endJumpForScroll(){LOG.push(['endJump']);} function drawMeta(){LOG.push(['drawMeta']);}
function restoreView(view){LOG.push(['restoreView']);}
function drawPins(){LOG.push(['drawPins']);} function marks(){LOG.push(['marks']);}
function drawDocTabs(){LOG.push(['drawDocTabs']);} function resetBuildForDoc(){LOG.push(['resetBuild']);}
function docTitle(){LOG.push(['docTitle']);}
function withDocQuery(u){return u;} function api(){return new Promise(()=>{});}
"""


class SwitchAndShow(unittest.TestCase):
    """switchDoc leaves the search and the changes view, then showDoc scales, draws and opens the pages and reads the
    commits again, each at its old place among documents' own steps."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def switch(self, setup):
        # the stand-ins after the served functions, whose setters (setPageScale ...) they replace with recording ones
        return run(
            JS_UPDATE_STUBS,
            *(extract_js_fn(n) for n in ("switchDoc", "showDoc", "applyViewWidth", "viewScale")),
            SWITCH_SCOPE,
            setup,
            "switchDoc('b'); console.log(JSON.stringify(LOG));",
        )

    def test_a_switch_leaves_then_shows_in_the_old_order(self):
        """The search ends first, the changes view goes back to the manuscript before the view is saved, and showDoc
        draws the pages, fits them without a kept view, and reads the commits again before opening the PDF."""
        self.assertEqual(
            self.switch(""),
            [
                ["leaveSearch"],
                ["setMode", "manuscript", None, {"id": 9}],
                ["saveView"],
                ["parkDraft"],
                ["cancelRepick"],
                ["setHash"],
                ["hideTip"],
                ["endJump"],
                ["drawMeta"],
                ["startScale"],
                ["pageScale", 1.25],
                ["build"],
                ["fitWidth"],
                ["restoreView"],
                ["drawPins"],
                ["marks"],
                ["drawDocTabs"],
                ["load", None, {"id": 9}],
                ["openVector"],
                ["resetBuild"],
                ["docTitle"],
                ["openDraft"],
                ["checkDocUpdate"],
            ],
        )

    def test_a_kept_view_takes_its_width_over_the_widest_page(self):
        """A view kept with a page width in this layout: the widest page is asked, its answer divides the width, and
        the pages are not fitted again (outside the changes view, nothing is said to it)."""
        got = self.switch("REVISION_OPEN=false; VIEW_BY.set('b',{lay:'wide',w:900});")
        self.assertEqual(
            got[: got.index(["restoreView"]) + 1],
            [
                ["leaveSearch"],
                ["saveView"],
                ["parkDraft"],
                ["cancelRepick"],
                ["setHash"],
                ["hideTip"],
                ["endJump"],
                ["drawMeta"],
                ["widestPoints"],
                ["pageScale", 1.5],
                ["build"],
                ["restoreView"],
            ],
        )
        self.assertNotIn(["load", None, {"id": 9}], got)


# What refreshDoc reads and calls besides the seams.
REFRESH_SCOPE = r"""
let DOC='a',SWITCHSEQ=1,REFRESH_GEN=0,META={pages:[{n:1},{n:2}]},MARKDOWN=false;
const META_BY=new Map();
const document={body:{classList:{contains:(c)=>c==='revision-open'}}};
function rendersInBrowser(){return MARKDOWN;}
function withDocQuery(u){return u;} function api(){return Promise.resolve({data:SNAPSHOT});}
function topAnchor(){return {page:1};} function restoreAnchor(){LOG.push(['restoreAnchor',BUILD_READING_PAGE]);}
function rebuildSources(){return [];} function sourceOk(){}
function setMeta(v){META=v;} function drawMeta(){LOG.push(['drawMeta']);}
function isComposingNow(){return false;}
// the reading page held while the pages are built again (verdict/view-panel.ts)
var BUILD_READING_PAGE=0; function pageUnderReadingLine(){return 4;}
function setBuildReadingPage(value){BUILD_READING_PAGE=value; return value;}
function buildDoc(){LOG.push(['build',BUILD_READING_PAGE]);}
function loadPins(){LOG.push(['loadPins']); return Promise.resolve(true);}
const IMGS=[{},{}];
function $$(){return IMGS.map((img)=>({dataset:{},style:{},querySelector:()=>img}));}
"""


class Refresh(unittest.TestCase):
    """refreshDoc draws a new build through the pages and the Markdown surface, at the points it drew them directly."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def refresh(self, setup):
        return run(
            REFRESH_SCOPE,
            extract_js_fn("refreshDoc"),
            setup,
            "refreshDoc(SNAPSHOT).then(()=>console.log(JSON.stringify({log:LOG,imgs:IMGS.map(i=>i.src)})));",
        )

    def test_the_same_page_count_swaps_the_pictures_in_place(self):
        """Lets go of the PDF.js pages, gives each page its new picture's address, sizes the pages again, then opens
        the new PDF and reads the commits before the pins."""
        got = self.refresh("const SNAPSHOT={pages:[{n:1,pt_w:1,pt_h:1},{n:2,pt_w:1,pt_h:1}]};")
        self.assertEqual(
            got["log"],
            [
                ["drawMeta"],
                ["releaseVector"],
                ["pageSource", 1],
                ["pageSource", 2],
                ["reapplyScale"],
                ["restoreAnchor", 0],
                ["openVector"],
                ["load", None, {"id": 9}],
                ["loadPins"],
            ],
        )
        self.assertEqual(got["imgs"], ["png-1", "png-2"])

    def test_another_page_count_builds_the_pages_while_the_reading_page_is_held(self):
        """The reading page is held around the build and the spot restored inside the hold."""
        got = self.refresh("const SNAPSHOT={pages:[{n:1}]};")
        self.assertEqual(
            got["log"],
            [
                ["drawMeta"],
                ["build", 4],
                ["restoreAnchor", 4],
                ["restoreAnchor", 0],
                ["openVector"],
                ["load", None, {"id": 9}],
                ["loadPins"],
            ],
        )

    def test_a_document_drawn_from_its_source_is_drawn_again_before_its_pins(self):
        """No pages: the meta, then the Markdown surface's build, then the pins."""
        got = self.refresh("MARKDOWN=true; const SNAPSHOT={pages:[]};")
        self.assertEqual(got["log"], [["drawMeta"], ["markdownBuild", None], ["loadPins"]])


class Poll(unittest.TestCase):
    """pollLightOnce asks the Markdown surface for a source it has not read yet, once per change."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def poll(self, setup):
        return run(
            JS_UPDATE_STUBS + extract_js_fn("pollLightOnce"),
            r"""
            let DOC='a',SWITCHSEQ=1,LAST_PINS_REVISION='r',LAST_SRC_MTIME=5,POLL_FAILS=0; const BUILD={lastSeq:0,timer:null};
            const OFF={n:0};
            function isMarkdownDoc(){return true;} function withDocQuery(u){return u;} function notifyQuery(){return '';}
            function $(){return {hidden:true};} function notifyHandle(){} function updateStaleBadge(){} function updateSyncBadge(){}
            function noteOtherDocs(){} function loadPins(){LOG.push(['loadPins']); return Promise.resolve(true);}
            function pollBuild(){}
            """,
            setup,
            "pollLightOnce().then(()=>console.log(JSON.stringify({log:LOG,asked:MARKDOWN_VIEW.asked})));",
        )

    def test_a_new_source_is_asked_for_once_and_drawn(self):
        """The source time the poll saw is not the drawn one nor the one asked for: it is noted as asked, then the
        surface reads and draws it."""
        got = self.poll("function api(){return Promise.resolve({data:{pins_rev:'r',src_mtime:9,src_sig:5}});}")
        self.assertEqual(got, {"log": [["markdownBuild", 9]], "asked": 9})

    def test_a_source_already_asked_for_only_checks_the_tree_images(self):
        """The time asked for already: no second read, the tree images are looked at instead."""
        got = self.poll(
            "MARKDOWN_VIEW.asked=9; function api(){return Promise.resolve({data:{pins_rev:'r',src_mtime:9,src_sig:5}});}"
        )
        self.assertEqual(got, {"log": [["checkTreeImages"]], "asked": 9})


class ReadingPosition(unittest.TestCase):
    """The phone's position button, the kept view and its return read the Markdown surface and the outline."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    POSITION = r"""
    let DOC='a',MD=true,META={pages:[{},{},{}]},LAYOUT='wide';
    const DOCS=[],VIEW_BY=new Map(); var VIEW_MODE={MANUSCRIPT:'manuscript',REVISIONS:'revisions'};
    const document={body:{classList:{contains:()=>false}}}; const innerWidth=500;
    const ELS={}; function $(sel){return ELS[sel]||(ELS[sel]={hidden:false,dataset:{},setAttribute(k,v){this[k]=v;},scrollLeft:0});}
    function isMarkdownDoc(){return MD;} function docInfo(){return {name:'main'};} function multiDoc(){return true;}
    function saveViews(){}
    """

    def test_the_position_button_reads_the_line_or_the_outline_page(self):
        """A drawn document: the label of its name, the line read now and the line count; a PDF: the outline's page."""
        got = run(
            self.POSITION,
            extract_js_fn("posLabel"),
            extract_js_fn("drawPos"),
            "drawPos(); const md=$('#btn-pos-p').textContent; MD=false; drawPos();"
            "console.log(JSON.stringify({log:LOG,md,pdf:$('#btn-pos-p').textContent}));",
        )
        self.assertEqual(got, {"log": [["positionLabel", "main", 12, 3, True, True]], "md": "12/3", "pdf": "7/3"})

    def test_a_kept_view_reads_the_drawn_documents_anchor_and_its_return_sets_the_line(self):
        """saveView asks for the anchor only while this document is the one drawn; restoreView writes the line to
        come back to."""
        got = run(
            self.POSITION,
            extract_js_fn("saveView"),
            extract_js_fn("restoreView"),
            "saveView(); MARKDOWN_VIEW.shown='b'; saveView(); restoreView({line:6,off:'2'});"
            "console.log(JSON.stringify({log:LOG,kept:VIEW_BY.get('a'),want:MARKDOWN_VIEW.want}));",
        )
        self.assertEqual(
            got,
            {
                "log": [["readingAnchor"]],
                "kept": {"line": 3, "off": 4, "lay": "wide"},
                "want": {"line": 6, "off": 2, "top": 0},
            },
        )


class Navigation(unittest.TestCase):
    """The navigation sheet and the document menu reach the outline and the page list at their old places."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_the_navigation_sheet_marks_the_outline_then_draws_and_reveals_the_page_rows(self):
        """Its outline's mark after the documents and the view, the page field's placeholder from the outline's page,
        the page rows drawn before the sheet shows, then the current row revealed and the cut titles tipped."""
        got = run(
            r"""
            let META={pages:[{},{}]};
            const ELS={}; function $(sel){return ELS[sel]||(ELS[sel]={id:sel,open:false,value:'x',placeholder:''});}
            function hideTip(){LOG.push(['hideTip']);} function drawDocsMenu(){LOG.push(['drawDocsMenu']);}
            function drawNavigationView(){LOG.push(['drawNavigationView']);} function showSheet(){LOG.push(['showSheet']);}
            function revealSheetOutline(){LOG.push(['revealSheetOutline']);}
            """,
            extract_js_fn("openNavigationSheet"),
            "openNavigationSheet(); console.log(JSON.stringify({log:LOG,placeholder:$('#ns-page-in').placeholder}));",
        )
        self.assertEqual(
            got,
            {
                "log": [
                    ["hideTip"],
                    ["drawDocsMenu"],
                    ["drawNavigationView"],
                    ["markOutline"],
                    ["drawSheetPages"],
                    ["showSheet"],
                    ["revealPageRow", "#ns-pages"],
                    ["tipCutTitles", "#ns-pages"],
                    ["revealSheetOutline"],
                ],
                "placeholder": "7",
            },
        )

    def test_the_document_menu_closes_the_page_list_without_giving_the_focus_back(self):
        """openDocMenu closes the page list's popover (back false) right after the tip, before drawing itself."""
        got = run(
            r"""
            const DOCS=[]; const COARSE_POINTER_QUERY={matches:false};
            const ELS={}; function $(sel){return ELS[sel]||(ELS[sel]={hidden:true,setAttribute(){},focus(){},scrollIntoView(){}});}
            function hideTip(){LOG.push(['hideTip']);} function drawDocMenu(){LOG.push(['drawDocMenu']);}
            function placeDocMenu(){LOG.push(['placeDocMenu']);}
            """,
            extract_js_fn("openDocMenu"),
            "openDocMenu(); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(got, [["hideTip"], ["closePageList", False], ["drawDocMenu"], ["placeDocMenu"]])


class Updates(unittest.TestCase):
    """The update messages open the changes view on their range and point at the Markdown lines that changed."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    UPDATES = r"""
    let DOC='a',SWITCHSEQ=1,OPEN=false,META={src_mtime:1};
    const document={body:{classList:{contains:(c)=>c==='revision-open'&&OPEN}}};
    var VIEW_MODE={MANUSCRIPT:'manuscript',REVISIONS:'revisions'};
    const UPDATE_STATE={lines:new Map([['a',{at:0,ranges:[{lo:2,hi:3},{lo:8,hi:9}]}]])};
    function switchDoc(){LOG.push(['switchDoc']);} function isMarkdownDoc(){return true;}
    function $$(){return [];}
    """

    def test_an_update_range_is_written_before_the_changes_view_opens_or_reads_it_again(self):
        """The range and no pin are written into the view, then it opens - or, open already, reads its commits."""
        got = run(
            self.UPDATES,
            extract_js_fn("openUpdateRange"),
            "openUpdateRange('a','b1','t1'); OPEN=true; openUpdateRange('a','b2'); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(
            got,
            [
                ["setMode", "revisions", {"base": "b1", "top": "t1"}, None],
                ["load", {"base": "b2", "top": ""}, None],
            ],
        )

    def test_the_next_change_and_the_tint_take_the_changed_lines_from_the_surface(self):
        """goToNextChange shows the line elements of the next range; tintChangedLines tints every range's lines."""
        got = run(
            self.UPDATES,
            extract_js_fn("goToNextChange"),
            extract_js_fn("tintChangedLines"),
            "goToNextChange('a'); LOG.push(['--']); tintChangedLines(); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(
            got,
            [
                ["lineLeaves", 8, 9],
                ["showLines", ["l1", "l2"]],
                ["--"],
                ["lineLeaves", 2, 3],
                ["tint", "l1", "md-upd"],
                ["tint", "l2", "md-upd"],
                ["lineLeaves", 8, 9],
                ["tint", "l1", "md-upd"],
                ["tint", "l2", "md-upd"],
            ],
        )

    def test_the_document_on_screen_is_dated_by_the_source_the_surface_drew(self):
        """shownDocState reads the drawn document's source time while it is the one drawn, the meta's otherwise."""
        got = run(
            self.UPDATES,
            "const META_BY=new Map(); function docInfo(){return {kind:'markdown',name:'a'};} function rendersInBrowser(){return true;}",
            extract_js_fn("shownDocState"),
            "const drawn=shownDocState('a'); MARKDOWN_VIEW.doc='b'; const other=shownDocState('a');"
            "console.log(JSON.stringify([drawn.ver,other.ver]));",
        )
        self.assertEqual(got, ["src:5", "src:1"])


class Meta(unittest.TestCase):
    """drawMeta hides the page-only controls through the Markdown surface between the body's classes and the reading
    area's name."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_the_hint_comes_after_the_surface_class_and_before_the_area_name(self):
        got = run(
            r"""
            const META={kind:'markdown',main:'a.md',pages:[],me:{}};
            const any=()=>new Proxy({},{get:(t,k)=>k in t?t[k]:(k==='dataset'?(t[k]={}):undefined),set:(t,k,v)=>(t[k]=v,true)});
            const ELS={'#left':{setAttribute(k,v){LOG.push(['left',k,v]);}}};
            function $(sel){return ELS[sel]||(ELS[sel]=any());}
            const document={body:{classList:{toggle(c,on){LOG.push(['body',c,on]);}}}};
            function buildsFromSource(){return false;} function isFigureKind(){return false;} function isMarkdownDoc(){return true;}
            function isTextDoc(){return false;} function isViewer(){return false;} function html(){return '';} function setHtml(){}
            function avatar(){return '';} function who(){return '';} function isAgent(){return false;} function commitShown(){return '';}
            function updateStaleBadge(){} function updateSyncBadge(){} function moreInfo(){return '';}
            """,
            extract_js_fn("drawMeta"),
            "drawMeta(); console.log(JSON.stringify(LOG.slice(0,6)));",
        )
        self.assertEqual(
            got,
            [
                ["body", "no-rebuild", True],
                ["body", "fig-doc", False],
                ["body", "md-surface", True],
                ["showHint"],
                ["left", "aria-label", "Markdown 문서"],
                ["body", "role-viewer", False],
            ],
        )


class LeavingWork(unittest.TestCase):
    """switchDoc keeps, drops and brings back the work on the page through documentWork, guarded as before."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def switch(self, setup, then="switchDoc('b')"):
        # a kept document shows at once, its fresh meta never answering here: the log is read right after the call
        return run(
            JS_UPDATE_STUBS,
            *(extract_js_fn(n) for n in ("switchDoc", "showDoc", "applyViewWidth", "viewScale")),
            SWITCH_SCOPE,
            "REVISION_OPEN=false;",
            setup,
            "(async()=>{%s; console.log(JSON.stringify(LOG));})();" % then,
        )

    def test_an_open_composer_is_cancelled_keeping_nothing_and_a_clean_edit_closes(self):
        """The draft is parked and the re-placing ended, then - a pin being composed - the selection is cancelled with
        clearNote false, and the edit card, asked whether it holds a change and answering no, is closed."""
        got = self.switch(
            "COMPOSE.current={}; EDITOR.current={};"
            "function cancelSelection(clearNote){LOG.push(['cancelSelection',clearNote]);}"
            "function editDirty(){LOG.push(['editDirty']); return false;}"
        )
        self.assertEqual(
            got[:7],
            [["leaveSearch"], ["saveView"], ["parkDraft"], ["cancelRepick"], ["cancelSelection", False], ["editDirty"],
             ["cancelEdit"]],
        )  # fmt: skip

    def test_an_edit_with_a_change_stays_open(self):
        """editDirty's yes keeps the edit card: no cancelEdit."""
        got = self.switch("EDITOR.current={}; function editDirty(){LOG.push(['editDirty']); return true;}")
        self.assertIn(["editDirty"], got)
        self.assertNotIn(["cancelEdit"], got)

    def test_a_failed_read_of_the_document_brings_the_draft_back(self):
        """A document with no kept meta whose read fails: the parked draft comes back, and nothing is shown."""
        got = self.switch("function api(){return Promise.reject(new Error('no'));}", then="await switchDoc('c')")
        self.assertEqual(got, [["leaveSearch"], ["saveView"], ["parkDraft"], ["cancelRepick"], ["restoreDraft"]])

    def test_a_reload_asks_the_reply_box_and_the_edit_card_what_would_be_lost(self):
        """reloadForUpdate reads the open reply box's field, then asks the edit card - a reply being written stops the
        reload before the edit card is asked."""
        got = run(
            r"""
            let REPLY={id:1}; const REPLY_DRAFT=new Set(); var NOTICE_KIND={WARN:'warn'};
            let FIELD={value:''}; function replyNote(reply){LOG.push(['replyNote',reply.id]); return FIELD;}
            function editDirty(){LOG.push(['editDirty']); return false;}
            function lineNote(){LOG.push(['said']);} function flushDeferred(){LOG.push(['flush']);}
            const location={reload(){LOG.push(['reload']);}};
            """,
            extract_js_fn("reloadForUpdate"),
            "reloadForUpdate(); LOG.push(['--']); FIELD={value:'답'}; reloadForUpdate(); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(
            got, [["replyNote", 1], ["editDirty"], ["flush"], ["reload"], ["--"], ["replyNote", 1], ["said"]]
        )


# The light poll's own state and what it calls besides the seams.
POLL_SCOPE = r"""
let DOC='a',SWITCHSEQ=1,LAST_PINS_REVISION='r',LAST_SRC_MTIME='s',POLL_FAILS=0,HIDDEN=false,NOTIFY_HIDDEN_INFLIGHT=null;
const BUILD={lastSeq:0,timer:null}; const OFF={n:0,held:0};
const document={get hidden(){return HIDDEN;}};
function isMarkdownDoc(){return false;} function withDocQuery(u){return u;}
const ELS={}; function $(sel){return ELS[sel]||(ELS[sel]={hidden:false});}
function notifyOn(){LOG.push(['on']); return true;} function notifyQuery(){LOG.push(['query']); return '&ev=4';}
function notifyHandle(meta){LOG.push(['handle',meta.tag]);}
function offlineFlush(){LOG.push(['flush']); return Promise.resolve();}
function updateStaleBadge(){LOG.push(['staleBadge']);} function updateSyncBadge(){} function noteOtherDocs(){}
let APPLIED=true; function loadPins(){LOG.push(['loadPins']); return Promise.resolve(APPLIED);}
function pollBuild(){} function announce(){}
let META={tag:'m',pins_rev:'r2',src_sig:'s'};
function api(url){LOG.push(['api',url]); return Promise.resolve({data:META});}
"""


class LightPoll(unittest.TestCase):
    """pollLightOnce asks for the events, says them, sends the queued pins back online and reads the pins, each
    through its seam at its old place, the answers used as before."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def poll(self, setup, call="pollLightOnce()"):
        return run(
            JS_UPDATE_STUBS + extract_js_fn("pollLightOnce"),
            extract_js_fn("pollHiddenNotify"),
            extract_js_fn("pollHiddenNotifyOnce"),
            POLL_SCOPE,
            setup,
            "Promise.resolve(%s).then(()=>console.log(JSON.stringify({log:LOG,rev:LAST_PINS_REVISION})));" % call,
        )

    def test_the_events_are_asked_for_and_said_before_the_visit_is_checked(self):
        """The query joins the meta's address, the answer's events are said first; then the badge and the pins, whose
        applied read moves the revision baseline."""
        got = self.poll("")
        self.assertEqual(
            got,
            {
                "log": [["query"], ["api", "/api/meta?light=1&ev=4"], ["handle", "m"], ["staleBadge"], ["loadPins"]],
                "rev": "r2",
            },
        )

    def test_a_pin_read_that_did_not_apply_keeps_the_baseline(self):
        """load()'s false: the revision is read again on the next poll."""
        self.assertEqual(self.poll("APPLIED=false;")["rev"], "r")

    def test_the_queued_pins_are_sent_when_the_connection_comes_back(self):
        """After failed polls and with pins queued, flush() runs before the badges; with none queued it does not."""
        sent = self.poll("POLL_FAILS=1; OFF.n=2;")["log"]
        none = self.poll("POLL_FAILS=1;")["log"]
        self.assertEqual(sent[3:5], [["flush"], ["staleBadge"]])
        self.assertNotIn(["flush"], none)

    def test_a_hidden_tab_asks_for_the_events_only_while_notifications_are_on(self):
        """pollHiddenNotify asks whether they are on; pollHiddenNotifyOnce joins the query and says the answer while
        the tab is still hidden."""
        got = self.poll("HIDDEN=true;", call="pollHiddenNotify()")
        self.assertEqual(got["log"], [["on"], ["query"], ["api", "/api/meta?light=1&ev=4"], ["handle", "m"]])
        off = self.poll("HIDDEN=true; function notifyOn(){LOG.push(['on']); return false;}", call="pollHiddenNotify()")
        self.assertEqual(off["log"], [["on"]])

    def test_the_timer_of_a_hidden_tab_starts_only_while_notifications_are_on(self):
        """syncHiddenNotifyTimer asks whether they are on before polling and starting its timer."""
        got = run(
            POLL_SCOPE,
            r"""
            HIDDEN=true; let NOTIFY_HIDDEN_TIMER; const NOTIFY_HIDDEN_INTERVAL_MS=20000;
            function pollHiddenNotify(){LOG.push(['poll']);}
            function setInterval(fn,ms){LOG.push(['timer',ms]); return 1;} function clearInterval(){}
            """,
            extract_js_fn("syncHiddenNotifyTimer"),
            "syncHiddenNotifyTimer(); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(got, [["on"], ["poll"], ["timer", 20000]])


class PinNews(unittest.TestCase):
    """The update messages read the notification cursor and open a new pin as its link does."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_a_device_with_a_cursor_was_here_before(self):
        got = run(
            "let CURSOR=null; function notifyCursor(){LOG.push(['cursor']); return CURSOR;} function seenStore(){return {};}",
            extract_js_fn("visitedBefore"),
            "const before=visitedBefore(); CURSOR=3; console.log(JSON.stringify([before,visitedBefore(),LOG.length]));",
        )
        self.assertEqual(got, [False, True, 2])

    def test_a_new_pins_view_opens_the_pin_and_hands_back_what_the_link_returns(self):
        """[보기]'s fn opens the first new pin of the message's document and returns openPinFromLink's promise."""
        got = run(
            r"""
            let DOC='a'; const GROUPS=new Map(),UPDATE_STATE={top:0}; var NOTICE_KIND={INFO:'info'},NOTICE_DOT={SIDE:'side'};
            function docInfo(){return {name:'a'};} function setSeenPin(){}
            const OPENED=Promise.resolve('opened');
            function openPinFromLink(doc,pin,restore){LOG.push(['openFromLink',doc,pin,restore===undefined]); return OPENED;}
            """,
            extract_js_fn("newPinsView"),
            "const view=newPinsView({doc:'b',pins:[{id:12,who:'x'}]}); const back=view.act.fn();"
            "console.log(JSON.stringify([LOG,back===OPENED]));",
        )
        self.assertEqual(got, [[["openFromLink", "b", 12, True]], True])


class ReadingLineHold(unittest.TestCase):
    """refreshDoc waits for a syllable being composed before it builds the pages, then reads the spot again."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_a_syllable_being_composed_ends_before_the_pages_are_built(self):
        got = run(
            REFRESH_SCOPE,
            r"""
            var BUILD_READING_PAGE=0; function setBuildReadingPage(value){BUILD_READING_PAGE=value; return value;}
            function pageUnderReadingLine(){LOG.push(['readingPage']); return 4;}
            function buildDoc(){LOG.push(['build',BUILD_READING_PAGE]);}
            function isComposingNow(){LOG.push(['composing']); return true;}
            function afterComposition(){LOG.push(['afterComposition']); return Promise.resolve();}
            function topAnchor(){LOG.push(['anchor']); return {page:1};}
            const SNAPSHOT={pages:[{n:1}]};
            """,
            extract_js_fn("refreshDoc"),
            "refreshDoc(SNAPSHOT).then(()=>console.log(JSON.stringify(LOG.slice(0,7))));",
        )
        self.assertEqual(
            got,
            [["anchor"], ["composing"], ["afterComposition"], ["anchor"], ["drawMeta"], ["readingPage"], ["build", 4]],
        )


class QueuedPins(unittest.TestCase):
    """The status line reads how many pins are queued and held back."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_the_status_input_counts_the_queued_and_held_pins(self):
        got = run(
            r"""
            const OFF={n:3,held:1}; const LINE=[],BUILD={cur:null,error:null,unchanged:null};
            let POLL_FAILS=0,STATUS_SYNC=null,META=null;
            function versionOutdated(){return false;} function $(){return {hidden:true};}
            function buildsFromSource(){return false;} function isViewer(){return false;}
            """,
            extract_js_fn("statusInput"),
            "const input=statusInput(); console.log(JSON.stringify([input.queued,input.held]));",
        )
        self.assertEqual(got, [3, 1])


if __name__ == "__main__":
    unittest.main()
