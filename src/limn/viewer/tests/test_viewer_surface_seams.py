"""What the reading surfaces ask the features above them (pdf/state-seams.ts, markdown/state-seams.ts,
docs/handbook/viewer.md §모듈 경계): the page surface asks for the pins' marks, the verdict's page lines and reason
field, the composer that takes a selection, the Markdown surface and the changes view; the Markdown surface asks for
the text surface, the composer and verdict rows a line pick fills, and the pins' marks.

test_viewer_platform_seams.py holds that js/main.ts registers every seam once before boot() and that an unregistered one
throws by name. These tests run the surfaces' own functions under node, wired by js/main.ts's own registration
(js_seams_wired) with recording stand-ins under the names it registers, and hold that each call reaches the feature at
the point it stood, with the same arguments, its answer used the same way, and in the same order among its neighbours.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_surface_seams.py
"""

import json
import unittest

from helpers import extract_js_fn, js_seams_wired, run_node
from helpers_notices import node_or_skip

PAGE_SEAMS = "pdf/state-seams.ts"
LINE_SEAMS = "markdown/state-seams.ts"

# Recording stand-ins under the names js/main.ts registers for the page surface's seams: the pins' marks
# (pins/flow-list.ts), the verdict (verdict/flow-reason.ts, verdict/flow-line.ts), the composer
# (composer/flow-pick.ts, composer/view-selection-popover.ts), the Markdown surface (markdown/view.ts) and the changes
# view (revisions/flow.ts).
PAGE_FEATURES = r"""
const LOG=[];
function marks(){LOG.push(['marks']);}
function markBadgeSides(){LOG.push(['placeBadges']);}
const HELD={sid:1};
function holdReasonFocus(){LOG.push(['holdReasonFocus']); return HELD;}
function restoreReasonFocus(held){LOG.push(['restoreReasonFocus',held===HELD]);}
function sizePageLines(){LOG.push(['sizeLines']);}
function pageVerdictPins(){LOG.push(['pagePins']); return new Map([[2,[{id:7,verdict:'ok'}]]]);}
function pick(region){LOG.push(['pick',region.page,region.doc]); return Promise.resolve();}
function discardSelection(){LOG.push(['discard']);}
function openSelectionPopover(box){LOG.push(['openPopover',box.id]);}
let POPOVER_OPEN=false; function isSelectionPopoverOpen(){LOG.push(['popoverOpen']); return POPOVER_OPEN;}
const SELECTION_POPOVER={id:'pop',getBoundingClientRect:()=>({left:0,top:0,right:10,bottom:10})};
let SELECTION_POPOVER_BOX=null;
function placeSelectionPopover(){LOG.push(['placePopover']);}
const MARKDOWN_VIEW={gen:3,shown:'a'};
function buildMarkdownDoc(){LOG.push(['markdownBuild']);}
function goToHeading(index){LOG.push(['goToHeading',index]);}
function updateMarkdownStrip(){LOG.push(['updateStrip']);}
function setViewMode(mode){LOG.push(['setMode',mode]);}
"""


def run(*parts: str) -> object:
    """parts joined after the stand-ins and the wiring; the script prints its result as JSON."""
    return json.loads(run_node("\n".join([PAGE_FEATURES, js_seams_wired(PAGE_SEAMS), *parts])))


class DrawingThePages(unittest.TestCase):
    """buildDoc draws the pages between the reason field's hold and its return, the pins' marks right after the page
    widths; setScale and autoFitWidth place the badges, then size the verdict lines."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    BUILD = r"""
    let MD=false,META={pages:[{pt_w:600,pt_h:800},{pt_w:600,pt_h:800}]},PAGE_SCALE=1; const COMPOSE={box:{}};
    const document={body:{classList:{remove(c){LOG.push(['bodyRemove',c,MARKDOWN_VIEW.gen,MARKDOWN_VIEW.shown]);}}},
      createElement:()=>({dataset:{},style:{},appendChild(){}})};
    const DOC={replaceChildren(){LOG.push(['clear']);},appendChild(){}};
    function $(sel){return DOC;} function isMarkdownDoc(){return MD;}
    function setHtml(){} function html(){return '';} function pageWidth(){return 600;} function pageSrc(){return '';}
    function pageWidthVars(){LOG.push(['widthVars']);} function observeVectorPages(){LOG.push(['observe']);}
    function drawZoom(){LOG.push(['drawZoom']);}
    """

    def test_a_pdf_document_is_drawn_between_the_reason_fields_hold_and_return(self):
        """The Markdown surface's draw generation goes up and its shown document is cleared before the body loses
        md-surface; the reason field is held before the pages are cleared, the marks follow the page widths, and the
        held focus comes back last."""
        got = run(self.BUILD, extract_js_fn("buildDoc"), "buildDoc(); console.log(JSON.stringify(LOG));")
        self.assertEqual(
            got,
            [
                ["bodyRemove", "md-surface", 4, ""],
                ["holdReasonFocus"],
                ["clear"],
                ["widthVars"],
                ["marks"],
                ["observe"],
                ["drawZoom"],
                ["restoreReasonFocus", True],
            ],
        )

    def test_a_document_drawn_from_its_source_goes_to_the_markdown_surface_alone(self):
        got = run(
            self.BUILD,
            extract_js_fn("buildDoc"),
            "MD=true; buildDoc(); console.log(JSON.stringify([LOG,COMPOSE.box,MARKDOWN_VIEW.gen]));",
        )
        self.assertEqual(got, [[["markdownBuild"]], None, 3])

    def test_a_scale_places_the_badges_then_sizes_the_verdict_lines(self):
        """Between sizing the pages and placing the chips; a fit that keeps the scale only places the badges."""
        got = run(
            r"""
            let PAGE_SCALE=1,SCALE_UNBOUNDED=true,LAYOUT='mid',ZOOMED=true; var LAYOUT_MODE={WIDE:'wide'}; const POINT_PX=1;
            function widestPagePoints(){return 600;} function widthBounds(){return [0,1e9];} function fitWidth(){return 0;}
            function setPageScale(v){PAGE_SCALE=v;} function sizePages(){LOG.push(['sizePages']);}
            function placeChips(){LOG.push(['placeChips']);} function saveScale(){} function invalidateVectorDraws(){}
            function drawZoom(){} function savedScale(){return null;} function defaultScale(){return 1;}
            const LEFT={getClientRects:()=>[1]}; function $(){return LEFT;}
            """,
            extract_js_fn("setScale"),
            extract_js_fn("autoFitWidth"),
            "setScale(1.5); LOG.push(['--']); autoFitWidth(); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(got, [["sizePages"], ["placeBadges"], ["sizeLines"], ["placeChips"], ["--"], ["placeBadges"]])


class GoingToAPlace(unittest.TestCase):
    """The page field, the page list and the outline leave the changes view before they go to a page; the outline and
    the section strip of a document drawn from its source are the Markdown surface's."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    PLACES = r"""
    let OPEN=false,MD=false,META={pages:[{},{},{}]};
    const document={body:{classList:{contains:(c)=>c==='revision-open'&&OPEN}}};
    var VIEW_MODE={MANUSCRIPT:'manuscript',REVISIONS:'revisions'};
    const ELS={'#ns-page-in':{value:'2'},'#nav-sheet':{close(){LOG.push(['closeSheet']);}}}; function $(s){return ELS[s];}
    function clampPage(v){return +v;} function goPage(page){LOG.push(['goPage',page]);}
    function closePageList(back){LOG.push(['closePageList',back]);} function isMarkdownDoc(){return MD;}
    """

    def test_the_page_field_and_the_page_list_leave_the_changes_view_only_while_it_shows(self):
        got = run(
            self.PLACES,
            extract_js_fn("goSheetPage"),
            extract_js_fn("goListedPage"),
            "goSheetPage(); goListedPage(3); OPEN=true; LOG.push(['--']); goSheetPage(); goListedPage(3);"
            "console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(
            got,
            [
                ["closeSheet"],
                ["goPage", 2],
                ["closePageList", True],
                ["goPage", 3],
                ["--"],
                ["closeSheet"],
                ["setMode", "manuscript"],
                ["goPage", 2],
                ["closePageList", True],
                ["setMode", "manuscript"],
                ["goPage", 3],
            ],
        )

    def test_an_outline_pick_marks_its_section_then_leaves_the_changes_view_before_going(self):
        """A heading of a drawn document goes to the Markdown surface; a PDF entry marks the outline and the strip,
        then shows the manuscript, then goes to its page."""
        got = run(
            self.PLACES,
            r"""
            const OUTLINE_ENTRIES=[{page:2}]; let OUTLINE_SELECTED=-1,OUTLINE_ACTIVE_PAGE=0,OUTLINE_PINNED=null;
            function outlinePickWait(){} function markOutline(){LOG.push(['markOutline']);}
            function updateSectionStrip(){LOG.push(['strip']);} function outlinePickTop(){LOG.push(['top']); return null;}
            """,
            extract_js_fn("pickOutline"),
            "MD=true; pickOutline(4); MD=false; LOG.push(['--']); pickOutline(0); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(
            got,
            [["goToHeading", 4], ["--"], ["markOutline"], ["strip"], ["setMode", "manuscript"], ["top"], ["goPage", 2]],
        )

    def test_the_section_strip_of_a_drawn_document_is_the_markdown_surfaces(self):
        got = run(
            "let MD=true; function isMarkdownDoc(){return MD;}",
            extract_js_fn("updateSectionStrip"),
            "updateSectionStrip(); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(got, [["updateStrip"]])

    def test_the_page_rows_ask_for_the_verdict_pins_only_while_page_lines_are_drawn(self):
        """pageRowsHtml reads each page's verdict pins once, when the document's words draw page lines, and names the
        page's newest verdict pin on its row."""
        got = run(
            r"""
            let LINES=null; function pageVerdictsOn(){return LINES;} function pageNames(){return ['','',''];}
            function verdictOf(pin){return pin.verdict;} function verdictLabel(key){return '['+key+']';}
            function lucideIcon(){return '';}
            function html(strings,...values){return strings.reduce((out,s,i)=>out+s+(i<values.length?[].concat(values[i]).join(''):''),'');}
            """,
            extract_js_fn("pageRowsHtml"),
            "const off=pageRowsHtml(3,1); LINES={page:true}; const on=pageRowsHtml(3,1);"
            "console.log(JSON.stringify([LOG,off.includes('#7'),on.includes('#7 <span translate=\"no\">[ok]')]));",
        )
        self.assertEqual(got, [[["pagePins"]], False, True])


class HandingTheSelection(unittest.TestCase):
    """A drag on the pages goes to the composer, its popover opens after the pick, and a click off or a press outside
    reads the popover through the seam."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    SELECTION = r"""
    let DOC='a',META={pages:[{pt_w:100,pt_h:200}],pages_build:'b1'},REPICK=null,REPLY=null,SWALLOW_CLICK=0;
    const COMPOSE={box:null,current:{}},EDITOR={current:null};
    const ELS={'#composer':{hidden:false},'#left':{clientWidth:500,clientHeight:500}}; function $(s){return ELS[s];}
    function drawBox(){} function pendingBadge(){}
    function isMarkdownDoc(){return false;} function hitsAny(rects){LOG.push(['rects',rects.length]); return false;}
    const document={querySelectorAll:()=>[]};
    """

    def test_a_drag_picks_its_region_then_opens_the_popover_unless_it_replaces_a_pin(self):
        got = run(
            self.SELECTION,
            # the boxes drawn beside the selection's own, which a new drag takes off (pdf/input-selection.ts)
            extract_js_fn("selectionParts"),
            extract_js_fn("clearSelectionParts"),
            extract_js_fn("finishRect"),
            r"""
            const page={dataset:{page:'1'}}, box=()=>({id:'box',classList:{add(){}},remove(){}});
            finishRect(page,box(),0,0,0.5,0.5); LOG.push(['--']);
            REPICK={}; finishRect(page,box(),0,0,0.5,0.5); console.log(JSON.stringify(LOG));
            """,
        )
        self.assertEqual(got, [["pick", 1, "a"], ["openPopover", "box"], ["--"], ["pick", 1, "a"]])

    def test_a_click_off_its_box_drops_the_selection_before_swallowing_the_next_click(self):
        got = run(
            self.SELECTION,
            extract_js_fn("selectionOpen"),
            extract_js_fn("clickOffNow"),
            "function discardSelection(){LOG.push(['discard',SWALLOW_CLICK]);}"
            "const box={}; COMPOSE.box=box; clickOffNow({}); clickOffNow(box);"
            "console.log(JSON.stringify([LOG,SWALLOW_CLICK>0]));",
        )
        self.assertEqual(got, [[["discard", 0]], True])

    def test_a_press_outside_counts_the_popover_only_while_it_shows(self):
        got = run(
            self.SELECTION,
            extract_js_fn("selectionOpen"),
            extract_js_fn("pressOutsideSelection"),
            r"""
            const press={target:{closest:()=>null},offsetX:1,offsetY:1,clientX:1,clientY:1};
            pressOutsideSelection(press); POPOVER_OPEN=true; pressOutsideSelection(press); console.log(JSON.stringify(LOG));
            """,
        )
        self.assertEqual(got, [["popoverOpen"], ["rects", 0], ["popoverOpen"], ["rects", 1]])

    def test_the_search_brings_the_popovers_box_back_only_when_the_popover_held_the_focus(self):
        """searchBringBack reads the popover's box once the popover is known to hold `to`, scrolls, then places the
        popover again; a field of the composer is scrolled into view instead."""
        got = run(
            r"""
            const AREA={left:0,top:0,right:100,bottom:100};
            function popoverFreeArea(){return AREA;} function endJumpForScroll(){LOG.push(['endJump']);}
            const LEFT={scrollTop:0,scrollLeft:0}; let IN_POP=true;
            const ELS={'#left':LEFT,'#sel-pop':{contains:()=>IN_POP},'#composer':{contains:()=>true}}; function $(s){return ELS[s];}
            const to={scrollIntoView(){LOG.push(['scrollIntoView']);}};
            """,
            extract_js_fn("searchBringBack"),
            r"""
            SELECTION_POPOVER_BOX={getBoundingClientRect:()=>({left:10,right:20,top:300,bottom:310})};
            searchBringBack(to); LOG.push(['--',LEFT.scrollTop]); IN_POP=false; searchBringBack(to);
            console.log(JSON.stringify(LOG));
            """,
        )
        self.assertEqual(got, [["endJump"], ["placePopover"], ["--", 270], ["scrollIntoView"]])


# Recording stand-ins under the names js/main.ts registers for the Markdown surface's seams: the text surface
# (text/view.ts), what a pick of lines fills (composer/flow-repick.ts, composer/flow-pick.ts, verdict/flow-line.ts) and
# the pins' marks (pins/flow-list.ts).
LINE_FEATURES = r"""
const LOG=[];
const TEXT_RUNGS=[{level:'raw'}];
function buildTextView(stale,ends){LOG.push(['textBuild',typeof stale,ends]); return Promise.resolve(null);}
function textLevels(range){LOG.push(['textLevels',range.lo,range.hi]); return TEXT_RUNGS;}
function bannerCompare(){LOG.push(['compare']);}
function setBusy(on){LOG.push(['setBusy',on]);}
function renderComposer(){LOG.push(['renderComposer']);}
function renderVerdictRow(){LOG.push(['renderVerdictRow']);}
function marks(){LOG.push(['marks']);}
"""


def run_lines(*parts: str) -> object:
    """parts joined after the Markdown surface's stand-ins and the wiring; the script prints its result as JSON."""
    return json.loads(run_node("\n".join([LINE_FEATURES, js_seams_wired(LINE_SEAMS), *parts])))


class PickingLines(unittest.TestCase):
    """A pick of lines fills the re-placing banner or the composer and its verdict row through linePick; a text
    document's ladder is the text surface's."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    # what pickLines reads and calls besides the seams, after the served function (whose setters these replace)
    PICK = r"""
    let DOC='a',REPICK=null,PICKSEQ=0,LAYOUT='wide',LAST_POINTER='touch',PINS=[]; var LAYOUT_MODE={WIDE:'wide'};
    const MARKDOWN_VIEW={heads:[],file:'a.md',name:'a.md',lines:['x','y']}; const COMPOSE={intent:0};
    const ELS={}; function $(s){return ELS[s]||(ELS[s]={hidden:true,scrollTop:1,focus(){}});}
    const document={querySelector:()=>null};
    function isTextDoc(){return false;} function markdownLevels(){return [];} function levelOf(){return null;}
    function lineSnippet(){return '';} function endTopic(){} function setPickseq(v){PICKSEQ=v;}
    function useLevel(){LOG.push(['useLevel']);} function setSide(){LOG.push(['setSide']);} function applySide(){}
    function overlapsFor(){return [];} function setSnipOpen(){LOG.push(['setSnipOpen']);}
    function revealBox(){LOG.push(['revealBox']);}
    """

    def test_a_pick_while_replacing_a_pin_only_redraws_the_comparison(self):
        got = run_lines(
            extract_js_fn("pickLines"),
            self.PICK,
            "REPICK={}; pickLines({lo:1,hi:2},null,null,'',false);console.log(JSON.stringify([LOG,REPICK.cand.lo]));",
        )
        self.assertEqual(got, [[["compare"]], 1])

    def test_a_pick_opens_the_composer_then_draws_it_and_its_verdict_row(self):
        """The composer is shown and set not busy after the level is used; it is drawn, then the verdict row, after
        the snippet folds and before the selection is revealed."""
        got = run_lines(
            extract_js_fn("pickLines"),
            self.PICK,
            "pickLines({lo:1,hi:2},null,null,'q',false); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(
            got,
            [
                ["useLevel"],
                ["setBusy", False],
                ["setSide"],
                ["setSnipOpen"],
                ["renderComposer"],
                ["renderVerdictRow"],
                ["revealBox"],
            ],
        )

    def test_a_text_documents_ladder_is_the_text_surfaces_answer(self):
        got = run_lines(
            "function isTextDoc(){return true;}",
            extract_js_fn("markdownLevels"),
            "const rungs=markdownLevels({lo:3,hi:4},null,null); console.log(JSON.stringify([LOG,rungs===TEXT_RUNGS]));",
        )
        self.assertEqual(got, [[["textLevels", 3, 4]], True])

    def test_a_pick_from_the_drawn_document_takes_the_line_views_ladder_and_redraws_the_composer(self):
        """relevelForLineView sets the raw ladder, uses it, then draws the composer."""
        got = run_lines(
            r"""
            let DOC='a',REPICK=null; const MARKDOWN_VIEW={file:'a.md'};
            const COMPOSE={current:{doc:'a',file:'a.md',lo:2,hi:3,levels:[{level:'block',lo:1,hi:4}]}};
            function isRegion(){return false;} function $(){return {};}
            function markdownLevels(){return [{level:'raw',lo:2,hi:3}];} function useLevel(s,l){LOG.push(['useLevel',l]);}
            """,
            extract_js_fn("relevelForLineView"),
            "relevelForLineView(); console.log(JSON.stringify([LOG,COMPOSE.current.default_level]));",
        )
        self.assertEqual(got, [[["useLevel", "raw"], ["renderComposer"]], "raw"])


class DrawingTheLines(unittest.TestCase):
    """A text document's lines are the text surface's view, shown once it is drawn and not stale; showDocumentNode
    draws the pins' marks after the outline and before the line view's ladder."""

    def setUp(self):
        """Skip without node."""
        node_or_skip(self)

    def test_a_text_document_is_drawn_by_the_text_surface_then_shown_and_compared(self):
        """buildMarkdownDoc hands the text surface its staleness check and the source's line ends, then shows the view
        it answers and compares the redrawn source; a draw that went stale while the view was built shows nothing."""
        got = run_lines(
            r"""
            let DOC='a',GONE=false; const MARKDOWN_VIEW={gen:0,shown:'',doc:null,mtime:null,asked:null,lines:[],heads:[]};
            var MARKDOWN_LIMITS={lines:100};
            const DOCROOT={querySelector:()=>null,replaceChildren(){}}; function $(){return DOCROOT;}
            const document={body:{classList:{add(){}}}};
            function isFieldBusy(){return false;} function isMarkdownDoc(){return true;} function isTextDoc(){return true;}
            function withDocQuery(u){return u;} function waitLine(){return {};}
            function api(){return Promise.resolve({status:200,data:{src_mtime:5,file:'a.txt',lines:['x'],line_ends:{crlf:1}}});}
            const VIEW={id:'view'};
            function buildTextView(stale,ends){LOG.push(['textBuild',typeof stale,ends.crlf]); if(GONE)DOC='b'; return Promise.resolve(VIEW);}
            function showDocumentNode(node){LOG.push(['show',node.id]);}
            function compareRedrawnSource(doc){LOG.push(['compare',doc]);}
            """,
            extract_js_fn("buildMarkdownDoc"),
            "(async()=>{await buildMarkdownDoc(); LOG.push(['--']); GONE=true; await buildMarkdownDoc();"
            "console.log(JSON.stringify(LOG));})();",
        )
        self.assertEqual(
            got,
            [["textBuild", "function", 1], ["show", "view"], ["compare", "a"], ["--"], ["textBuild", "function", 1]],
        )

    def test_the_marks_come_after_the_outline_and_before_the_ladder(self):
        got = run_lines(
            r"""
            let DOC='a',SWITCHSEQ=1,COLUMN_OBSERVER=null;
            const MARKDOWN_VIEW={want:null,shown:'a',spot:null,jumpTo:null,headTo:null};
            const DOCROOT={replaceChildren(){LOG.push(['replace']);}}; function $(){return DOCROOT;}
            function isColumnShown(){return true;} function readingAnchor(){return null;}
            function fitWideFormulas(){} function restoreReadingAnchor(){} function drawOutline(){LOG.push(['outline']);}
            function relevelForLineView(){LOG.push(['relevel']);} function markChosenLines(){} function shownChoice(){}
            function updateMarkdownStrip(){LOG.push(['strip']);} function readSpot(){} function tintChangedLines(){}
            """,
            extract_js_fn("showDocumentNode"),
            "showDocumentNode({dataset:{}}); console.log(JSON.stringify(LOG));",
        )
        self.assertEqual(got, [["replace"], ["outline"], ["marks"], ["relevel"], ["strip"]])


if __name__ == "__main__":
    unittest.main()
