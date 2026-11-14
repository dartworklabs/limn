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
var OFF_STATE='state',OFF_WROTE='wrote',OFF_WROTE_MAX=500,STATE=new Map();
function offIn(store,mode,fn){const s={put:function(v){STATE.set(v.key,v); return {};},
  get:function(k){return {result:STATE.get(k)};},delete:function(k){STATE.delete(k); return {};}};
  const rq=fn(s); return Promise.resolve(rq&&'result' in rq?rq.result:null);}
var OFF={n:0,held:0,flushing:false,prep:false,db:null};
var QUEUE=[],PICKS=[],PINS_SENT=[],PINS_OK=[],NOTES=[],LOADS=0,OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[];
var NOTICE_KIND={OK:'ok',WARN:'warn',ERR:'err',INFO:'info'},NOTICE_LIFE={TIMER:'timer',CLICK:'click'},NOTICE_PLACE={LINE:'line'};
var SOURCE={};   // the source of each document as the server would read it now: {<doc>: [lines]}
function dq(u,k){return u+(u.indexOf('?')<0?'?':'&')+'doc='+encodeURIComponent(k);}
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
  if(url.indexOf('/api/source?doc=')===0){const k=decodeURIComponent(url.split('doc=')[1]);
    if(SOURCE[k]==='down')return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve({status:200,data:{file:'notes.md',lines:SOURCE[k]||[]}});}
  if(url==='/api/pin'){PINS_SENT.push(o.body); const a=ANSWERS.pin.shift();
    if(a&&a.refuse){const e=new Error('HTTP '+a.refuse); e.status=a.refuse; return Promise.reject(e);}
    if(a&&a.throw)return Promise.reject(a.throw);
    PINS_OK.push(a.id);   // the pins that exist, as against the attempts counted in PINS_SENT
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

FUNCTIONS = (
    "offlineBox",
    "offlineBody",
    "fracSame",
    "pvTopId",
    "offlineLanded",
    "offWrote",
    "offWroteAdd",
    "offWroteKeep",
    "linesWhere",
    "offlinePlaceLines",
    "offlineFlush",
)


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

    def test_a_pin_this_queue_wrote_is_never_taken_for_another_record_s(self):
        """The ambiguity that was deleting pins: two records alike in place and note, one written and gone from the
        queue, the other left with an attempt mark by a 5xx that wrote nothing. The written pin is remembered as this
        queue's, so the record left is written instead of being matched to it."""
        got = self._run(
            """
            const a=rec(1,'twin'),b=rec(2,'twin');
            QUEUE=[a,b];
            ANSWERS={pick:[found(10),found(10),found(10)],pin:[{refuse:500},{id:72},{id:73}]};
            offlineFlush().then(function(){
              // The next read of the list shows b's pin. a's 5xx wrote nothing, which this cannot know - so a's own
              // write has to go out again rather than be answered for by the pin its twin made.
              return offlineFlush().then(function(){
                console.log(JSON.stringify({written:PINS_OK,left:QUEUE.length}));});});
            """
        )
        self.assertEqual(got["written"], [72, 73], "a's write goes out again instead of claiming b's pin")
        self.assertEqual(got["left"], 0)

    def test_a_pin_that_was_already_there_is_not_this_record_s_write(self):
        """A record is matched only against pins newer than the write it was attempted after. A pin of mine at the
        same place with the same note that predates the attempt is some earlier pin, not this record's."""
        got = self._run(
            """
            const a=rec(1,'same'); QUEUE=[a];
            OPEN_ALL=[{id:40,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'same'}];
            ANSWERS={pick:[found(10),found(10)],pin:[{throw:new Error('network')},{id:41}]};
            offlineFlush().then(function(){
              return offlineFlush().then(function(){
                console.log(JSON.stringify({pins:PINS_OK.length,left:QUEUE.length,top:a.top}));});});
            """
        )
        self.assertEqual(got["top"], 40, "the attempt notes the pins that existed before it")
        self.assertEqual(got["pins"], 1, "the record is written; the older pin is not mistaken for its write")
        self.assertEqual(got["left"], 0)

    def test_the_ledger_keeps_what_a_waiting_record_still_needs(self):
        """Capping the ledger by length would drop the number a record that waited through many writes still needs, so
        it is pruned against the records left instead: only numbers above the smallest boundary are kept, and an empty
        queue keeps none."""
        got = self._run(
            """
            const held=rec(1,'held'); held.rect=null; held.pt=null;   // stays in the queue, nothing can place it
            const b=rec(2,'twin'),c=rec(3,'twin');
            QUEUE=[held,b,c];
            ANSWERS={pick:[found(10),found(20)],pin:[{id:61},{id:62}]};
            offlineFlush().then(function(){
              const after=(STATE.get('wrote')||{}).ids;
              QUEUE=[];   // the waiting record is dealt with by hand
              return offWroteKeep([]).then(function(){
                console.log(JSON.stringify({afterSend:after,afterEmpty:(STATE.get('wrote')||{}).ids,
                  left:QUEUE.length}));});});
            """
        )
        self.assertEqual(got["afterSend"], [61, 62], "kept while a record waits")
        self.assertEqual(got["afterEmpty"], [], "nothing waits, nothing to remember")

    def test_a_lost_answer_is_still_matched_to_its_own_pin(self):
        """The dedup has to keep working where it is sound: nothing else of this queue wrote that pin."""
        got = self._run(
            """
            const a=rec(1,'alone'); QUEUE=[a];
            ANSWERS={pick:[found(10),found(10)],pin:[{throw:new Error('network')}]};
            offlineFlush().then(function(){
              // The write did reach the server; its answer was lost. The next read of the list shows it.
              OPEN_ALL=[{id:80,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'alone'}];
              return offlineFlush().then(function(){
                console.log(JSON.stringify({tries:PINS_SENT.length,written:PINS_OK.length,left:QUEUE.length}));});});
            """
        )
        self.assertEqual(got, {"tries": 1, "written": 0, "left": 0}, "found, not written a second time")

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
var OFF_STATE='state',OFF={idem:false};
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

    def test_a_meta_answer_says_whether_the_server_knows_a_write_by_its_key(self):
        """Every meta answer, the light poll's included, carries it; an answer without it is an older server."""
        got = self._run(
            """
            const seen=[];
            offStash('/api/meta?light=1',{pin_idem:true},200,null); seen.push(OFF.idem);
            offStash('/api/pins?all=1',[],200,null); seen.push(OFF.idem);          // another read says nothing about it
            offStash('/api/meta?doc=ms',{pages:[]},200,null); seen.push(OFF.idem);  // a meta answer without it: an older server
            offStash('/api/meta',{pin_idem:true},500,null); seen.push(OFF.idem);    // not an answer to go by
            console.log(JSON.stringify(seen));
            """
        )
        self.assertEqual(got, [True, True, False, False])

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


SERVE_SCOPE = r"""
var POLL_FAILS=0,LAST_PINS_REV='r1',SAID=[],ENDED=[];
var OFF={boot:false,saidStale:false,staleNote:null};
var navigator={onLine:true};
var NOTICE_KIND={WARN:'warn'};
function tr(s){return s;} function tl(s){return s;}
function sourceOk(){} function apiFailed(o,why){SAID.push(why);}
function lineNote(msg){const n={n:1,msg:msg}; return n;}
function endNotice(n){ENDED.push(n.msg);}
function offStash(){}
// The store holds one good answer to the pin read.
function offStashed(url){return Promise.resolve(url==='/api/pins?all=1'?{data:['stored'],status:200,at:0}:null);}
var NET='down';   // what fetch does: 'down' rejects as a lost connection does, 'up' answers
globalThis.fetch=function(){return NET==='down'?Promise.reject(new TypeError('Failed to fetch'))
  :Promise.resolve({status:200,json:function(){return Promise.resolve(['fresh']);}});};
function read(){return api('/api/pins?all=1',{what:'핀 읽기'}).then(function(r){return r.data[0];},function(){return 'failed';});}
"""


class StoredReadsServe(unittest.TestCase):
    """When a stored answer may stand in for a read the network refused (api.js, offline.js offlineMayServe).

    Answered from the store whenever a read failed, a failure while the viewer was connected read as a success: the
    pin list stayed stale with no '핀 읽기 실패' and nothing asked again, and a Markdown source's note and its re-ask
    went the same way. The store answers a visit's first reads and a connection known to be gone - nothing else.
    """

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        names = ("offlineNow", "offlineMayServe", "offStaleSaid", "offlineBack", "api")
        return json.loads(run_node("\n".join([SERVE_SCOPE, *(extract_js_fn(n) for n in names), scenario])))

    def test_a_read_that_fails_while_connected_is_a_failure(self):
        """After the first reads, with the light poll answering: the failure is said, not papered over."""
        got = self._run("read().then(function(v){console.log(JSON.stringify({got:v,said:SAID.length}));});")
        self.assertEqual(got, {"got": "failed", "said": 1})

    def test_the_first_reads_of_a_visit_are_answered_from_the_store(self):
        """A tab opened again with no network: there is nothing else to draw from."""
        got = self._run(
            "OFF.boot=true; read().then(function(v){console.log(JSON.stringify({got:v,said:SAID.length,stale:OFF.saidStale}));});"
        )
        self.assertEqual(got, {"got": "stored", "said": 0, "stale": True})

    def test_a_connection_known_to_be_gone_is_answered_from_the_store(self):
        """Two light polls lost, or the browser says there is no network: switching documents during a flight."""
        for gone in ("POLL_FAILS=2;", "navigator.onLine=false;"):
            with self.subTest(gone=gone):
                got = self._run(gone + "read().then(function(v){console.log(JSON.stringify({got:v}));});")
                self.assertEqual(got, {"got": "stored"})

    def test_the_first_answer_from_the_network_ends_the_stored_screen(self):
        """Its message goes and the pin list is read again whatever revision it was read at."""
        got = self._run(
            """
            OFF.boot=true;
            read().then(function(first){OFF.boot=false; NET='up';
              return read().then(function(second){console.log(JSON.stringify({first:first,second:second,
                stale:OFF.saidStale,ended:ENDED.length,rev:LAST_PINS_REV}));});});
            """
        )
        self.assertEqual(got, {"first": "stored", "second": "fresh", "stale": False, "ended": 1, "rev": None})


class OfflineQuote(unittest.TestCase):
    """The words a drag made with no network lies on, read from the PDF already open (offline.js quoteIn)."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        # A 600 x 800 pt page; an item is where its baseline starts (from the bottom), its width and its height.
        scope = """
        function item(str,x,top,w,h){return {str:str,transform:[h,0,0,h,x,800-top-h],width:w,height:h};}
        var ITEMS=[item('Title of the paper',72,100,300,14),
                   item('A line that starts at the margin and runs across the page.',72,200,456,10),
                   item('The line below it.',72,214,120,10),
                   item('Far below.',72,600,60,10),
                   item('   ',72,206,10,10)];
        """
        return json.loads(run_node("\n".join([scope, extract_js_fn("quoteIn"), scenario])))

    def test_a_line_that_starts_left_of_the_box_and_runs_through_it_is_read(self):
        """The drag starts inside the text column, not at its margin - as nearly every drag does. Judged by where
        the line starts, nothing was read and every quote was empty (seen on a live document)."""
        got = self._run("console.log(JSON.stringify(quoteIn(ITEMS,800,{x0:150,y0:196,x1:400,y1:226})));")
        self.assertEqual(got, "A line that starts at the margin and runs across the page. The line below it.")

    def test_lines_the_box_is_not_on_are_left_out(self):
        got = self._run("console.log(JSON.stringify(quoteIn(ITEMS,800,{x0:150,y0:196,x1:400,y1:212})));")
        self.assertEqual(got, "A line that starts at the margin and runs across the page.")

    def test_a_box_beside_the_text_reads_nothing(self):
        got = self._run("console.log(JSON.stringify(quoteIn(ITEMS,800,{x0:540,y0:196,x1:590,y1:226})));")
        self.assertEqual(got, "")

    def test_a_long_quote_is_cut_as_the_server_cuts_its_own(self):
        got = self._run(
            "const many=[]; for(let i=0;i<30;i++)many.push(item('0123456789',72,200,400,10));"
            "console.log(JSON.stringify(quoteIn(many,800,{x0:100,y0:196,x1:300,y1:212})));"
        )
        self.assertEqual(len(got), 160)
        self.assertTrue(got.endswith("…"))


MD_REC = """
function mdrec(id,lo,text){return {id:id,v:1,label:'inst',doc:'notes',build:'',page:undefined,rect:null,frac:undefined,pt:null,
  quote:'q',note:'md note',kind_req:'fix',assignee:'agent',mentions:[],at:'t',held:false,why:'',sent:false,place:null,
  lines:{file:'notes.md',name:'notes.md',lo:lo,hi:lo+text.split('\\n').length-1,text:text,kind:'lines',scope:null},idem:'key-0123456789abcdef'};}
"""


class LinePins(unittest.TestCase):
    """A Markdown or text document's kept pin: its lines are its place, and they are written where they read the same
    now (offline.js linesWhere, offlinePlaceLines). Without this such a pin had no box to pick with and was always held."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        js = "\n".join([SCOPE, MD_REC, *(extract_js_fn(name) for name in FUNCTIONS), scenario])
        return json.loads(run_node(js))

    def test_lines_that_still_read_the_same_are_written_where_they_were(self):
        got = self._run(
            """
            SOURCE.notes=['# T','','first','second','third'];
            QUEUE=[mdrec(1,3,'first\\nsecond')]; ANSWERS={pick:[],pin:[{id:11}]};
            offlineFlush().then(function(){console.log(JSON.stringify({picks:PICKS.length,left:QUEUE.length,
              body:PINS_SENT[0]}));});
            """
        )
        self.assertEqual(got["picks"], 0, "a line pin is not picked from a PDF")
        self.assertEqual(got["left"], 0)
        body = got["body"]
        self.assertEqual(
            (body["file"], body["lo"], body["hi"], body["kind"], body["note"]), ("notes.md", 3, 4, "lines", "md note")
        )
        self.assertNotIn("page", body)
        self.assertNotIn("frac", body)
        self.assertNotIn("pdf_build", body)

    def test_lines_pushed_down_by_text_added_above_are_found_again(self):
        """The common change while away: something was written above. The very lines, standing in one place, are it."""
        got = self._run(
            """
            SOURCE.notes=['# T','','a new paragraph','','first','second','third'];
            QUEUE=[mdrec(1,3,'first\\nsecond')]; ANSWERS={pick:[],pin:[{id:12}]};
            offlineFlush().then(function(){console.log(JSON.stringify({lo:PINS_SENT[0].lo,hi:PINS_SENT[0].hi,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"lo": 5, "hi": 6, "left": 0})

    def test_lines_that_changed_are_held_not_written_at_their_old_numbers(self):
        got = self._run(
            """
            SOURCE.notes=['# T','','first, reworded','second','third'];
            QUEUE=[mdrec(1,3,'first\\nsecond')]; ANSWERS={pick:[],pin:[{id:13}]};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length,
              held:QUEUE[0].held,why:QUEUE[0].why}));});
            """
        )
        self.assertEqual((got["pins"], got["left"], got["held"]), (0, 1, True))
        self.assertTrue(got["why"])

    def test_lines_that_stand_in_two_places_are_held(self):
        """Moved, and the same lines appear twice: nothing says which of them the pin was on."""
        got = self._run(
            """
            SOURCE.notes=['x','same','y','same','z'];
            QUEUE=[mdrec(1,4,'same')]; SOURCE.notes=['new','x','same','y','same','z']; ANSWERS={pick:[],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,held:QUEUE[0].held}));});
            """
        )
        self.assertEqual(got, {"pins": 0, "held": True})

    def test_lines_still_at_their_numbers_are_that_place_even_if_they_also_stand_elsewhere(self):
        """A repeated line (a blank line, a common phrase) is in many places. Where it was pinned is where it is,
        as long as it still reads the same there - it is only when it has moved that two places leave no answer."""
        got = self._run(
            """
            SOURCE.notes=['x','same','y','same','z'];
            QUEUE=[mdrec(1,4,'same')]; ANSWERS={pick:[],pin:[{id:14}]};
            offlineFlush().then(function(){console.log(JSON.stringify({lo:PINS_SENT[0]&&PINS_SENT[0].lo,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"lo": 4, "left": 0})

    def test_a_source_that_cannot_be_asked_for_leaves_the_record_waiting(self):
        got = self._run(
            """
            SOURCE.notes='down'; QUEUE=[mdrec(1,3,'first')]; ANSWERS={pick:[],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length,held:QUEUE[0].held}));});
            """
        )
        self.assertEqual(got, {"pins": 0, "left": 1, "held": False})


class KeyedSend(unittest.TestCase):
    """A server that knows a write by its key (meta's pin_idem): the record is sent with its key until an answer comes,
    and nothing is looked for in the pin list - the looking is what could mistake one pin for another."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        js = "\n".join([SCOPE, *(extract_js_fn(name) for name in FUNCTIONS), scenario])
        return json.loads(run_node(js))

    def test_the_key_goes_with_every_attempt(self):
        got = self._run(
            """
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a]; ANSWERS={pick:[found(10)],pin:[{id:41}]};
            offlineFlush().then(function(){console.log(JSON.stringify({idem:PINS_SENT[0].idem}));});
            """
        )
        self.assertEqual(got, {"idem": "key-aaaaaaaaaaaaaaaa"})

    def test_a_lost_answer_is_simply_sent_again_and_the_replay_ends_it(self):
        """The first answer never came; the second attempt carries the same key and the server names the same pin."""
        got = self._run(
            """
            OFF.idem=true;
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a];
            // A pin of mine that looks exactly like it is already there: the looking would have taken it for this one.
            OPEN_ALL=[{id:40,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'n1'}];
            ANSWERS={pick:[found(10),found(10)],pin:[{throw:new Error('network')},{id:41,replay:true}]};
            offlineFlush().then(function(){const mid=QUEUE.length;
              return offlineFlush().then(function(){console.log(JSON.stringify({mid:mid,left:QUEUE.length,
                keys:PINS_SENT.map(function(b){return b.idem;}),sent:a.sent}));});});
            """
        )
        self.assertEqual(got["mid"], 1, "no answer: the record waits")
        self.assertEqual(got["left"], 0)
        self.assertEqual(got["keys"], ["key-aaaaaaaaaaaaaaaa", "key-aaaaaaaaaaaaaaaa"])
        self.assertFalse(got["sent"], "the attempt mark belongs to the looking, which is not used")

    def test_a_refusal_is_kept_with_what_the_server_said(self):
        got = self._run(
            """
            OFF.idem=true; const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[{refuse:403}]};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,held:QUEUE[0].held,why:QUEUE[0].why}));});
            """
        )
        self.assertEqual((got["left"], got["held"]), (1, True))
        self.assertTrue(got["why"])

    def test_a_server_without_the_key_is_still_looked_through(self):
        """An older Limn drops the field it does not know: the record must not rely on it there."""
        got = self._run(
            """
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; a.sent=true; QUEUE=[a];
            OPEN_ALL=[{id:41,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'n1'}];
            ANSWERS={pick:[found(10)],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({pins:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"pins": 0, "left": 0})


class OfflineKeys(unittest.TestCase):
    """The key a kept pin is sent with (offline.js offlineKey), and the files a document needs (offlineDocFiles)."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_a_key_fits_what_the_server_takes_with_or_without_randomuuid(self):
        js = "\n".join(
            [
                extract_js_fn("offlineKey"),
                """
                const out=[offlineKey()];
                globalThis.crypto=undefined; out.push(offlineKey()); out.push(offlineKey());
                console.log(JSON.stringify(out));
                """,
            ]
        )
        keys = json.loads(run_node(js))
        for k in keys:
            self.assertRegex(k, r"^[A-Za-z0-9_-]{16,64}$")
        self.assertEqual(len(set(keys)), 3)

    def test_a_documents_files_are_the_addresses_the_viewer_asks_for(self):
        """A copy is found again by its address, so these must be the ones vecOpen and pageSrc build (pdf-open.js,
        pages.js) for that document: the PDF with its build and built_at, each page under its build, both with ?doc=."""
        js = "\n".join(
            [
                extract_js_fn("dq"),
                extract_js_fn("offlineDocFiles"),
                """
                var DOC='ms';
                const m={pages_build:'pages-20261114T090000',built_at:'2026-11-14 09:00:00',pages:[{name:'page-1.png'},{name:'page-2.png'}]};
                console.log(JSON.stringify({rr:offlineDocFiles('rr',m),none:offlineDocFiles('rr',{pages:[]})}));
                """,
            ]
        )
        got = json.loads(run_node(js))
        self.assertEqual(
            got["rr"],
            [
                "/pdf?build=pages-20261114T090000&v=2026-11-14%2009%3A00%3A00&doc=rr",
                "/pages/pages-20261114T090000/page-1.png?doc=rr",
                "/pages/pages-20261114T090000/page-2.png?doc=rr",
            ],
        )
        self.assertEqual(got["none"], [])


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
