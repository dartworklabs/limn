"""Exercise viewer actions whose document or pin loading finishes after navigation."""

import json
import shutil
import unittest

from helpers import extract_js_fn, run_node


class CrossDocumentActionLifetime(unittest.TestCase):
    """An action belongs to the document visit on which its request began."""

    def setUp(self):
        """Require Node for controlled JavaScript promise ordering."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, functions, scenario):
        """Use the served viewer functions and control delayed meta and pin-list responses."""
        js = "\n".join(
            [
                """
                let DOC='main',SWITCHSEQ=0,META=null,CUR=null,EDIT=null,REPICK=null;
                let OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[],PINS=[],DROPPED=[];
                let LAYOUT='wide',scrolls=0,links=0,banners=0,cardJumps=0,restores=0,trashOpens=0; const SMOOTH='smooth';
                const VIEW_BY=new Map(),META_BY=new Map([
                  ['other',{pages:[],pages_build:'same'}],['third',{pages:[],pages_build:'same'}]]);
                const OPEN_CARDS=new Set(),SEC={done:false};
                const document={body:{classList:{contains(){return false;}}},
                  querySelector(){return null;},getElementById(){return {scrollIntoView(){scrolls++;}}}};
                function $(s){return {hidden:true};}
                function docInfo(k){return k==='other'||k==='third';}
                function pdoc(p){return p.doc;} function dq(path,k){return path+'?doc='+k;}
                function saveView(){} function cancelRepick(){REPICK=null;} function cancelSelection(){}
                function editDirty(){return !!EDIT;} function cancelEdit(){}
                function savePrefs(){} function setHash(){} function hideTip(){} function showDoc(){}
                function drawMeta(){} function refreshDoc(){} function isRegion(){return false;}
                function setSide(){} function setSelMode(){} function drawPins(){}
                function viaDoc(){return false;} function setViewMode(){}
                function isViewer(){return false;} function restorePin(){restores++;} function openTrash(){trashOpens++;}
                function jumpToCard(){cardJumps++;} function jumpPin(){links++;}
                function findAnyPin(id){return OPEN_ALL.find(p=>p.id===id)||null;}
                function pinState(){return 'open';}
                function bannerRepick(){banners++;}
                const frames=[]; function requestAnimationFrame(fn){frames.push(fn);}
                const MQ_COARSE={matches:false};
                let firstOtherResolve=null,otherReads=0,loadPinsResolve=null,holdPins=false,loaded=true;
                function loadPins(){return holdPins?new Promise(resolve=>{loadPinsResolve=resolve;}):Promise.resolve(loaded);}
                function api(url){
                  if(url==='/api/meta?doc=other'){
                    otherReads++;
                    if(otherReads===1)return new Promise(resolve=>{firstOtherResolve=resolve;});
                  }
                  return Promise.resolve({data:{pages:[],pages_build:'same'}});
                }
                """,
                extract_js_fn("switchDoc"),
                *(extract_js_fn(name) for name in functions),
                scenario,
            ]
        )
        return json.loads(run_node(js))

    def test_review_pin_jump_does_not_resume_on_later_visit(self):
        """A late review-pin switch cannot scroll a later visit to that pin."""
        result = self._run(
            ("jumpPin",),
            """
            (async()=>{
              REVIEW_ALL=[{id:7,doc:'other'}];
              jumpPin(7);await switchDoc('third');await switchDoc('other');
              firstOtherResolve({data:{pages:[],pages_build:'same'}});
              await Promise.resolve();await Promise.resolve();
              console.log(JSON.stringify({doc:DOC,scrolls}));
            })();
            """,
        )
        self.assertEqual(result, {"doc": "other", "scrolls": 0})

    def test_pin_link_does_not_resume_on_later_visit(self):
        """A delayed link switch cannot open a pin after leaving and returning to its document."""
        result = self._run(
            ("openPinFromLink",),
            """
            (async()=>{
              OPEN_ALL=[{id:7,doc:'other'}];
              const old=openPinFromLink('other',7,false);
              await switchDoc('third');await switchDoc('other');
              firstOtherResolve({data:{pages:[],pages_build:'same'}});
              await old;
              console.log(JSON.stringify({doc:DOC,links}));
            })();
            """,
        )
        self.assertEqual(result, {"doc": "other", "links": 0})

    def test_pin_link_does_not_resume_after_pin_read_on_another_document(self):
        """A pin-list response must not open its link after the reader changes documents."""
        result = self._run(
            ("openPinFromLink",),
            """
            (async()=>{
              OPEN_ALL=[{id:7,doc:'main'}];holdPins=true;
              const old=openPinFromLink('main',7,false);
              await switchDoc('third');holdPins=false;loadPinsResolve(true);
              await old;
              console.log(JSON.stringify({doc:DOC,links}));
            })();
            """,
        )
        self.assertEqual(result, {"doc": "third", "links": 0})

    def test_repick_does_not_start_on_later_visit(self):
        """A delayed edit switch cannot start re-place mode after leaving and returning."""
        result = self._run(
            ("startRepick",),
            """
            (async()=>{
              EDIT={id:7,doc:'other',lo:1,hi:1,page:1};
              const old=startRepick();await switchDoc('third');await switchDoc('other');
              firstOtherResolve({data:{pages:[],pages_build:'same'}});
              await old;
              console.log(JSON.stringify({doc:DOC,repick:REPICK,banners}));
            })();
            """,
        )
        self.assertEqual(result, {"doc": "other", "repick": None, "banners": 0})

    def test_pin_link_frame_does_not_scroll_after_switch(self):
        """A scheduled card jump cannot run after a later document switch."""
        result = self._run(
            ("openPinFromLink",),
            """
            (async()=>{
              OPEN_ALL=[{id:7,doc:'main'}];
              await openPinFromLink('main',7,false);
              await switchDoc('third');frames.forEach(fn=>fn());
              console.log(JSON.stringify({doc:DOC,links,cardJumps}));
            })();
            """,
        )
        self.assertEqual(result, {"doc": "third", "links": 1, "cardJumps": 0})

    def test_failed_pin_snapshot_cannot_restore_from_old_trash(self):
        """A failed pin or Trash read cannot restore a pin from an earlier snapshot."""
        result = self._run(
            ("openPinFromLink",),
            """
            (async()=>{
              DROPPED=[{id:7,doc:'main'}];loaded=false;
              await openPinFromLink('main',7,true);
              console.log(JSON.stringify({restores,trashOpens,links}));
            })();
            """,
        )
        self.assertEqual(result, {"restores": 0, "trashOpens": 0, "links": 0})
