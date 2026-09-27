"""Execute the viewer's pin-list decisions and request ordering under Node."""

import json
import shutil
import unittest

from helpers import extract_js_fn, run_node


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

    def test_newer_refresh_wins_when_older_trash_request_finishes_last(self):
        """An older response never restores stale rows or emits stale transition toasts after a newer refresh."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                extract_js_fn("applyPinLists"),
                extract_js_fn("loadPins"),
                """
                let DOC='main',DEFAULT_DOC='main',OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[],PINS=[],DONE=[],DROPPED=[];
                let EDIT=null,REPLY=null,CUR=null,PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0;
                const SEC_SEEN={open:null,review:null,done:null},calls=[],reads=[],toasts=[];
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
                function diffToast(prev,rows){calls.push(['diff',prev.map(p=>p.id),rows.map(p=>p.id)]);}
                function reviewToast(prev,rows){calls.push(['review',prev.map(p=>p.id),rows.map(p=>p.id)]);}
                function toast(msg){toasts.push(msg);} function tl(s){return s;}
                function drawPins(){calls.push(['draw',OPEN_ALL.map(p=>p.id)]);}
                function marks(){} function drawDocTabs(){} function docTitle(){}
                function recomputeOverlap(){} function renderOverlapBanner(){} function closeReply(){}
                reads.push([{id:1}], [{id:2}]);
                const old=loadPins();
                setImmediate(async()=>{
                  const newest=loadPins(); await newest;
                  firstTrash({data:{dropped:[{id:99}]}}); await old;
                  console.log(JSON.stringify({open:OPEN_ALL.map(p=>p.id),dropped:DROPPED.map(p=>p.id),calls,toasts}));
                });
                """,
            ]
        )
        result = json.loads(run_node(js))
        self.assertEqual(result["open"], [2])
        self.assertEqual(result["dropped"], [])
        self.assertEqual(result["calls"], [["diff", [], [2]], ["review", [], [2]], ["draw", [2]]])
        self.assertEqual(result["toasts"], [])

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
                let EDIT=null,REPLY=null,CUR=null,PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0;
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
                function diffToast(prev,rows){calls.push(['diff',rows.map(p=>p.id)]);}
                function reviewToast(prev,rows){calls.push(['review',rows.map(p=>p.id)]);}
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
                let DOC='main',DEFAULT_DOC='main',OPEN_ALL=[{id:0}],REVIEW_ALL=[],DONE_ALL=[],PINS=OPEN_ALL,DONE=[],DROPPED=[];
                let EDIT=null,REPLY=null,CUR=null,PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0;
                let LAST_PINS_REV='old',LAST_SRC_MTIME='old-src',LAST_BUILD_SEQ=0,BUILD_TIMER=null,POLL_FAILS=0;
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
                function diffToast(){} function reviewToast(){}
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

    def test_failed_boot_pin_read_is_retried_by_first_light_poll(self):
        """A failed first pin fetch leaves no revision baseline, so the next light poll loads the missing rows."""
        js = "\n".join(
            [
                extract_js_fn("pinState"),
                extract_js_fn("derivePinLists"),
                extract_js_fn("applyPinLists"),
                extract_js_fn("loadPins"),
                extract_js_fn("boot"),
                extract_js_fn("pollLightOnce"),
                """
                let DOC=null,META=null,DEFAULT_DOC='main',OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[],PINS=[],DONE=[],DROPPED=[];
                let EDIT=null,REPLY=null,CUR=null,PINS_LOAD_SEQ=0,PINS_APPLIED_SEQ=0;
                let LAST_PINS_REV=null,LAST_SRC_MTIME=null,LAST_BUILD_SEQ=null,BUILD_TIMER=null,POLL_FAILS=0;
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
                function saveBtnLabel(){return 'save';} async function loadDocs(){}
                function initialDoc(){return 'main';} function multiDoc(){return false;}
                function loadViews(){} function drawMeta(){} function applySideWidth(){}
                function applyOutlineState(){} function applyViewWidth(){return false;}
                function buildDoc(){} function autoW(){} function vecBoot(){}
                function restoreView(){} function drawDocTabs(){} function restoreDraft(){}
                function coach(){} function startLightPolling(){} function startBuildPolling(){}
                function drawNotify(){} function prefs(){return {};}
                function loadPeople(){} function diffToast(){} function reviewToast(){}
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
                extract_js_fn("boot"),
                extract_js_fn("pollLightOnce"),
                """
                let DOC=null,META=null,LAST_PINS_REV=null,LAST_SRC_MTIME=null;
                let LAST_BUILD_SEQ=null,BUILD_TIMER=null,POLL_FAILS=0;
                const META_BY=new Map(),VIEW_BY=new Map(),DOC_SEQ=new Map(),MQ_COARSE={matches:false};
                const document={hidden:false}; let pinReads=0;
                function api(url){return Promise.resolve({data:{doc:'main',pins_rev:'r1',src_sig:'s1',
                  build_seq:0,docs:[]}});}
                function dq(url){return url;} function notifyQuery(){return '';}
                function $(sel){return {hidden:true,innerHTML:''};}
                function i18nStart(){} function takeLinkHash(){return {};}
                function applyTheme(){} function applyLayout(){} function initDiffWrap(){}
                function saveBtnLabel(){return 'save';} async function loadDocs(){}
                function initialDoc(){return 'main';} function multiDoc(){return false;}
                function loadViews(){} function drawMeta(){} function applySideWidth(){}
                function applyOutlineState(){} function applyViewWidth(){return false;}
                function buildDoc(){} function autoW(){} function vecBoot(){}
                function restoreView(){} function drawDocTabs(){} function restoreDraft(){}
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
                """
                let DOC='a',META={build_seq:1},SWITCHSEQ=0,CUR=null,EDIT=null;
                let OPEN_ALL=[{id:1,doc:'a'},{id:2,doc:'b'}],PINS=[OPEN_ALL[0]];
                let DONE_ALL=[{id:3,doc:'a'},{id:4,doc:'b'}],DONE=[DONE_ALL[0]];
                let BUILD_TIMER=null,LAST_BUILD_SEQ=null,LAST_BUILD_ERR=null,BUILD_BOOTED=false,BUILD_INFLIGHT=null;
                const BUILD_ERR_BY=new Map(),META_BY=new Map([['b',{build_seq:2}]]),VIEW_BY=new Map();
                const drawn=[],nodes=new Map();
                const document={body:{classList:{contains:()=>false}}};
                function $(sel){if(!nodes.has(sel))nodes.set(sel,{hidden:true,textContent:'',disabled:false}); return nodes.get(sel);}
                function docInfo(k){return k==='b'?{key:'b'}:null;}
                function pdoc(p){return p.doc||'a';}
                function saveView(){} function cancelRepick(){} function savePrefs(){} function setHash(){}
                function hideTip(){} function drawMeta(){} function buildDoc(){} function autoW(){}
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
