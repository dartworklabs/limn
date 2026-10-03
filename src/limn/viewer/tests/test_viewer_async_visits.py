"""Keep delayed viewer requests from changing a later document visit."""

import json
import shutil
import unittest

from helpers import extract_js_fn, run_node


class AsyncDocumentVisits(unittest.TestCase):
    """A response belongs to the document visit that sent its request."""

    def setUp(self):
        """Require Node to resolve the real viewer functions in a controlled order."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_rebuild_response_does_not_change_another_documents_panel(self):
        """A rebuild started on A cannot hide B's error or poll B when its POST finishes late."""
        js = "\n".join(
            [
                extract_js_fn("dq"),
                extract_js_fn("rebuild"),
                """
                let DOC='a',SWITCHSEQ=1; const BUILD={inflight:null};
                const nodes=new Map(),calls=[];
                let finish;
                function $(name){if(!nodes.has(name))nodes.set(name,{hidden:false});return nodes.get(name);}
                function api(url){calls.push(url);return new Promise(resolve=>{finish=resolve;});}
                function pollBuild(){calls.push('poll:'+DOC);}
                function toast(){calls.push('toast');}
                (async()=>{
                  const old=rebuild();DOC='b';SWITCHSEQ++;
                  finish({status:200});await old;
                  console.log(JSON.stringify({hidden:$('#build-err').hidden,calls}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {"hidden": False, "calls": ["/api/rebuild?async=1&doc=a"]},
        )

    def test_old_light_poll_failure_keeps_current_connection_status(self):
        """A failed poll from A cannot mark B disconnected after the user switches."""
        js = "\n".join(
            [
                extract_js_fn("pollLightOnce"),
                """
                let DOC='a',SWITCHSEQ=1,POLL_FAILS=1;
                const lost={hidden:true};
                let fail;
                function dq(path){return path;}function notifyQuery(){return '';}
                function api(){return new Promise((resolve,reject)=>{fail=reject;});}
                function $(name){return lost;}
                (async()=>{
                  const old=pollLightOnce();DOC='b';SWITCHSEQ++;
                  fail(Error('offline'));await old;
                  console.log(JSON.stringify({hidden:lost.hidden,fails:POLL_FAILS}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"hidden": True, "fails": 1})

    def test_rebuild_wait_does_not_poll_after_document_switch(self):
        """A rebuild waiting for an earlier build poll cannot poll a document opened meanwhile."""
        js = "\n".join(
            [
                extract_js_fn("dq"),
                extract_js_fn("rebuild"),
                """
                let DOC='a',SWITCHSEQ=1;
                let release;
                const calls=[];
                const BUILD={inflight:new Promise(resolve=>{release=resolve;})};
                function $(name){return {hidden:false};}
                function api(url){calls.push(url);return Promise.resolve({status:200});}
                function pollBuild(){calls.push('poll:'+DOC);}
                (async()=>{
                  const old=rebuild();await Promise.resolve();
                  DOC='b';SWITCHSEQ++;release();await old;
                  console.log(JSON.stringify(calls));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), ["/api/rebuild?async=1&doc=a"])

    def test_old_light_poll_success_keeps_current_connection_status(self):
        """A successful old poll cannot clear the current document's disconnected banner."""
        js = "\n".join(
            [
                extract_js_fn("pollLightOnce"),
                """
                let DOC='a',SWITCHSEQ=1,POLL_FAILS=2;
                const lost={hidden:false};
                let finish;
                function dq(path){return path;}function notifyQuery(){return '';}
                function api(){return new Promise(resolve=>{finish=resolve;});}
                function $(name){return lost;}
                function notifyHandle(){}
                (async()=>{
                  const old=pollLightOnce();DOC='b';SWITCHSEQ++;
                  finish({data:{}});await old;
                  console.log(JSON.stringify({hidden:lost.hidden,fails:POLL_FAILS}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"hidden": False, "fails": 2})


class VisitLocalContinuations(unittest.TestCase):
    """Completed requests keep their server effects while leaving a later visit's local UI alone."""

    def setUp(self):
        """Require Node to control promise and timer completion order."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _save_result(self, scenario):
        """Run the real save continuation with a controlled POST and observable local effects."""
        js = "\n".join(
            [
                extract_js_fn("captureVisit"),
                extract_js_fn("currentVisit"),
                extract_js_fn("composeOwns"),
                extract_js_fn("savePin"),
                """
                let DOC='a',SWITCHSEQ=1; const COMPOSE={current:{doc:'a',file:'a.tex',page:1,lo:1,hi:1},box:{remove(){removes++;}},saving:false,picking:false};
                let KIND_NEW='fix',PINS=[],removes=0,clears=0,drafts=0,loads=0,drops=0,restores=0;
                const SEC_SEEN={open:new Set()},ASSIGN_NEW={v:'agent'};
                let finish,undo;
                function $(name){return name==='#note'?{value:'note'}:{disabled:false};}
                function isRegion(){return false;}function kindFor(){return 'line';}function figureFields(b){return b;}function figRung(){return null;}
                function mentionHints(){return [];}function renderAssignNew(){}
                function selectionSnapshot(){return {};}
                function cancelSelection(){clears++;COMPOSE.current=null;}
                function syncDraft(){drafts++;}
                function savedDraftSnapshot(){return null;} function restoredDraftOwns(){return false;} function clearSavedDraft(){}
                function restoreSelection(){restores++;}
                function dropPin(){drops++;}
                function tl(s){return s;}function toast(msg,type,action){undo=action.fn;}
                function loadPins(){loads++;return Promise.resolve();}
                function api(){return new Promise(resolve=>{finish=resolve;});}
                """,
                scenario,
            ]
        )
        return json.loads(run_node(js))

    def test_saved_pin_does_not_clear_a_later_visits_selection(self):
        """A saved pin refreshes all pins but leaves a new document's composer and draft untouched."""
        result = self._save_result(
            """
            (async()=>{
              const old=savePin();DOC='b';SWITCHSEQ++;
              COMPOSE.current={doc:'b',file:'b.tex',page:2};COMPOSE.box={remove(){removes++;}};
              finish({data:{id:8}});await old;undo();
              console.log(JSON.stringify({doc:COMPOSE.current.doc,pending:!!COMPOSE.box,removes,clears,drafts,loads,drops,restores}));
            })();
            """
        )
        self.assertEqual(
            result,
            {
                "doc": "b",
                "pending": True,
                "removes": 0,
                "clears": 0,
                "drafts": 0,
                "loads": 1,
                "drops": 1,
                "restores": 0,
            },
        )

    def test_saved_pin_does_not_clear_or_restore_new_selection_in_same_visit(self):
        """Save completion and undo affect the saved pin but leave a newer selection in the same document intact."""
        result = self._save_result(
            """
            (async()=>{
              const old=savePin();COMPOSE.current={doc:'a',newSelection:true};COMPOSE.box={remove(){removes++;}};
              finish({data:{id:8}});await old;undo();
              console.log(JSON.stringify({newSelection:COMPOSE.current.newSelection,pending:!!COMPOSE.box,removes,clears,drafts,loads,drops,restores}));
            })();
            """
        )
        self.assertEqual(
            result,
            {
                "newSelection": True,
                "pending": True,
                "removes": 0,
                "clears": 0,
                "drafts": 0,
                "loads": 1,
                "drops": 1,
                "restores": 0,
            },
        )

    def test_saved_pin_does_not_remove_new_pending_box(self):
        """A replacement drag box belongs to the newer selection even before its pick updates COMPOSE.current."""
        result = self._save_result(
            """
            (async()=>{
              const old=savePin();COMPOSE.box={newBox:true,remove(){removes++;}};
              finish({data:{id:8}});await old;undo();
              console.log(JSON.stringify({newBox:COMPOSE.box.newBox,removes,clears,drafts,loads,drops,restores}));
            })();
            """
        )
        self.assertEqual(
            result,
            {"newBox": True, "removes": 0, "clears": 0, "drafts": 0, "loads": 1, "drops": 1, "restores": 0},
        )

    def test_append_response_does_not_clear_a_new_selection(self):
        """An append still announces and refreshes its pin while preserving a selection made during the POST."""
        js = "\n".join(
            [
                extract_js_fn("captureVisit"),
                extract_js_fn("currentVisit"),
                extract_js_fn("composeOwns"),
                extract_js_fn("appendToPin"),
                """
                let DOC='a',SWITCHSEQ=1,PINS=[{id:7,note:'old'}]; const COMPOSE={current:{doc:'a'},box:{remove(){removed++;}}};
                let finish,removed=0,cleared=0,toasts=0,loads=0;
                function api(){return new Promise(resolve=>{finish=resolve;});}
                function cancelSelection(){cleared++;COMPOSE.current=null;}
                function syncDraft(){} function savedDraftSnapshot(){return null;}
                function restoredDraftOwns(){return false;} function clearSavedDraft(){}
                function toast(){toasts++;}function tl(s){return s;}
                function loadPins(){loads++;return Promise.resolve();}
                function undoAppend(){}
                (async()=>{
                  const old=appendToPin(7,'new');COMPOSE.current={doc:'a',newSelection:true};
                  COMPOSE.box={remove(){removed++;}};
                  finish({data:{pin:{rev:2}}});await old;
                  console.log(JSON.stringify({newSelection:COMPOSE.current.newSelection,pending:!!COMPOSE.box,removed,cleared,toasts,loads}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {"newSelection": True, "pending": True, "removed": 0, "cleared": 0, "toasts": 1, "loads": 1},
        )

    def test_failed_drop_restores_global_pin_without_restoring_old_document_rows(self):
        """A failed optimistic delete restores the pin globally and derives the active document's rows."""
        js = "\n".join(
            [
                extract_js_fn("captureVisit"),
                extract_js_fn("currentVisit"),
                extract_js_fn("dropPin"),
                """
                let DOC='a',SWITCHSEQ=1,PINS_APPLIED_SEQ=0,OPEN_ALL=[{id:1,doc:'a'},{id:2,doc:'b'}],PINS=[OPEN_ALL[0]]; const EDITOR={current:null,saving:false};
                let fail,draws=0,marksCount=0,loads=0;
                function pdoc(p){return p.doc;}
                function drawPins(){draws++;}function marks(){marksCount++;}
                function api(){return new Promise((resolve,reject)=>{fail=reject;});}
                function loadPins(){loads++;return Promise.resolve(false);}
                (async()=>{
                  const old=dropPin(1,false);DOC='b';SWITCHSEQ++;PINS=[OPEN_ALL[0]];
                  fail(Error('offline'));await old;
                  console.log(JSON.stringify({all:OPEN_ALL.map(p=>p.id),here:PINS.map(p=>p.id),loads}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"all": [1, 2], "here": [2], "loads": 1})

    def test_failed_drop_restores_only_its_pin_when_another_drop_is_pending(self):
        """A failed optimistic delete leaves a concurrent successful delete hidden if refresh fails."""
        js = "\n".join(
            [
                extract_js_fn("dropPin"),
                """
                let DOC='a',PINS_APPLIED_SEQ=0;
                let OPEN_ALL=[{id:1,doc:'a'},{id:2,doc:'a'},{id:3,doc:'a'}],PINS=OPEN_ALL; const EDITOR={current:null,saving:false};
                const pending={};let loads=0;
                function pdoc(p){return p.doc;}
                function drawPins(){}function marks(){}function markMine(){}
                function tl(s){return s;}function toast(){}function restorePin(){}
                function api(url){const id=Number(url.split('/')[3]);return new Promise((resolve,reject)=>{pending[id]={resolve,reject};});}
                function loadPins(){loads++;return Promise.resolve(false);}
                (async()=>{
                  const first=dropPin(1,false),second=dropPin(2,false);
                  pending[1].reject(Error('offline'));await first;
                  const afterFailure=OPEN_ALL.map(p=>p.id);
                  pending[2].resolve({data:{}});await second;
                  console.log(JSON.stringify({afterFailure,all:OPEN_ALL.map(p=>p.id),here:PINS.map(p=>p.id),loads}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {"afterFailure": [1, 3], "all": [1, 3], "here": [1, 3], "loads": 2},
        )

    def test_save_edit_result_does_not_replace_new_editor(self):
        """An edit POST still refreshes pins but cannot close a replacement editor."""
        js = "\n".join(
            [
                extract_js_fn("editorOwns"),
                extract_js_fn("editNote"),
                extract_js_fn("saveEdit"),
                """
                let DOC='a',SWITCHSEQ=1;
                const first={id:1,base_rev:1,lo:1,hi:1,orig:{note:'old',lo:1,hi:1},el:{querySelector(){return {value:'changed'};}}};
                const EDITOR={current:first,saving:false};let finish,loads=0,toasts=0;
                function viewerBlocked(){return false;}
                function mentionHints(){return [];}function toast(){toasts++;}function tl(s){return s;}
                function loadPins(){loads++;return Promise.resolve();}
                function api(){return new Promise(resolve=>{finish=resolve;});}
                (async()=>{
                  const old=saveEdit();EDITOR.current={id:2,newEditor:true};
                  finish({status:200,data:{pin:{id:1}}});await old;
                  console.log(JSON.stringify({id:EDITOR.current.id,newEditor:EDITOR.current.newEditor,loads,toasts,saving:EDITOR.saving}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {"id": 2, "newEditor": True, "loads": 1, "toasts": 1, "saving": False},
        )

    def test_save_edit_conflict_after_document_switch_refreshes_owned_editor(self):
        """A dirty card that survives A→B receives the conflict revision before another save."""
        js = "\n".join(
            [
                extract_js_fn("editorOwns"),
                extract_js_fn("editNote"),
                extract_js_fn("saveEdit"),
                """
                let DOC='a',SWITCHSEQ=1;
                const first={id:1,base_rev:1,lo:1,hi:1,orig:{note:'old',lo:1,hi:1},el:{querySelector(){return {value:'changed'};}}};
                const EDITOR={current:first,saving:false};let finish,loads=0,snips=0,toasts=0;
                function viewerBlocked(){return false;}
                function mentionHints(){return [];}function toast(){toasts++;}
                function loadPins(){loads++;return Promise.resolve();}
                function assigneeOf(){return 'agent';}function editSnip(){snips++;}
                function api(){return new Promise(resolve=>{finish=resolve;});}
                (async()=>{
                  const old=saveEdit();DOC='b';SWITCHSEQ++;
                  finish({status:409,data:{pin:{rev:2,lo:4,hi:5,file:'new.tex',note:'remote'}}});await old;
                  console.log(JSON.stringify({rev:EDITOR.current.base_rev,lo:EDITOR.current.lo,snips,loads,toasts}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"rev": 2, "lo": 4, "snips": 1, "loads": 1, "toasts": 1})

    def test_save_edit_success_after_same_document_revisit_closes_owned_editor(self):
        """A saved card that survives A→B→A closes when its successful POST completes."""
        js = "\n".join(
            [
                extract_js_fn("editorOwns"),
                extract_js_fn("editNote"),
                extract_js_fn("saveEdit"),
                """
                let DOC='a',SWITCHSEQ=1;
                const card={id:1,base_rev:1,lo:1,hi:1,orig:{note:'old',lo:1,hi:1},el:{querySelector(){return {value:'changed'};}}};
                const EDITOR={current:card,saving:false};let finish,loads=0,toasts=0;
                function viewerBlocked(){return false;}
                function mentionHints(){return [];}function toast(){toasts++;}function tl(s){return s;}
                function loadPins(){loads++;return Promise.resolve();}
                function api(){return new Promise(resolve=>{finish=resolve;});}
                (async()=>{
                  const old=saveEdit();DOC='b';SWITCHSEQ++;DOC='a';SWITCHSEQ++;
                  finish({status:200,data:{pin:{id:1}}});await old;
                  console.log(JSON.stringify({kept:EDITOR.current===card,loads,toasts,saving:EDITOR.saving}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"kept": False, "loads": 1, "toasts": 1, "saving": False})

    def test_repick_result_does_not_cancel_new_repick(self):
        """A completed location change keeps global feedback and leaves a later repick in place."""
        js = "\n".join(
            [
                extract_js_fn("captureVisit"),
                extract_js_fn("currentVisit"),
                extract_js_fn("applyRepick"),
                """
                let DOC='a',SWITCHSEQ=1;
                const prior={id:1,cand:{file:'a.tex',page:1,lo:2,hi:3,kind:'line'}};
                let REPICK=prior,finish,loads=0,toasts=0,cancels=0,snips=0;
                const EDITOR={current:{id:1,base_rev:1,orig:{lo:1,hi:1}},saving:false};
                function lvOf(){return null;}function isRegion(){return false;}function figureFields(b){return b;}function repickEl(){return null;}function pinPlace(p){return {page:p.page};}
                function tl(s){return s;}function toast(){toasts++;}
                function cancelRepick(){cancels++;REPICK=null;}
                function editSnip(){snips++;}function loadPins(){loads++;return Promise.resolve();}
                function api(){return new Promise(resolve=>{finish=resolve;});}
                (async()=>{
                  const old=applyRepick();REPICK={id:2,cand:{}};EDITOR.current={id:2,base_rev:1};
                  finish({status:200,data:{pin:{id:1,rev:2,lo:2,hi:3,file:'a.tex'}}});await old;
                  console.log(JSON.stringify({repick:REPICK.id,edit:EDITOR.current.id,cancels,snips,loads,toasts}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {"repick": 2, "edit": 2, "cancels": 0, "snips": 0, "loads": 1, "toasts": 1},
        )

    def test_repick_success_toast_names_the_page_the_mark_is_on_now(self):
        """A re-placed figure region whose element the server found on another page is announced with that page (pinPlace),
        not with the page it was first placed on; a pin without a found element keeps its own page."""
        for pin, expected_page in (
            ({"id": 1, "rev": 2, "page": 1, "mark": [0.1, 0.1, 0.2, 0.2], "mark_page": 3}, 3),
            ({"id": 1, "rev": 2, "page": 1}, 1),
        ):
            with self.subTest(pin=pin):
                js = "\n".join(
                    [
                        extract_js_fn("captureVisit"),
                        extract_js_fn("currentVisit"),
                        extract_js_fn("isFrac"),
                        extract_js_fn("hasMark"),
                        extract_js_fn("pinPlace"),
                        extract_js_fn("applyRepick"),
                        """
                        let DOC='a',SWITCHSEQ=1;
                        let REPICK={id:1,cand:{page:1,kind:'region',frac:[0,0,1,1]}};
                        const EDITOR={current:null,saving:false}; const TOASTS=[];
                        function lvOf(){return null;}function isRegion(){return true;}function figureFields(b){return b;}function repickEl(){return null;}
                        function tl(s,v){return s.replace(/\\{(\\w+)\\}/g,(m,k)=>v[k]);}function toast(m,k){TOASTS.push(m);}
                        function cancelRepick(){REPICK=null;}function editSnip(){}function loadPins(){return Promise.resolve();}
                        function api(){return Promise.resolve({status:200,data:{pin:PIN}});}
                        (async()=>{await applyRepick(); console.log(JSON.stringify(TOASTS));})();
                        """.replace("PIN", json.dumps(pin)),
                    ]
                )
                self.assertEqual(json.loads(run_node(js)), [f"핀 #1 위치를 쪽 {expected_page} 영역 로 바꿨습니다"])

    def test_repick_reply_updates_the_same_editor_after_document_switch(self):
        """A dirty editor kept across documents receives the relocation revision without reviving its banner."""
        for status, pin, expected_lo, expected_snips in (
            (200, {"id": 1, "rev": 2, "lo": 2, "hi": 3, "file": "a.tex"}, 2, 1),
            (409, {"id": 1, "rev": 2, "lo": 4, "hi": 5, "file": "a.tex"}, 1, 0),
        ):
            with self.subTest(status=status):
                js = "\n".join(
                    [
                        extract_js_fn("captureVisit"),
                        extract_js_fn("currentVisit"),
                        extract_js_fn("applyRepick"),
                        """
                        let DOC='a',SWITCHSEQ=1;
                        const prior={id:1,cand:{file:'a.tex',page:1,lo:2,hi:3,kind:'line'}};
                        let REPICK=prior,finish,loads=0,toasts=0,cancels=0,snips=0;
                        const card={id:1,base_rev:1,lo:1,hi:1,orig:{lo:1,hi:1}};
                        const EDITOR={current:card,saving:false};
                        function lvOf(){return null;}function isRegion(){return false;}function figureFields(b){return b;}function repickEl(){return null;}function pinPlace(p){return {page:p.page};}
                        function tl(s){return s;}function toast(){toasts++;}
                        function cancelRepick(){cancels++;REPICK=null;}
                        function editSnip(){snips++;}function loadPins(){loads++;return Promise.resolve();}
                        function api(){return new Promise(resolve=>{finish=resolve;});}
                        (async()=>{
                          const pending=applyRepick();DOC='b';SWITCHSEQ++;cancelRepick();
                          finish(RESPONSE);await pending;
                          console.log(JSON.stringify({same:EDITOR.current===card,rev:card.base_rev,lo:card.lo,
                            banner:REPICK,cancels,snips,loads,toasts}));
                        })();
                        """.replace("RESPONSE", json.dumps({"status": status, "data": {"pin": pin}})),
                    ]
                )
                self.assertEqual(
                    json.loads(run_node(js)),
                    {
                        "same": True,
                        "rev": 2,
                        "lo": expected_lo,
                        "banner": None,
                        "cancels": 1,
                        "snips": expected_snips,
                        "loads": 1,
                        "toasts": 1,
                    },
                )

    def test_old_snippet_response_cannot_redraw_new_selection(self):
        """A snippet response after a document switch leaves the new selection's text and DOM unchanged."""
        js = "\n".join(
            [
                extract_js_fn("captureVisit"),
                extract_js_fn("currentVisit"),
                extract_js_fn("refetchSnip"),
                """
                let DOC='a',SWITCHSEQ=1,snipT=null; const COMPOSE={current:{doc:'a',file:'a.tex',lo:1,hi:1,snippet:'old'}}; const EDITOR={current:null,saving:false};
                let fire,finish,renders=0;
                function clearTimeout(){}function setTimeout(fn){fire=fn;return 1;}
                function dq(path){return path;}function api(){return new Promise(resolve=>{finish=resolve;});}
                (async()=>{
                  const prior=COMPOSE.current;refetchSnip(prior,()=>{renders++;});
                  const request=fire();DOC='b';SWITCHSEQ++;COMPOSE.current={doc:'b',file:'b.tex',lo:1,hi:1,snippet:'new'};
                  finish({data:{lo:1,hi:1,snippet:'stale'}});await request;
                  console.log(JSON.stringify({old:prior.snippet,current:COMPOSE.current.snippet,renders}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"old": "old", "current": "new", "renders": 0})

    def test_nudged_snippet_updates_a_surviving_editor_after_document_switch(self):
        """A dirty edit card keeps its range snippet when the user switches documents during the read."""
        js = "\n".join(
            [
                extract_js_fn("captureVisit"),
                extract_js_fn("currentVisit"),
                extract_js_fn("refetchSnip"),
                """
                let DOC='a',SWITCHSEQ=1,snipT=null;
                const COMPOSE={current:null};
                const card={doc:'a',file:'a.tex',lo:2,hi:3,snippet:'old'};
                const EDITOR={current:card,saving:false};
                let fire,finish,renders=0;
                function clearTimeout(){}function setTimeout(fn){fire=fn;return 1;}
                function dq(path){return path;}
                function api(){return new Promise(resolve=>{finish=resolve;});}
                (async()=>{
                  refetchSnip(card,()=>{renders++;});const request=fire();
                  DOC='b';SWITCHSEQ++;
                  finish({data:{lo:2,hi:3,snippet:'new range'}});await request;
                  console.log(JSON.stringify({same:EDITOR.current===card,snippet:card.snippet,renders}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"same": True, "snippet": "new range", "renders": 1})

    def test_revision_import_finishing_after_switch_does_not_start_pdf(self):
        """A late PDF.js module import cannot attach a loading task to another document's revision view."""
        source = extract_js_fn("loadRevisionPdf").replace(
            "await import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V)", "await delayedImport()"
        )
        js = "\n".join(
            [
                source,
                """
                let DOC='a';const REV={seq:1,commit:'head',target:null};
                const REV_SCOPE={whole:false,fallback:false},REV_PDF={loading:null};
                const VEC={lib:null},PDFJS_V='test';
                let finishImport,opened=0;
                const statusBox={textContent:''},warningBox={hidden:true,open:false,querySelector(){return {textContent:''};}};
                function $(name){return name==='#revision-status'?statusBox:warningBox;}
                function revisionPinFor(){return null;}
                function revisionCurrent(seq,k,id){return seq===REV.seq&&k===DOC&&id===REV.commit;}
                function api(){return Promise.resolve({data:{state:'ready',head:'head',warnings:[]}});}
                function dq(path){return path;}
                function fetch(){return Promise.resolve({ok:true,arrayBuffer:()=>Promise.resolve(new ArrayBuffer(1))});}
                function delayedImport(){return new Promise(resolve=>{finishImport=resolve;});}
                (async()=>{
                  const old=loadRevisionPdf('head',1,'a');
                  for(let i=0;i<8&&!finishImport;i++)await Promise.resolve();
                  DOC='b';REV.seq++;
                  finishImport({GlobalWorkerOptions:{},getDocument(){opened++;return {promise:Promise.resolve({})};}});
                  await old;console.log(JSON.stringify({opened,loading:REV_PDF.loading}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"opened": 0, "loading": None})
