"""The queue of pins made while cut off, and how it is sent (js/offline.js).

The served functions are pulled and run under node with the queue and the server stubbed, so what these tests exercise
is the shipped code. What they protect is the one promise of the feature: a kept pin is dropped only once its pin is on
the server, and a pin whose place cannot be found again is kept and counted, never lost.
"""

import json
import re
import shutil
import unittest
from pathlib import Path

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
function offHas(id){return Promise.resolve(QUEUE.some(function(r){return r.id===id;}));}
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
var WRITTEN=[];
function loadPins(){LOADS++; OPEN_ALL=OPEN_ALL.concat(WRITTEN.splice(0,WRITTEN.length)); return Promise.resolve(true);}
// The stubbed server: ANSWERS maps a call to its answer or to the error it throws.
var ANSWERS={};
function api(url,o){
  if(url==='/api/pick'){PICKS.push(o.body); const a=ANSWERS.pick.shift();
    if(a&&a.throw)return Promise.reject(a.throw); return Promise.resolve({status:200,data:a});}
  if(url==='/api/pin'){PINS_SENT.push(o.body); const a=ANSWERS.pin.shift();
    if(a&&a.refuse){const e=new Error('HTTP '+a.refuse); e.status=a.refuse; return Promise.reject(e);}
    if(a&&a.throw)return Promise.reject(a.throw);
    WRITTEN.push({id:a.id,author:'me',doc:o.body.doc||'main',file:o.body.file||null,lo:o.body.lo,hi:o.body.hi,
      page:o.body.page,frac:o.body.frac,note:o.body.note});   // as the next list read would show it
    return Promise.resolve({status:200,data:a});}
  throw new Error('unexpected call '+url);
}
function rec(id,note){return {id:id,v:1,label:'inst',doc:'main',build:'pages-20261114T090000',page:3,
  rect:{x0:10,y0:20,x1:110,y1:40},pt:{w:612,h:792},place:null,sent:false,frac:[0.1,0.2,0.3,0.04],quote:'q'+id,note:note||('n'+id),
  kind_req:'fix',assignee:'agent',mentions:[],at:'2026-11-14T09:00:00Z',held:false,why:''};}
function found(lo){return {file:'main.tex',name:'main.tex',page:3,lo:lo,hi:lo+1,raw_lo:lo,raw_hi:lo+1,
  kind:'paragraph',via:'synctex',score:0.9,fill:1,rival:null,frac:[0.1,0.2,0.3,0.04],quote:'server quote',
  pdf_build:'pages-20261114T090000'};}
"""

FUNCTIONS = ("offlineBox", "offlineBody", "fracSame", "offlineLanded", "offlineFlush")


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
            const r=rec(1); r.sent=true;   // an earlier send attempted this one and lost the answer
            QUEUE=[r]; ANSWERS={pick:[found(10)],pin:[]};
            OPEN_ALL=[{id:41,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'n1'}];
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"pins": 0, "left": 0})

    def test_two_region_pins_on_one_page_are_both_written(self):
        """A view-only PDF, two boxes on page 3, the same note on both - which is ordinary. The duplicate judgment
        reads a region answer by its box as well as its page: a page-only judgment dropped the second pin unwritten."""
        got = self._run(
            """
            const a=rec(1,'same note'),b=rec(2,'same note');
            a.frac=[0.1,0.1,0.2,0.05]; b.frac=[0.1,0.6,0.2,0.05]; a.rect=null; b.rect=null;
            QUEUE=[a,b];
            ANSWERS={pick:[{page:3,frac:[0.1,0.1,0.2,0.05],quote:'top'},{page:3,frac:[0.1,0.6,0.2,0.05],quote:'bottom'}],
                     pin:[{id:61},{id:62}]};
            offlineFlush().then(function(){console.log(JSON.stringify({
              pins:PINS_SENT.map(function(b){return [b.page,b.frac[1],b.note];}),left:QUEUE.length}));});
            """
        )
        self.assertEqual(got["pins"], [[3, 0.1, "same note"], [3, 0.6, "same note"]])
        self.assertEqual(got["left"], 0)

    def test_a_region_pin_already_written_is_found_by_its_page_and_box(self):
        """The dedup still has to work where it should: this one's answer was lost on an earlier send."""
        got = self._run(
            """
            const a=rec(1,'note'); a.sent=true; a.rect=null; a.frac=[0.1,0.6,0.2,0.05]; QUEUE=[a];
            OPEN_ALL=[{id:63,author:'me',doc:'main',page:3,frac:[0.1,0.6,0.2,0.05],note:'note'}];
            ANSWERS={pick:[{page:3,frac:[0.1,0.6,0.2,0.05],quote:'bottom'}],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length,
              said:NOTES.map(function(n){return n.msg;}).join(' ')}));});
            """
        )
        self.assertEqual(got["pins"], 0)
        self.assertEqual(got["left"], 0)
        self.assertIn("#63", got["said"], "the notice names the pin, not the queue record")

    def test_an_attempted_region_record_is_not_matched_to_another_box_on_its_page(self):
        """Its own write was attempted and the answer lost, so it may be matched - but only to its own box. A pin of
        mine elsewhere on the same page, with the same note, is a different pin."""
        got = self._run(
            """
            const a=rec(1,'note'); a.sent=true; a.rect=null; a.frac=[0.1,0.6,0.2,0.05]; QUEUE=[a];
            OPEN_ALL=[{id:91,author:'me',doc:'main',page:3,frac:[0.1,0.1,0.2,0.05],note:'note'}];
            ANSWERS={pick:[{page:3,frac:[0.1,0.6,0.2,0.05]}],pin:[{id:92}]};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"pins": 1, "left": 0})

    def test_a_refused_write_leaves_the_record_unattempted_and_it_is_written_next_time(self):
        """The server answered, and the answer was no: nothing is on it. The record must not carry an attempt mark,
        or the next send matches it against a pin at the same place that belongs to another record and deletes it."""
        got = self._run(
            """
            const a=rec(1,'twice'),b=rec(2,'twice');
            QUEUE=[a,b];
            ANSWERS={pick:[found(10),found(10),found(10)],pin:[{refuse:400},{id:72},{id:73}]};
            offlineFlush().then(function(){
              const left=QUEUE.map(function(r){return {id:r.id,sent:r.sent};});
              return offlineFlush().then(function(){
                console.log(JSON.stringify({afterFirst:left,pins:PINS_SENT.length,
                  ids:PINS_SENT.map(function(x){return x.note;}),left:QUEUE.length}));});});
            """
        )
        self.assertEqual(got["afterFirst"], [{"id": 1, "sent": False}], "a refusal takes the attempt mark off")
        self.assertEqual(got["pins"], 3, "the refused one is written on the next send, not swallowed")
        self.assertEqual(got["left"], 0)

    def test_a_server_error_keeps_the_attempt_mark_and_is_looked_for_in_the_list(self):
        """A 5xx may follow a write that went through - the server wrote the pin and then failed answering, or a
        gateway timed out over a request that reached it. Clearing the mark would write the pin a second time."""
        got = self._run(
            """
            const a=rec(1,'once'); QUEUE=[a];
            ANSWERS={pick:[found(10),found(10)],pin:[{refuse:500},{id:95}]};
            offlineFlush().then(function(){
              const mark=QUEUE[0]&&QUEUE[0].sent;
              // The pin had in fact been written; the next send has to find it rather than write it again.
              OPEN_ALL=[{id:94,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'once'}];
              return offlineFlush().then(function(){
                console.log(JSON.stringify({mark:mark,pins:PINS_SENT.length,left:QUEUE.length}));});});
            """
        )
        self.assertEqual(got["mark"], True, "a 5xx leaves the record matchable")
        self.assertEqual(got["pins"], 1, "the pin already there is found, not written twice")
        self.assertEqual(got["left"], 0)

    def test_an_answer_that_never_came_keeps_the_attempt_mark(self):
        """A tab closed mid-request, or a lost answer: the record stays matchable, or its pin is written twice."""
        got = self._run(
            """
            const a=rec(1,'once'); QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[{throw:new Error('network')}]};
            offlineFlush().then(function(){console.log(JSON.stringify({
              left:QUEUE.length,sent:QUEUE[0]&&QUEUE[0].sent}));});
            """
        )
        self.assertEqual(got, {"left": 1, "sent": True})

    def test_two_pins_alike_in_every_field_are_both_written(self):
        """Someone pinned the same paragraph twice with the same note. The second is not the first: one pin on the
        server answers for one record, and a pin an earlier record answered for is not offered again."""
        got = self._run(
            """
            QUEUE=[rec(1,'twice'),rec(2,'twice')];
            ANSWERS={pick:[found(10),found(10)],pin:[{id:71},{id:72}]};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"pins": 2, "left": 0})

    def test_an_interrupted_send_does_not_swallow_the_rest_on_its_next_try(self):
        """The real way a pin was lost: the connection goes after the first pin, and the next send reads a list that
        now holds it. The records still waiting were never attempted, so each is written - whatever it resembles."""
        got = self._run(
            """
            const a=rec(1,'same note'),b=rec(2,'same note'),c=rec(3,'same note');
            a.frac=[0.1,0.1,0.2,0.05]; b.frac=[0.1,0.6,0.2,0.05]; c.frac=[0.1,0.1,0.2,0.05];
            a.rect=null; b.rect=null; c.rect=null;   // region drags: page and box are all they have
            QUEUE=[a,b,c];
            ANSWERS={pick:[{page:3,frac:a.frac},{page:3,frac:b.frac},{page:3,frac:c.frac}],
                     pin:[{id:81},{id:82},{id:83}]};
            const realApi=api; let n=0;
            api=function(url,o){const r=realApi(url,o);
              if(url==='/api/pin'&&++n===1)POLL_FAILS=2;   // the connection goes right after the first pin is written
              return r;};
            offlineFlush().then(function(){POLL_FAILS=0; return offlineFlush();}).then(function(){
              console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length,
                ids:PINS_SENT.map(function(b){return b.frac[1];})}));});
            """
        )
        self.assertEqual(got["pins"], 3, "every pin the person made is written")
        self.assertEqual(got["left"], 0)
        self.assertEqual(got["ids"], [0.1, 0.6, 0.1])

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

    def test_stored_lines_are_never_written_against_the_current_source(self):
        """A pick answered before the connection went, and hours of editing followed. Those line numbers now point at
        other text, so the send asks pick again about the drag itself and writes the lines that come back."""
        got = self._run(
            """
            const r=rec(1); r.place={file:'main.tex',name:'main.tex',lo:12,hi:13}; r.rect=null;
            r.pt={w:612,h:792};
            QUEUE=[r]; ANSWERS={pick:[found(30)],pin:[{id:51}]};
            offlineFlush().then(function(){console.log(JSON.stringify({picks:PICKS.length,
              pins:PINS_SENT.map(function(b){return [b.file,b.lo,b.hi];}),left:QUEUE.length}));});
            """
        )
        self.assertEqual(got["picks"], 1)
        self.assertEqual(got["pins"], [["main.tex", 30, 31]], "the lines pick answered now, not the ones kept")
        self.assertEqual(got["left"], 0)

    def test_a_record_with_no_box_is_picked_from_its_page_fractions(self):
        """Only the fractions and the page's size on that build were kept - the same product the drag itself sent."""
        got = self._run(
            """
            const r=rec(1); r.rect=null; r.pt={w:612,h:792}; r.frac=[0.25,0.5,0.1,0.02];
            QUEUE=[r]; ANSWERS={pick:[found(10)],pin:[{id:52}]};
            offlineFlush().then(function(){console.log(JSON.stringify({
              box:PICKS.map(function(p){return [p.x0,p.y0,p.x1,p.y1];}),pins:PINS_SENT.length}));});
            """
        )
        self.assertEqual(len(got["box"]), 1)
        for got_v, want in zip(got["box"][0], (0.25 * 612, 0.5 * 792, 0.35 * 612, 0.52 * 792), strict=True):
            self.assertAlmostEqual(got_v, want, places=6)
        self.assertEqual(got["pins"], 1)

    def test_a_record_with_neither_a_box_nor_fractions_is_held(self):
        """A box of zeros would resolve to the page's top-left corner and put the pin somewhere nobody chose."""
        got = self._run(
            """
            const r=rec(1); r.rect=null; r.pt=null; QUEUE=[r]; ANSWERS={pick:[found(10)],pin:[{id:53}]};
            offlineFlush().then(function(){console.log(JSON.stringify({picks:PICKS.length,pins:PINS_SENT.length,
              left:QUEUE.length,held:QUEUE[0]&&QUEUE[0].held}));});
            """
        )
        self.assertEqual(got, {"picks": 0, "pins": 0, "left": 1, "held": True})

    def test_a_region_answer_is_written_as_a_region_pin(self):
        """A view-only PDF, or a figure element with no code behind it: the pick answers a page and a box, and the pin
        is that - not a line pin whose file and lines are null."""
        got = self._run(
            """
            const r=rec(1); QUEUE=[r]; ANSWERS={pick:[{page:3,frac:[0.1,0.2,0.3,0.04],quote:'region words',
              pdf_build:'pages-20261114T090000'}],pin:[{id:54}]};
            offlineFlush().then(function(){console.log(JSON.stringify({body:PINS_SENT[0],left:QUEUE.length}));});
            """
        )
        self.assertEqual(got["left"], 0)
        self.assertEqual(
            got["body"],
            {
                "page": 3,
                "frac": [0.1, 0.2, 0.3, 0.04],
                "note": "n1",
                "quote": "region words",
                "pdf_build": "pages-20261114T090000",
                "doc": "main",
                "kind_req": "fix",
                "assignee": "agent",
            },
        )

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

    def test_two_sends_started_together_write_each_pin_once(self):
        """Reconnecting fires several triggers in the same tick ('online', the poll's recovery, boot). Both calls must
        not send the same records: the second has to find the send already under way, before any await."""
        got = self._run(
            """
            QUEUE=[rec(1),rec(2)]; ANSWERS={pick:[found(10),found(20)],pin:[{id:41},{id:42}]};
            Promise.all([offlineFlush(),offlineFlush()]).then(function(){console.log(JSON.stringify({
              picks:PICKS.length,pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"picks": 2, "pins": 2, "left": 0})

    def test_a_record_another_tab_wrote_meanwhile_is_not_written_again(self):
        """The queue is shared by this browser's tabs. A record that left while the pick was out has been dealt with."""
        got = self._run(
            """
            QUEUE=[rec(1)]; ANSWERS={pick:[found(10)],pin:[{id:41}]};
            const realApi=api;
            api=function(url,o){if(url==='/api/pick')QUEUE=[];   // the other tab wrote and dropped it
              return realApi(url,o);};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"pins": 0, "left": 0})


STORE_SCOPE = r"""
var OFF_STATE='state';
var OFF_READS=['/api/meta','/api/docs','/api/pins','/api/pins/dropped','/api/people','/api/outline-labels','/api/source'];
var STORE=new Map();
// Stands in for the one IndexedDB store, keeping put/get as they behave there.
function offIn(store,mode,fn){const s={put:function(v){STORE.set(v.key,v); return {};},
  get:function(k){return {result:STORE.get(k)};},delete:function(k){STORE.delete(k); return {};}};
  const rq=fn(s); return Promise.resolve(rq&&'result' in rq?rq.result:null);}
"""


class StoredAnswers(unittest.TestCase):
    """What may be stored for a reopened tab, and what may be served from the store (offline.js offStash/offStashed).

    api() hands its caller the answers it says it expects without throwing, and a read may expect a refusal: a Markdown
    document past the drawing limit answers 413 with its reason. Such an answer is not the document. Stored, the next
    visit with no network would open it as a document that simply has nothing in it.
    """

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        js = "\n".join([STORE_SCOPE, *(extract_js_fn(n) for n in ("offReadKey", "offStash", "offStashed")), scenario])
        return json.loads(run_node(js))

    def test_a_successful_answer_is_stored_and_served(self):
        got = self._run(
            """
            offStash('/api/meta',{pages_build:'pages-1'},200);
            offStashed('/api/meta',null).then(function(v){console.log(JSON.stringify({
              build:v&&v.data&&v.data.pages_build,status:v&&v.status}));});
            """
        )
        self.assertEqual(got, {"build": "pages-1", "status": 200})

    def test_a_refused_answer_is_never_stored(self):
        """413 with a reason, 404, any status the server refused with - none of it is the document."""
        got = self._run(
            """
            offStash('/api/source?doc=main',{error:'too_large',reason:'md_too_large'},413);
            offStash('/api/pins?all=1',{error:'nope'},404);
            offStashed('/api/source?doc=main',null).then(function(a){
              return offStashed('/api/pins?all=1',null).then(function(b){
                console.log(JSON.stringify({source:a,pins:b,kept:STORE.size}));});});
            """
        )
        self.assertEqual(got, {"source": None, "pins": None, "kept": 0})

    def test_a_later_refusal_does_not_replace_the_last_good_answer(self):
        """The document was read before the trip; a refusal afterwards must not take that copy away."""
        got = self._run(
            """
            offStash('/api/source?doc=main',{text:'the manuscript'},200);
            offStash('/api/source?doc=main',{error:'too_large'},413);
            offStashed('/api/source?doc=main',null).then(function(v){console.log(JSON.stringify({
              text:v&&v.data&&v.data.text,status:v&&v.status}));});
            """
        )
        self.assertEqual(got, {"text": "the manuscript", "status": 200})

    def test_an_answer_with_no_body_is_not_stored(self):
        got = self._run(
            """
            offStash('/api/meta',null,200);
            offStashed('/api/meta',null).then(function(v){console.log(JSON.stringify({got:v,kept:STORE.size}));});
            """
        )
        self.assertEqual(got, {"got": None, "kept": 0})

    def test_a_record_that_does_not_say_it_succeeded_is_dropped_not_trusted(self):
        """An earlier build of this viewer stored refusals with no status at all. Such a record must not be read as a
        success - that is the empty document again - and it is dropped so the next read asks the network."""
        got = self._run(
            """
            STORE.set('/api/source?doc=main',{key:'/api/source?doc=main',data:{error:'too_large'},at:1});
            offStashed('/api/source?doc=main',null).then(function(v){
              setTimeout(function(){console.log(JSON.stringify({got:v,left:STORE.size}));},0);});
            """
        )
        self.assertEqual(got, {"got": None, "left": 0})

    def test_a_light_poll_and_a_write_are_outside_the_store(self):
        """The light poll has to fail, so the status line says the connection is gone; a write is never a stored read."""
        got = self._run(
            """
            offStash('/api/meta?light=1',{pins_rev:'r2'},200);
            offStashed('/api/meta?light=1',null).then(function(a){
              return offStashed('/api/pin',{method:'POST'}).then(function(b){
                console.log(JSON.stringify({light:a,write:b,kept:STORE.size}));});});
            """
        )
        self.assertEqual(got, {"light": None, "write": None, "kept": 0})


class StoredReads(unittest.TestCase):
    """Which reads are stored for a reopened tab with no network (offline.js OFF_READS).

    A tab the phone discarded comes back with no network and is drawn from the stored answers. loadPins() reads twice
    and applies neither snapshot unless both answered, so a read left out of the list does not merely go missing - it
    throws away the stored list that did answer, and the screen has no pins at all (observed).
    """

    def off_reads(self):
        """The paths offline.js stores, read from the shipped source."""
        src = (Path(__file__).resolve().parent.parent / "js" / "offline.js").read_text(encoding="utf-8")
        m = re.search(r"const OFF_READS=\[(.*?)\];", src, re.S)
        self.assertIsNotNone(m, "OFF_READS is not declared as a literal list any more")
        return set(re.findall(r"'([^']+)'", m.group(1)))

    def test_every_read_loadpins_makes_is_stored(self):
        """Both of loadPins' reads, whatever they are, have to be in the list."""
        reads = set(re.findall(r"api\('(/api/[^'?]*)", extract_js_fn("loadPins")))
        self.assertTrue(reads, "loadPins makes no api() read any more - this test needs rewriting")
        self.assertLessEqual(reads, self.off_reads(), "a read loadPins makes is not stored for an offline visit")

    def test_the_stored_reads_are_the_boot_path_reads(self):
        """The list is exactly the boot path's reads. A new one is added here deliberately, with the thought of what a
        stored answer means for it; a light poll, a build state and every write stay out."""
        self.assertEqual(
            self.off_reads(),
            {
                "/api/meta",  # the pages, their sizes and the build the pins point at
                "/api/docs",  # the document tabs
                "/api/pins",  # the list itself
                "/api/pins/dropped",  # read by the same loadPins, which applies nothing without it
                "/api/people",  # the names on the cards
                "/api/outline-labels",  # the outline
                "/api/source",  # what a Markdown or text document is drawn from
            },
        )


if __name__ == "__main__":
    unittest.main()
