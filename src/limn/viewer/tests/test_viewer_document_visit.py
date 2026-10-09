"""Exercise delayed document-switch continuations in the served viewer JavaScript."""

import json
import shutil
import unittest

from helpers import extract_js_fn, run_node


class DocumentVisitActions(unittest.TestCase):
    """An action from an earlier visit must not fire after leaving and returning to a document."""

    def setUp(self):
        """Require Node to run the actual viewer functions with controlled promise order."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, functions, scenario):
        """Keep the document switch real while controlling only the server's meta response."""
        js = "\n".join(
            [
                """
                let DOC='main',SWITCHSEQ=0,META=null,COMPOSE={current:null},REPICK=null; const EDITOR={current:null,saving:false};
                let OPEN_ALL=[{id:7,doc:'other',file:'m.tex',lo:1,hi:1,page:1}],REVIEW_ALL=[],DONE_ALL=[];
                let LAYOUT='wide',modeCalls=0;const REV={back:null,target:null};
                const VIEW_BY=new Map(),META_BY=new Map([
                  ['other',{pages:[],pages_build:'same'}],['third',{pages:[],pages_build:'same'}]]);
                const document={body:{classList:{contains(){return false;}}}};
                function $(s){return {hidden:true};}
                function docInfo(k){return k==='other'||k==='third';}
                function pdoc(p){return p.doc;} function dq(path,k){return path+'?doc='+k;}
                function saveView(){} function searchLeave(){} function parkDraft(){} function openDraftDoc(){} function restoreDraft(){}
                function cancelRepick(){} function cancelSelection(){}
                function editDirty(){return false;} function cancelEdit(){}
                function savePrefs(){} function setHash(){} function hideTip(){} function showDoc(){}
                function drawMeta(){} function refreshDoc(){} function isRegion(){return false;}
                function setSide(){} function loadRevisions(){}
                function setViewMode(){modeCalls++;}
                let firstOtherResolve=null,otherReads=0;
                function api(url){
                  if(url==='/api/meta?doc=other'){
                    otherReads++;
                    if(otherReads===1)return new Promise(resolve=>{firstOtherResolve=resolve;});
                  }
                  return Promise.resolve({data:{pages:[],pages_build:'same'}});
                }
                """,
                *(extract_js_fn(name) for name in functions),
                scenario,
            ]
        )
        return json.loads(run_node(js))

    def test_old_via_doc_action_does_not_run_on_later_visit(self):
        """A delayed first visit cannot replay a pin action after the reader leaves and returns."""
        result = self._run(
            ("switchDoc", "viaDoc"),
            """
            (async()=>{
              const actions=[];
              viaDoc(7,id=>actions.push(id));
              await switchDoc('third');await switchDoc('other');
              firstOtherResolve({data:{pages:[],pages_build:'same'}});
              await Promise.resolve();await Promise.resolve();
              console.log(JSON.stringify({doc:DOC,actions,visits:SWITCHSEQ}));
            })();
            """,
        )
        self.assertEqual(result, {"doc": "other", "actions": [], "visits": 3})

    def test_old_change_view_action_does_not_open_on_later_visit(self):
        """A delayed change-view navigation cannot open a pin on a later visit to the same key."""
        result = self._run(
            ("switchDoc", "findAnyPin", "showChange"),
            """
            (async()=>{
              const old=showChange(7);
              await switchDoc('third');await switchDoc('other');
              firstOtherResolve({data:{pages:[],pages_build:'same'}});
              await old;
              console.log(JSON.stringify({doc:DOC,target:REV.target,back:REV.back,modeCalls}));
            })();
            """,
        )
        self.assertEqual(result, {"doc": "other", "target": None, "back": None, "modeCalls": 0})
