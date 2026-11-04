"""Execute viewer pin-list decisions and document-scoped request ordering under Node."""

import json
import shutil
import unittest

from helpers import extract_js_fn, js_esc, js_markup, run_node


class PinListLoading(unittest.TestCase):
    """Pin list refreshes keep document partitions and ignore superseded responses."""

    def setUp(self):
        """Require Node to execute the viewer's actual JavaScript source."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_partition_keeps_legacy_pins_in_default_document(self):
        """One pure decision assigns every pin state and scopes legacy records to the default document."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                """
                const rows=[{id:1},{id:2,done:true,review:true},{id:3,done:true,doc:'other'},
                            {id:4,doc:'other',state:'open'}];
                const r=derivePinLists(rows,'main','main');
                console.log(JSON.stringify([r.openAll.map(p=>p.id),r.reviewAll.map(p=>p.id),
                  r.doneAll.map(p=>p.id),r.openHere.map(p=>p.id),r.doneHere.map(p=>p.id)]));
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [[1, 4], [2], [3], [1], []])

    def test_a_confirm_waiting_for_its_undo_stays_out_of_the_review_list(self):
        """A pin whose [확인] waits for its undo (CONFIRMING) is left out of every snapshot's review list, so a poll
        in those six seconds does not bring its card back; the other lists are as they were."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                """
                const rows=[{id:1},{id:2,done:true,review:true},{id:5,done:true,review:true},{id:3,done:true}];
                const r=derivePinLists(rows,'main','main',new Set([2]));
                console.log(JSON.stringify([r.openAll.map(p=>p.id),r.reviewAll.map(p=>p.id),r.doneAll.map(p=>p.id)]));
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [[1], [5], [3]])

    def test_newer_refresh_wins_when_older_trash_request_finishes_last(self):
        """An older response never restores stale rows or says stale transitions after a newer refresh."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                extract_js_fn("applyPinLists"),
                extract_js_fn("loadPins"),
                """
                let DOC='main',DEFAULT_DOC='main',OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[],PINS=[],DONE=[],DROPPED=[];
                let REPLY=null,COMPOSE={current:null},PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0; const CONFIRMING=new Set(),CONFIRMING_PIN=new Map(); const EDITOR={current:null,saving:false};
                const SEC_SEEN={open:null,review:null,done:null},calls=[],reads=[],said=[];
                let firstTrash;
                function api(url){
                  if(url==='/api/pins?all=1')return Promise.resolve({data:reads.shift()});
                  if(url==='/api/pins/dropped'){
                    if(!firstTrash)return new Promise(resolve=>{firstTrash=resolve;});
                    return Promise.resolve({data:{dropped:[]}});
                  }
                  throw Error(url);
                }
                function loadPeople(){} function pdoc(p){return p.doc||DEFAULT_DOC;}
                function notePinChanges(prev,rows){calls.push(['diff',prev.map(p=>p.id),rows.map(p=>p.id)]);}
                function noteReviewChanges(prev,rows){calls.push(['review',prev.map(p=>p.id),rows.map(p=>p.id)]);}
                function lineNote(msg){said.push(msg);} function tl(s){return s;}
                function drawPins(){calls.push(['draw',OPEN_ALL.map(p=>p.id)]);}
                function marks(){} function drawDocTabs(){} function docTitle(){}
                function recomputeOverlap(){} function renderOverlapBanner(){} function closeReply(){}
                reads.push([{id:1}], [{id:2}]);
                const old=loadPins();
                setImmediate(async()=>{
                  const newest=loadPins(); await newest;
                  firstTrash({data:{dropped:[{id:99}]}}); await old;
                  console.log(JSON.stringify({open:OPEN_ALL.map(p=>p.id),dropped:DROPPED.map(p=>p.id),calls,said}));
                });
                """,
            ]
        )
        result = json.loads(run_node(js))
        self.assertEqual(result["open"], [2])
        self.assertEqual(result["dropped"], [])
        self.assertEqual(result["calls"], [["diff", [], [2]], ["review", [], [2]], ["draw", [2]]])
        self.assertEqual(result["said"], [])

    def test_old_pin_response_does_not_fetch_trash_after_newer_refresh(self):
        """A late pin-list response stops before people, Trash, transition notices, or rendering effects."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                extract_js_fn("applyPinLists"),
                extract_js_fn("loadPins"),
                """
                let DOC='main',DEFAULT_DOC='main',OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[],PINS=[],DONE=[],DROPPED=[];
                let REPLY=null,COMPOSE={current:null},PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0; const CONFIRMING=new Set(),CONFIRMING_PIN=new Map(); const EDITOR={current:null,saving:false};
                const SEC_SEEN={open:null,review:null,done:null},calls=[];
                let firstPins,pinReads=0,trashReads=0,peopleReads=0;
                function api(url){
                  if(url==='/api/pins?all=1'){
                    pinReads++;
                    return pinReads===1 ? new Promise(resolve=>{firstPins=resolve;})
                      : Promise.resolve({data:[{id:2}]});
                  }
                  if(url==='/api/pins/dropped'){
                    trashReads++;
                    return Promise.resolve({data:{dropped:[]}});
                  }
                  throw Error(url);
                }
                function loadPeople(){peopleReads++;}
                function notePinChanges(prev,rows){calls.push(['diff',rows.map(p=>p.id)]);}
                function noteReviewChanges(prev,rows){calls.push(['review',rows.map(p=>p.id)]);}
                function drawPins(){calls.push(['draw',OPEN_ALL.map(p=>p.id)]);}
                function marks(){} function drawDocTabs(){} function docTitle(){}
                function recomputeOverlap(){} function renderOverlapBanner(){} function closeReply(){}
                const old=loadPins(),newest=loadPins();
                (async()=>{
                  await newest;
                  firstPins({data:[{id:1}]}); await old;
                  console.log(JSON.stringify({open:OPEN_ALL.map(p=>p.id),peopleReads,trashReads,calls}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {
                "open": [2],
                "peopleReads": 1,
                "trashReads": 1,
                "calls": [["diff", [2]], ["review", [2]], ["draw", [2]]],
            },
        )

    # The served loadPins with a stubbed network and screen. Every pin read waits on the server until the scenario answers
    # it (answer(i, id): read i, in the order asked, gets one pin) or fails it (fail(i)); the Trash answers at once.
    PINS_HARNESS = """
        let DOC='main',SWITCHSEQ=0,DEFAULT_DOC='main',OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[],PINS=[],DONE=[],DROPPED=[];
        let REPLY=null,COMPOSE={current:null},PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0; const CONFIRMING=new Set(),CONFIRMING_PIN=new Map(); const EDITOR={current:null,saving:false};
        const SEC_SEEN={open:null,review:null,done:null},SEC={done:false},OPEN_CARDS=new Set(),drawn=[],pending=[];
        let jumps=0;
        function api(url){
          if(url==='/api/pins?all=1')return new Promise((resolve,reject)=>pending.push({resolve,reject}));
          if(url==='/api/pins/dropped')return Promise.resolve({data:{dropped:[]}});
          throw Error(url);
        }
        const answer=(i,id)=>pending[i].resolve({data:[{id}]}),fail=i=>pending[i].reject(Error('offline'));
        const open=()=>OPEN_ALL.map(p=>p.id);
        function loadPeople(){} function pdoc(p){return p.doc||DEFAULT_DOC;}
        function notePinChanges(){} function noteReviewChanges(){}
        function drawPins(){drawn.push(open());}
        function marks(){} function drawDocTabs(){} function docTitle(){}
        function recomputeOverlap(){} function renderOverlapBanner(){} function closeReply(){}
        function docInfo(){return true;} function isViewer(){return false;} function restorePin(){} function openTrash(){}
        function findAnyPin(id){return OPEN_ALL.concat(REVIEW_ALL,DONE_ALL).find(p=>p.id===id)||null;}
        function setSide(){} function jumpPin(){jumps++;} function jumpToCard(){} function requestAnimationFrame(){}
        """

    def _pins_run(self, scenario, *functions):
        """Run scenario (an async body that prints JSON) against the served pinState, derivePinLists, applyPinLists,
        loadPins and loadPinsNow, and the named functions besides, under PINS_HARNESS; return what it prints, parsed."""
        names = ("pinState", "derivePinLists", "applyPinLists", "loadPins", "loadPinsNow", *functions)
        body = "(async()=>{%s})();" % scenario
        return json.loads(run_node("\n".join([*(extract_js_fn(n) for n in names), self.PINS_HARNESS, body])))

    def test_reading_now_answers_whether_the_list_shows_a_snapshot_asked_since_the_call(self):
        """loadPinsNow resolves true when its own read applied or a newer read that overtook it did, and false when its
        read failed with nothing newer applied - also when an older read, asked before the call, applied while it waited.
        loadPins itself stays false when overtaken: the light poll reads that revision again."""
        cases = {
            "its own read applies": (
                "const now=loadPinsNow(); answer(0,1); console.log(JSON.stringify({now:await now,open:open()}));",
                {"now": True, "open": [1]},
            ),
            "a newer read overtakes it": (
                """const now=loadPinsNow(),newer=loadPins(); answer(1,2); const n=await newer; answer(0,1);
                   console.log(JSON.stringify({now:await now,newer:n,open:open()}));""",
                {"now": True, "newer": True, "open": [2]},
            ),
            "its read fails while an older one applies": (
                """const old=loadPins(),now=loadPinsNow(); answer(0,1); await old; fail(1);
                   console.log(JSON.stringify({now:await now,open:open()}));""",
                {"now": False, "open": [1]},
            ),
            "loadPins, overtaken": (
                """const old=loadPins(),newer=loadPins(); answer(1,2); await newer; answer(0,1);
                   console.log(JSON.stringify({older:await old,open:open()}));""",
                {"older": False, "open": [2]},
            ),
        }
        for name, (scenario, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self._pins_run(scenario), expected)

    def test_a_pin_link_opens_its_card_when_a_newer_read_overtakes_its_own(self):
        """A notification's pin link reads the list again before it opens the pin's card. When a light poll's read, asked
        after the link's, applies first, the link's own read is overtaken - and the list it waited for is there: the card
        opens and the PDF goes to the pin. Before, the link took the overtaken read for a failed one and did nothing."""
        scenario = """
            const link=openPinFromLink('main',7,false);   // its read waits on the server
            const poll=loadPins(); answer(1,7);           // the poll's read, asked after it, is answered first
            const applied=await poll; answer(0,7); await link;
            console.log(JSON.stringify({applied,opened:[...OPEN_CARDS],jumps,drawn}));
            """
        self.assertEqual(
            self._pins_run(scenario, "openPinFromLink"),
            {"applied": True, "opened": [7], "jumps": 1, "drawn": [[7], [7]]},
        )

    def test_failed_newer_poll_keeps_older_success_and_retries_revision(self):
        """A failed newer pin fetch cannot discard an older success or mark its meta revision as loaded."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                extract_js_fn("applyPinLists"),
                extract_js_fn("loadPins"),
                extract_js_fn("pollLightOnce"),
                """
                let DOC='main',SWITCHSEQ=0,DEFAULT_DOC='main',OPEN_ALL=[{id:0}],REVIEW_ALL=[],DONE_ALL=[],PINS=OPEN_ALL,DONE=[],DROPPED=[];
                let REPLY=null,COMPOSE={current:null},PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0; const CONFIRMING=new Set(),CONFIRMING_PIN=new Map(); const EDITOR={current:null,saving:false};
                let LAST_PINS_REV='old',LAST_SRC_MTIME='old-src',POLL_FAILS=0; const BUILD={lastSeq:0,timer:null};
                const SEC_SEEN={open:new Set(),review:new Set(),done:new Set()},drawn=[];
                const document={hidden:false};
                let pinReads=0,firstTrash;
                function api(url){
                  if(url==='/api/pins?all=1'){
                    pinReads++;
                    return pinReads===1 ? Promise.resolve({data:[{id:1}]})
                      : Promise.reject(Error('offline'));
                  }
                  if(url==='/api/pins/dropped')return new Promise(resolve=>{firstTrash=resolve;});
                  if(url==='/api/meta?light=1')return Promise.resolve({data:{pins_rev:'new',src_sig:'new-src',build_seq:0}});
                  throw Error(url);
                }
                function dq(url){return url;} function notifyQuery(){return '';}
                function notifyHandle(){} function updateStaleBadge(){} function updateSyncBadge(){}
                function noteOtherDocs(){} function loadPeople(){} function pollBuild(){}
                function $(sel){return {hidden:true};}
                function notePinChanges(){} function noteReviewChanges(){}
                function drawPins(){drawn.push(OPEN_ALL.map(p=>p.id));}
                function marks(){} function drawDocTabs(){} function docTitle(){}
                function recomputeOverlap(){} function renderOverlapBanner(){} function closeReply(){}
                const old=loadPins();
                setImmediate(async()=>{
                  await pollLightOnce();
                  firstTrash({data:{dropped:[]}}); await old;
                  console.log(JSON.stringify({open:OPEN_ALL.map(p=>p.id),rev:LAST_PINS_REV,
                    src:LAST_SRC_MTIME,drawn}));
                });
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {"open": [1], "rev": "old", "src": "old-src", "drawn": [[1]]},
        )

    def test_failed_trash_read_preserves_snapshot_and_retries_revision(self):
        """A partial pin refresh keeps the old coherent view and retries the same meta revision."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                extract_js_fn("applyPinLists"),
                extract_js_fn("loadPins"),
                extract_js_fn("pollLightOnce"),
                """
                let DOC='main',SWITCHSEQ=0,DEFAULT_DOC='main',OPEN_ALL=[{id:1}],REVIEW_ALL=[],DONE_ALL=[],PINS=OPEN_ALL,DONE=[],DROPPED=[{id:9}];
                let REPLY=null,COMPOSE={current:null},PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0; const CONFIRMING=new Set(),CONFIRMING_PIN=new Map(); const EDITOR={current:null,saving:false};
                let LAST_PINS_REV='old',LAST_SRC_MTIME='old-src',POLL_FAILS=0; const BUILD={lastSeq:0,timer:null};
                const SEC_SEEN={open:new Set(),review:new Set(),done:new Set()},drawn=[];
                const document={hidden:false};let pinReads=0,trashReads=0;
                function api(url){
                  if(url==='/api/meta?light=1')return Promise.resolve({data:{pins_rev:'new',src_sig:'new-src',build_seq:0}});
                  if(url==='/api/pins?all=1'){pinReads++;return Promise.resolve({data:[{id:2}]});}
                  if(url==='/api/pins/dropped'){
                    trashReads++;
                    return trashReads===1?Promise.reject(Error('temporary')):Promise.resolve({data:{dropped:[{id:10}]}});
                  }
                  throw Error(url);
                }
                function dq(url){return url;} function notifyQuery(){return '';}
                function notifyHandle(){} function updateStaleBadge(){} function updateSyncBadge(){}
                function noteOtherDocs(){} function loadPeople(){} function pollBuild(){}
                function $(sel){return {hidden:true};}
                function notePinChanges(){} function noteReviewChanges(){}
                function drawPins(){drawn.push(OPEN_ALL.map(p=>p.id));}
                function marks(){} function drawDocTabs(){} function docTitle(){}
                function recomputeOverlap(){} function renderOverlapBanner(){} function closeReply(){}
                (async()=>{
                  await pollLightOnce();
                  const first={open:OPEN_ALL.map(p=>p.id),dropped:DROPPED.map(p=>p.id),
                    rev:LAST_PINS_REV,src:LAST_SRC_MTIME,drawn:drawn.slice()};
                  await pollLightOnce();
                  console.log(JSON.stringify({first,after:{open:OPEN_ALL.map(p=>p.id),
                    dropped:DROPPED.map(p=>p.id),rev:LAST_PINS_REV,src:LAST_SRC_MTIME,
                    drawn},pinReads,trashReads}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {
                "first": {"open": [1], "dropped": [9], "rev": "old", "src": "old-src", "drawn": []},
                "after": {"open": [2], "dropped": [10], "rev": "new", "src": "new-src", "drawn": [[2]]},
                "pinReads": 2,
                "trashReads": 2,
            },
        )

    def test_failed_boot_pin_read_is_retried_by_first_light_poll(self):
        """A failed first pin fetch leaves no revision baseline, so the next light poll loads the missing rows."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                extract_js_fn("applyPinLists"),
                extract_js_fn("loadPins"),
                js_esc(),
                js_markup(),
                extract_js_fn("boot"),
                extract_js_fn("pollLightOnce"),
                """
                let DOC=null,SWITCHSEQ=0,META=null,DEFAULT_DOC='main',OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[],PINS=[],DONE=[],DROPPED=[];
                let REPLY=null,COMPOSE={current:null},PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0; const CONFIRMING=new Set(),CONFIRMING_PIN=new Map(); const EDITOR={current:null,saving:false};
                let LAST_PINS_REV=null,LAST_SRC_MTIME=null,POLL_FAILS=0; const BUILD={lastSeq:null,timer:null};
                const META_BY=new Map(),VIEW_BY=new Map(),DOC_SEQ=new Map();
                const SEC_SEEN={open:null,review:null,done:null},MQ_COARSE={matches:false};
                const document={hidden:false};
                let pinReads=0;
                function api(url){
                  if(url==='/api/meta'||url==='/api/meta?light=1')
                    return Promise.resolve({data:{doc:'main',pins_rev:'r1',src_sig:'s1',build_seq:0,docs:[]}});
                  if(url==='/api/pins?all=1'){
                    pinReads++;
                    return pinReads===1 ? Promise.reject(Error('temporary')) : Promise.resolve({data:[{id:1}]});
                  }
                  if(url==='/api/pins/dropped')return Promise.resolve({data:{dropped:[]}});
                  throw Error(url);
                }
                function dq(url){return url;} function notifyQuery(){return '';}
                function $(sel){return {hidden:true,innerHTML:''};}
                function i18nStart(){} function takeLinkHash(){return {};}
                function applyTheme(){} function applyLayout(){} function initDiffWrap(){}
                function saveBtnLabel(){return html`save`;} async function loadDocs(){}
                function initialDoc(){return 'main';} function multiDoc(){return false;}
                function loadViews(){} function drawMeta(){} function applySideWidth(){}
                function applyOutlineState(){} function applyViewWidth(){return false;}
                function buildDoc(){} function autoW(){} function vecBoot(){}
                function restoreView(){} function drawDocTabs(){} function restoreDraft(){} function updateSectionStrip(){}
                function coach(){} function startLightPolling(){} function startBuildPolling(){}
                function drawNotify(){} function prefs(){return {};}
                function loadPeople(){} function notePinChanges(){} function noteReviewChanges(){}
                function drawPins(){} function marks(){} function docTitle(){}
                function recomputeOverlap(){} function renderOverlapBanner(){} function closeReply(){}
                function notifyHandle(){} function updateStaleBadge(){} function updateSyncBadge(){}
                function noteOtherDocs(){} function pollBuild(){}
                (async()=>{
                  await boot(); const before={rev:LAST_PINS_REV,src:LAST_SRC_MTIME,open:OPEN_ALL.map(p=>p.id)};
                  await pollLightOnce();
                  console.log(JSON.stringify({before,after:{rev:LAST_PINS_REV,src:LAST_SRC_MTIME,
                    open:OPEN_ALL.map(p=>p.id)},pinReads}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {
                "before": {"rev": None, "src": None, "open": []},
                "after": {"rev": "r1", "src": "s1", "open": [1]},
                "pinReads": 2,
            },
        )

    def test_successful_boot_pin_read_sets_baseline_without_extra_poll_fetch(self):
        """A successful first pin read records meta's baseline, so an unchanged light poll does not fetch again."""
        js = "\n".join(
            [
                js_esc(),
                js_markup(),
                extract_js_fn("boot"),
                extract_js_fn("pollLightOnce"),
                """
                let DOC=null,SWITCHSEQ=0,META=null,LAST_PINS_REV=null,LAST_SRC_MTIME=null;
                let POLL_FAILS=0; const BUILD={lastSeq:null,timer:null};
                const META_BY=new Map(),VIEW_BY=new Map(),DOC_SEQ=new Map(),MQ_COARSE={matches:false};
                const document={hidden:false}; let pinReads=0;
                function api(url){return Promise.resolve({data:{doc:'main',pins_rev:'r1',src_sig:'s1',
                  build_seq:0,docs:[]}});}
                function dq(url){return url;} function notifyQuery(){return '';}
                function $(sel){return {hidden:true,innerHTML:''};}
                function i18nStart(){} function takeLinkHash(){return {};}
                function applyTheme(){} function applyLayout(){} function initDiffWrap(){}
                function saveBtnLabel(){return html`save`;} async function loadDocs(){}
                function initialDoc(){return 'main';} function multiDoc(){return false;}
                function loadViews(){} function drawMeta(){} function applySideWidth(){}
                function applyOutlineState(){} function applyViewWidth(){return false;}
                function buildDoc(){} function autoW(){} function vecBoot(){}
                function restoreView(){} function drawDocTabs(){} function restoreDraft(){} function updateSectionStrip(){}
                function coach(){} function startLightPolling(){} function startBuildPolling(){}
                function drawNotify(){} function prefs(){return {};}
                async function loadPins(){pinReads++;return true;}
                function notifyHandle(){} function updateStaleBadge(){} function updateSyncBadge(){}
                function noteOtherDocs(){} function pollBuild(){}
                (async()=>{await boot(); await pollLightOnce();
                  console.log(JSON.stringify({rev:LAST_PINS_REV,src:LAST_SRC_MTIME,pinReads}));})();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"rev": "r1", "src": "s1", "pinReads": 1})

    def test_cached_document_switch_shows_its_done_rows_before_refresh(self):
        """Switching to cached document B draws B's completed rows before its background fetch resolves."""
        js = "\n".join(
            [
                extract_js_fn("switchDoc"),
                extract_js_fn("showDoc"),
                extract_js_fn("resetBuildForDoc"),
                """
                let DOC='a',META={build_seq:1},SWITCHSEQ=0,COMPOSE={current:null}; const EDITOR={current:null,saving:false};
                let OPEN_ALL=[{id:1,doc:'a'},{id:2,doc:'b'}],PINS=[OPEN_ALL[0]];
                let DONE_ALL=[{id:3,doc:'a'},{id:4,doc:'b'}],DONE=[DONE_ALL[0]];
                const BUILD={timer:null,lastSeq:null,error:null,booted:false,inflight:null};
                const BUILD_ERR_BY=new Map(),META_BY=new Map([['b',{build_seq:2}]]),VIEW_BY=new Map();
                const drawn=[],nodes=new Map();
                const document={body:{classList:{contains:()=>false}}};
                function $(sel){if(!nodes.has(sel))nodes.set(sel,{hidden:true,textContent:'',disabled:false}); return nodes.get(sel);}
                function docInfo(k){return k==='b'?{key:'b'}:null;}
                function pdoc(p){return p.doc||'a';}
                function saveView(){} function searchLeave(){} function parkDraft(){} function openDraftDoc(){} function restoreDraft(){}
                function cancelRepick(){} function savePrefs(){} function setHash(){}
                function hideTip(){} function drawMeta(){} function buildDoc(){} function autoW(){} function pvShow(){}
                function restoreView(){} function applyViewWidth(){return false;}
                function drawPins(){drawn.push(DONE.map(p=>p.id));}
                function marks(){} function drawDocTabs(){} function vecOpen(){} function pollBuild(){}
                function docTitle(){} function tr(s){return s;}
                function api(){return new Promise(()=>{});}
                switchDoc('b');
                console.log(JSON.stringify({doc:DOC,open:PINS.map(p=>p.id),done:DONE.map(p=>p.id),drawn}));
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"doc": "b", "open": [2], "done": [4], "drawn": [[4]]})

    def test_older_document_refresh_cannot_paint_after_switching_away_and_back(self):
        """A refresh from a previous visit to the same document must not replace the current view."""
        js = "\n".join(
            [
                extract_js_fn("refreshDoc"),
                """
                let DOC='b',SWITCHSEQ=1,META={pages:[{id:'current'}]},REFRESH_GEN=0;
                const META_BY=new Map(),pending=[],painted=[];
                const document={body:{classList:{contains:()=>false}}};
                function topAnchor(){return null;}
                function dq(u){return u;}
                function api(){return new Promise(resolve=>pending.push(resolve));}
                function drawMeta(){painted.push(META.pages[0].id);}
                function vecReleaseAll(){} function $$(){return [];}
                function restoreAnchor(){} function vecOpen(){} function loadPins(){return Promise.resolve();}
                (async()=>{
                  const stale=refreshDoc();
                  DOC='a'; SWITCHSEQ++;
                  DOC='b'; SWITCHSEQ++;
                  META={pages:[{id:'new-visit'}]};
                  pending[0]({data:{pages:[{id:'old-visit'}]}});
                  await stale;
                  console.log(JSON.stringify({painted,meta:META.pages[0].id}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"painted": [], "meta": "new-visit"})

    def test_cached_document_switch_reuses_fetched_meta_for_changed_build(self):
        """A changed cached document applies the meta it fetched without a second request."""
        js = "\n".join(
            [
                extract_js_fn("switchDoc"),
                extract_js_fn("refreshDoc"),
                """
                let DOC='a',SWITCHSEQ=0,META={pages:[{id:'a'}]},COMPOSE={current:null},REFRESH_GEN=0; const EDITOR={current:null,saving:false};
                const META_BY=new Map([['b',{pages:[{id:'old'}],pages_build:'v1'}]]);
                const VIEW_BY=new Map(),requests=[];
                const document={body:{classList:{contains:()=>false}}};
                function $(sel){return {hidden:true};}
                function docInfo(k){return k==='b'?{key:k}:null;}
                function saveView(){} function searchLeave(){} function parkDraft(){} function openDraftDoc(){} function restoreDraft(){}
                function cancelRepick(){} function savePrefs(){} function setHash(){}
                function hideTip(){} function showDoc(){} function drawMeta(){}
                function topAnchor(){return null;} function restoreAnchor(){}
                function vecReleaseAll(){} function $$(){return [];}
                function vecOpen(){} function loadPins(){return Promise.resolve();}
                function rebuildSources(){return [];} function sourceOk(){}   // a refresh ends a failed rebuild's error
                function dq(u,k){return u+(k||DOC);}
                function api(url){requests.push(url);return Promise.resolve({data:{pages:[{id:'new'}],pages_build:'v2'}});}
                (async()=>{await switchDoc('b');console.log(JSON.stringify({requests,build:META.pages_build}));})();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"requests": ["/api/metab"], "build": "v2"})


class ViewerPollingVisits(unittest.TestCase):
    """Polling from a previous document visit cannot update a later visit's screen."""

    def setUp(self):
        """Require Node to execute the viewer's actual polling functions."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_light_meta_from_previous_visit_does_not_update_returned_document(self):
        """A stale light response keeps its notification but cannot set the current revision baseline."""
        js = "\n".join(
            [
                extract_js_fn("pollLightOnce"),
                """
                let DOC='b',SWITCHSEQ=1,LAST_PINS_REV='old',LAST_SRC_MTIME='old-src';
                let POLL_FAILS=0; const BUILD={lastSeq:0,timer:null};
                const document={hidden:false},seen=[];
                let resolveMeta;
                function dq(u){return u;} function notifyQuery(){return '';}
                function api(){return new Promise(resolve=>{resolveMeta=resolve;});}
                function $(sel){return {hidden:true};}
                function notifyHandle(){seen.push('notify');}
                function updateStaleBadge(){seen.push('badge');}
                function updateSyncBadge(){} function noteOtherDocs(){}
                function loadPins(){seen.push('pins');return Promise.resolve(true);}
                function pollBuild(){seen.push('build');}
                (async()=>{
                  const old=pollLightOnce();
                  DOC='a'; SWITCHSEQ++;
                  DOC='b'; SWITCHSEQ++;
                  resolveMeta({data:{pins_rev:'new',src_sig:'new-src',build_seq:1}});
                  await old;
                  console.log(JSON.stringify({seen,rev:LAST_PINS_REV,src:LAST_SRC_MTIME}));
                })();
                """,
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            {"seen": ["notify"], "rev": "old", "src": "old-src"},
        )

    def test_light_poll_does_not_claim_revision_after_visit_changes_during_pin_load(self):
        """A pin read from an old visit cannot advance the new visit's meta baseline."""
        js = "\n".join(
            [
                extract_js_fn("pollLightOnce"),
                """
                let DOC='b',SWITCHSEQ=1,LAST_PINS_REV='old',LAST_SRC_MTIME='old-src';
                let POLL_FAILS=0; const BUILD={lastSeq:0,timer:null};
                const document={hidden:false},seen=[];
                let resolvePins;
                function dq(u){return u;} function notifyQuery(){return '';}
                function api(){return Promise.resolve({data:{pins_rev:'new',src_sig:'new-src',build_seq:1}});}
                function $(sel){return {hidden:true};}
                function notifyHandle(){} function updateStaleBadge(){}
                function updateSyncBadge(){} function noteOtherDocs(){}
                function loadPins(){return new Promise(resolve=>{resolvePins=resolve;});}
                function pollBuild(){seen.push('build');}
                (async()=>{
                  const old=pollLightOnce();
                  await Promise.resolve();
                  DOC='a'; SWITCHSEQ++;
                  DOC='b'; SWITCHSEQ++;
                  resolvePins(true); await old;
                  console.log(JSON.stringify({seen,rev:LAST_PINS_REV,src:LAST_SRC_MTIME}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"seen": [], "rev": "old", "src": "old-src"})

    def test_build_status_from_previous_visit_does_not_open_error_on_return(self):
        """An old build status response cannot display its error on a new visit to the same document."""
        js = "\n".join(
            [
                extract_js_fn("pollBuildOnce"),
                """
                let DOC='b',SWITCHSEQ=1; const BUILD={timer:null,booted:false,lastSeq:3};
                const seen=[],DOC_SEQ=new Map(),document={hidden:false};
                let resolveBuild;
                function dq(u){return u;}
                function api(){return new Promise(resolve=>{resolveBuild=resolve;});}
                function $(sel){return {hidden:true,disabled:false};}
                function showBuildErr(){seen.push('error');}
                function refreshDoc(){return Promise.resolve();}
                (async()=>{
                  const old=pollBuildOnce();
                  DOC='a'; SWITCHSEQ++;
                  DOC='b'; SWITCHSEQ++;
                  resolveBuild({data:{state:'fail',seq:3}});
                  await old;
                  console.log(JSON.stringify({seen,booted:BUILD.booted}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"seen": [], "booted": False})

    def test_build_completion_from_previous_visit_is_not_said_after_refresh(self):
        """A document switch during build refresh suppresses the old visit's completion message."""
        js = "\n".join(
            [
                extract_js_fn("pollBuildOnce"),
                """
                let DOC='b',SWITCHSEQ=1; const BUILD={timer:null,booted:true,lastSeq:3};
                BUILD.error=null;
                const seen=[],DOC_SEQ=new Map(),BUILD_ERR_BY=new Map(),META={pages:[1]};
                let resolveRefresh;
                function dq(u){return u;}
                function api(){return Promise.resolve({data:{state:'ok',seq:4,elapsed_s:1}});}
                function $(sel){return {hidden:true,disabled:false};}
                function refreshDoc(){return new Promise(resolve=>{resolveRefresh=resolve;});}
                function lineNote(){seen.push('said');}function showBuildErr(){seen.push('panel');}
                function pullSuffix(){return '';} function hideBuildErr(){}
                (async()=>{
                  const old=pollBuildOnce();
                  await Promise.resolve();
                  DOC='a'; SWITCHSEQ++;
                  DOC='b'; SWITCHSEQ++;
                  resolveRefresh(); await old;
                  console.log(JSON.stringify({seen}));
                })();
                """,
            ]
        )
        self.assertEqual(json.loads(run_node(js)), {"seen": []})
