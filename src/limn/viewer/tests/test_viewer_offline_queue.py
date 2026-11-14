"""The queue of pins made while cut off, and how it is sent (js/offline.js).

The served functions are pulled and run under node with the queue and the server stubbed, so what these tests exercise
is the shipped code. What they protect is the one promise of the feature: a kept pin is dropped only once its pin is on
the server, and a pin whose place cannot be found again is kept and counted, never lost.
"""

import json
import shutil
import unittest

from helpers import extract_js_fn, run_node

# The page scope a pulled offline function reads: the queue (an array standing in for IndexedDB), the server (api), the
# list the dedup judgment reads, and the messages. Every call is recorded so a test can say what went out and in which order.
SCOPE = r"""
var POLL_FAILS=0,DEFAULT_DOC='main',DOC='main',META={label:'inst',pages_build:'pages-20261114T090000',pages:[],built_at:'t'};
var OFF={n:0,held:0,flushing:false,prep:false,db:null};
var QUEUE=[],PICKS=[],PINS_SENT=[],NOTES=[],LOADS=0,OPEN_ALL=[];
var NOTICE_KIND={OK:'ok',WARN:'warn',ERR:'err',INFO:'info'},NOTICE_LIFE={TIMER:'timer',CLICK:'click'},NOTICE_PLACE={LINE:'line'};
function offAll(){return Promise.resolve(QUEUE.slice());}
function offDel(id){QUEUE=QUEUE.filter(function(r){return r.id!==id;}); return Promise.resolve(true);}
function offPut(rec){QUEUE=QUEUE.map(function(r){return r.id===rec.id?rec:r;}); return Promise.resolve(true);}
function offlineSync(){OFF.n=QUEUE.length; OFF.held=QUEUE.filter(function(r){return r.held;}).length; return Promise.resolve();}
function drawStatus(){}
function viewerBlocked(){return false;}
function offlineNow(){return POLL_FAILS>=2;}
function isMe(a){return a==='me';}
function pdoc(p){return p.doc||DEFAULT_DOC;}
function errText(d){return d&&d.error?String(d.error):'';}
function tr(s){return s;}
function tl(s,p){return s.replace(/\{(\w+)\}/g,function(_,k){return String(p[k]);});}
function lineNote(msg,kind){NOTES.push({msg:msg,kind:kind}); return {n:NOTES.length};}
function loadPins(){LOADS++; return Promise.resolve(true);}
// The stubbed server: ANSWERS maps a call to its answer or to the error it throws.
var ANSWERS={};
function api(url,o){
  if(url==='/api/pick'){PICKS.push(o.body); const a=ANSWERS.pick.shift();
    if(a&&a.throw)return Promise.reject(a.throw); return Promise.resolve({status:200,data:a});}
  if(url==='/api/pin'){PINS_SENT.push(o.body); const a=ANSWERS.pin.shift();
    if(a&&a.throw)return Promise.reject(a.throw); return Promise.resolve({status:200,data:a});}
  throw new Error('unexpected call '+url);
}
function rec(id,note){return {id:id,v:1,label:'inst',doc:'main',build:'pages-20261114T090000',page:3,
  rect:{x0:10,y0:20,x1:110,y1:40},frac:[0.1,0.2,0.3,0.04],quote:'q'+id,note:note||('n'+id),
  kind_req:'fix',assignee:'agent',mentions:[],at:'2026-11-14T09:00:00Z',held:false,why:''};}
function found(lo){return {file:'main.tex',name:'main.tex',page:3,lo:lo,hi:lo+1,raw_lo:lo,raw_hi:lo+1,
  kind:'paragraph',via:'synctex',score:0.9,fill:1,rival:null,frac:[0.1,0.2,0.3,0.04],quote:'server quote',
  pdf_build:'pages-20261114T090000'};}
"""

FUNCTIONS = ("offlineBody", "offlineLanded", "offlineFlush")


class OfflineQueueSend(unittest.TestCase):
    """offlineFlush: every record's own coordinates and build go to pick, its answer to the pin."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        js = "\n".join([SCOPE, *(extract_js_fn(name) for name in FUNCTIONS), scenario])
        return json.loads(run_node(js))

    def test_each_kept_pin_is_picked_on_its_own_build_and_then_written(self):
        """Two kept pins go out oldest first, each with the coordinates and build it was drawn on, and the queue empties."""
        got = self._run(
            """
            QUEUE=[rec(1),rec(2)]; ANSWERS={pick:[found(10),found(20)],pin:[{id:41},{id:42}]};
            offlineFlush().then(function(){console.log(JSON.stringify({
              picks:PICKS.map(function(p){return [p.page,p.x0,p.y0,p.x1,p.y1,p.pdf_build];}),
              pins:PINS_SENT.map(function(b){return [b.file,b.lo,b.hi,b.note,b.kind_req,b.assignee,b.quote];}),
              left:QUEUE.length,n:OFF.n}));});
            """
        )
        self.assertEqual(
            got["picks"],
            [[3, 10, 20, 110, 40, "pages-20261114T090000"], [3, 10, 20, 110, 40, "pages-20261114T090000"]],
        )
        # The found place wins over what was kept, including the server's own quote of those lines.
        self.assertEqual(
            got["pins"],
            [
                ["main.tex", 10, 11, "n1", "fix", "agent", "server quote"],
                ["main.tex", 20, 21, "n2", "fix", "agent", "server quote"],
            ],
        )
        self.assertEqual((got["left"], got["n"]), (0, 0))

    def test_a_pin_already_on_the_server_is_not_written_twice(self):
        """A send whose answer was lost earlier is found in the list and the record is dropped, not sent again."""
        got = self._run(
            """
            QUEUE=[rec(1)]; ANSWERS={pick:[found(10)],pin:[]};
            OPEN_ALL=[{id:41,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'n1'}];
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"pins": 0, "left": 0})

    def test_someone_elses_pin_on_the_same_lines_is_not_mine(self):
        """The same lines and note by another author is not this record's pin: it is still written."""
        got = self._run(
            """
            QUEUE=[rec(1)]; ANSWERS={pick:[found(10)],pin:[{id:41}]};
            OPEN_ALL=[{id:9,author:'other',doc:'main',file:'main.tex',lo:10,hi:11,note:'n1'}];
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"pins": 1, "left": 0})

    def test_a_place_that_cannot_be_found_is_kept_and_counted(self):
        """The build the pin was drawn on is gone: the record stays, marked, with why - and the next send tries again."""
        got = self._run(
            """
            QUEUE=[rec(1)]; ANSWERS={pick:[{error:'pdf_build_gone',pdf_build_gone:true}],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length,
              held:QUEUE[0].held,why:QUEUE[0].why,offHeld:OFF.held,notes:NOTES.map(function(n){return n.kind;})}));});
            """
        )
        self.assertEqual(got["pins"], 0)
        self.assertEqual((got["left"], got["held"], got["offHeld"]), (1, True, 1))
        self.assertEqual(got["why"], "pdf_build_gone")
        self.assertIn("warn", got["notes"])

    def test_a_lost_answer_to_the_pin_is_looked_for_before_it_is_called_a_failure(self):
        """No answer from POST /api/pin: the list is read again, and a pin that did land drops its record."""
        got = self._run(
            """
            QUEUE=[rec(1)]; ANSWERS={pick:[found(10)],pin:[{throw:new Error('network')}]};
            var reads=0; loadPins=function(){reads++; LOADS++;
              if(reads===2)OPEN_ALL=[{id:41,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'n1'}];
              return Promise.resolve(true);};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,reads:reads}));});
            """
        )
        self.assertEqual(got["left"], 0)
        self.assertGreaterEqual(got["reads"], 2)

    def test_a_refused_pick_leaves_the_record_for_the_next_send(self):
        """A pick that could not be sent at all is neither a found place nor a lost pin: the record waits, unmarked."""
        got = self._run(
            """
            QUEUE=[rec(1)]; ANSWERS={pick:[{throw:new Error('network')}],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,held:QUEUE[0].held,
              pins:PINS_SENT.length,notes:NOTES.map(function(n){return n.kind;})}));});
            """
        )
        self.assertEqual((got["left"], got["held"], got["pins"]), (1, False, 0))
        self.assertIn("warn", got["notes"])

    def test_nothing_goes_out_while_the_connection_is_gone(self):
        """Cut off, the queue is not sent: the pins stay and no request is made."""
        got = self._run(
            """
            POLL_FAILS=2; QUEUE=[rec(1)]; ANSWERS={pick:[],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({picks:PICKS.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"picks": 0, "left": 1})

    def test_the_send_stops_where_the_connection_is_lost_midway(self):
        """The connection goes while the queue is being sent: what is left stays for the next send."""
        got = self._run(
            """
            QUEUE=[rec(1),rec(2)]; ANSWERS={pick:[found(10),found(20)],pin:[{id:41},{id:42}]};
            var once=false; const realApi=api;
            api=function(url,o){if(url==='/api/pin'&&!once){once=true; POLL_FAILS=2;} return realApi(url,o);};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"pins": 1, "left": 1})


if __name__ == "__main__":
    unittest.main()
