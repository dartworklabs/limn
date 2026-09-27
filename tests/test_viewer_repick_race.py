"""Run the viewer's real JavaScript through delayed re-place responses and navigation."""

import json
import shutil
import unittest

from helpers import extract_js_fn, run_node


class RepickRequestLifetime(unittest.TestCase):
    """A cancelled re-place request cannot update the current document or a later selection."""

    def setUp(self):
        """Require Node because the race depends on JavaScript promise continuation order."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        """Execute the production functions with controlled API and document-switch responses."""
        js = "\n".join(
            [
                """
                let PICKSEQ=0,REPICK={id:7,from:{lo:1,hi:1,page:1},box:null,cand:null};
                let CUR=null,PICKING=false,DOC='main',SWITCHSEQ=0,EDIT=null;
                let PENDING=null,LAYOUT='wide',MID_OVERLAY=false,PEND_SAVE=false;
                const MQ_COARSE={matches:false},VIEW_BY=new Map(),META_BY=new Map([['other',{pages:[]}]]);
                const document={body:{classList:{contains(){return false;}}}};
                const els={'#composer':{hidden:true},'#banner':{hidden:true}};
                function $(s){return els[s]||(els[s]={hidden:true});}
                function setBusy(){} function banner(){} function setSelMode(){} function setSide(){}
                function saveView(){} function savePrefs(){} function setHash(){} function hideTip(){}
                function showDoc(){} function editDirty(){return false;}
                function docInfo(k){return k==='other';}
                function dq(path,k){return path+'?doc='+k;}
                function clearPendingSave(){} function applySide(){} function tl(s){return s;}
                function errText(d){return d.error;}
                function lvOf(){return null;} function isRegion(){return false;}
                function scopeLabel(){return '';} function levelLabel(){return '';}
                function esc(s){return String(s);} function tr(s){return s;}
                const pending=[];
                function api(url){if(url==='/api/pick')return new Promise((resolve,reject)=>pending.push({resolve,reject}));
                  return Promise.resolve({data:{pages:[]}});}
                let refreshResolve=null,refreshCalls=0,compares=0,banners=0;
                function refreshDoc(){refreshCalls++;return new Promise(resolve=>{refreshResolve=resolve;});}
                function bannerCompare(){compares++; if(!REPICK)throw Error('cancelled re-place rendered');}
                function bannerRepick(){banners++; if(!REPICK)throw Error('cancelled re-place banner rendered');}
                function cancelSelection(){PICKSEQ++;}
                """,
                extract_js_fn("cancelRepick"),
                extract_js_fn("pick"),
                extract_js_fn("switchDoc"),
                scenario,
            ]
        )
        return json.loads(run_node(js))

    def test_cancelled_repick_ignores_late_success_and_failure(self):
        """Both success and failure continuations leave a cancelled re-place untouched."""
        result = self._run(
            """
            (async()=>{
              const first=pick({doc:'main'});cancelRepick();
              pending[0].resolve({data:{file:'m.tex',lo:1,hi:1,page:1}});
              await first;
              REPICK={id:8,from:{lo:2,hi:2,page:1},box:null,cand:null};
              const second=pick({doc:'main'});cancelRepick();
              pending[1].reject(Error('offline'));await second;
              console.log(JSON.stringify({compares,banners,repick:REPICK}));
            })().catch(e=>{console.error(e);process.exitCode=1;});
            """
        )
        self.assertEqual(result, {"compares": 0, "banners": 0, "repick": None})

    def test_document_switch_invalidates_inflight_repick(self):
        """An old document's delayed pick cannot draw a comparison on the new document."""
        result = self._run(
            """
            (async()=>{
              const request=pick({doc:'main'});await switchDoc('other');
              pending[0].resolve({data:{file:'m.tex',lo:1,hi:1,page:1}});
              await request;
              console.log(JSON.stringify({doc:DOC,compares,banners,repick:REPICK}));
            })().catch(e=>{console.error(e);process.exitCode=1;});
            """
        )
        self.assertEqual(result, {"doc": "other", "compares": 0, "banners": 0, "repick": None})

    def test_cancel_during_stale_build_refresh_ignores_old_error(self):
        """A delayed refresh after pdf_build_gone cannot recreate a cancelled banner."""
        result = self._run(
            """
            (async()=>{
              const request=pick({doc:'main'});
              pending[0].resolve({data:{error:'stale',pdf_build_gone:true}});
              await Promise.resolve();await Promise.resolve();
              cancelRepick();refreshResolve();await request;
              console.log(JSON.stringify({refreshCalls,compares,banners,repick:REPICK}));
            })().catch(e=>{console.error(e);process.exitCode=1;});
            """
        )
        self.assertEqual(result, {"refreshCalls": 1, "compares": 0, "banners": 0, "repick": None})
