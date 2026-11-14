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
var API_WAIT={POLL:8000,READ:8000,PICK:8000,SAVE:10000,SEND:30000};   // api.js: how long a request waits (the real waits are test_viewer_offline_live's)
var POLL_FAILS=0,DEFAULT_DOC='main',DOC='main',META={label:'inst',pages_build:'pages-20261114T090000',pages:[],built_at:'t'};
var OFF_STATE='state',OFF_WROTE='wrote',OFF_WROTE_MAX=500,STATE=new Map();
function offIn(store,mode,fn){const s={put:function(v){STATE.set(v.key,v); return {};},
  get:function(k){return {result:STATE.get(k)};},delete:function(k){STATE.delete(k); return {};}};
  const rq=fn(s); return Promise.resolve(rq&&'result' in rq?rq.result:null);}
var OFF={n:0,held:0,flushing:false,prep:false,db:null};
var QUEUE=[],PICKS=[],PINS_SENT=[],PINS_OK=[],NOTES=[],LOADS=0,OPEN_ALL=[],REVIEW_ALL=[],DONE_ALL=[];
var NOTICE_KIND={OK:'ok',WARN:'warn',ERR:'err',INFO:'info'},NOTICE_LIFE={TIMER:'timer',CLICK:'click'},NOTICE_PLACE={LINE:'line'};
var SOURCE={};   // the source of each document as the server would read it now: {<doc>: [lines]}
var SERVER_IDEM,META_DOWN=false,META_ASKED=0;   // what the server says it can do when asked (undefined: says nothing new)
var KNOWN={},PROBES=[];   // the pins the server has by key ({<idem>: id}, or 'down'), and the keys it was asked about
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
  if(url.indexOf('/api/meta?light=1')===0){META_ASKED++;
    if(META_DOWN)return Promise.reject(new TypeError('Failed to fetch'));
    if(typeof SERVER_IDEM==='boolean')OFF.idem=SERVER_IDEM;   // as offStash does with the real answer
    return Promise.resolve({status:200,data:{pin_idem:OFF.idem}});}
  if(url.indexOf('/api/source?doc=')===0){const k=decodeURIComponent(url.split('doc=')[1]);
    if(SOURCE[k]==='down')return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve({status:200,data:{file:'notes.md',lines:SOURCE[k]||[]}});}
  if(url==='/api/pin'&&o.body&&o.body.replay_only){PROBES.push(o.body.idem);
    if(KNOWN==='down')return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve(KNOWN[o.body.idem]?{status:200,data:{id:KNOWN[o.body.idem],replay:true}}
      :{status:409,data:{error:'unknown',reason:'idem_unknown'}});}
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
var STORE=new Map(),FOLLOW_SEEN=[],KEPT=null;
function offKept(){return Promise.resolve(KEPT);}   // the kept record (tested in KeptCopyFollows)
function offlineFollowSeen(d){FOLLOW_SEEN.push(d);}   // what a meta answer tells the follow (tested in KeptCopyFollows)
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
        names = ("offReadKey", "offStash", "offStashed", "offKeptMeta")
        js = "\n".join([STORE_SCOPE, *(extract_js_fn(n) for n in names), scenario])
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

    def test_a_meta_read_is_answered_with_the_build_kept_whole_not_the_last_one_seen(self):
        """The server moved to B2 and the screen read its meta, but the follow had not fetched B2 when the connection
        went. A tab opened again is drawn from B1 - every file of it is here - not from B2 with pages missing. Once
        the follow has kept B2 the last meta read is the answer again."""
        got = self._run(
            """
            const m1={doc:'main',pages_build:'pages-B1',pages:[1,2]},m2={doc:'main',pages_build:'pages-B2',pages:[1,2,3]};
            offStash('/api/meta?doc=main',m2,200);
            KEPT={key:'kept',docs:{main:{build:'pages-B1',files:[],at:1,seen:7,meta:m1}},old:[]};
            offStashed('/api/meta?doc=main',null).then(function(a){
              KEPT.docs.main={build:'pages-B2',files:[],at:2,seen:9,meta:m2};
              return offStashed('/api/meta?doc=main',null).then(function(b){
                console.log(JSON.stringify({a:[a.data.pages_build,a.status,a.at],b:b.data.pages_build}));});});
            """
        )
        self.assertEqual(got, {"a": ["pages-B1", 200, 7], "b": "pages-B2"})

    def test_what_the_kept_build_s_meta_stands_in_for(self):
        """Only a document this browser keeps on another build than the last meta read, and only with the meta that
        build was kept with: never for an instance not kept, a document not kept, a Markdown document (no build), a
        record made before the meta was carried, or a carried meta that is not of the build recorded. A read with no
        document in its answer is told apart by its address."""
        got = self._run(
            """
            const m1={doc:'main',pages_build:'pages-B1'},last={doc:'main',pages_build:'pages-B2'};
            const rec=function(e){return {key:'kept',docs:{main:e},old:[]};};
            const is=function(v){return v?v.data.pages_build:null;};
            console.log(JSON.stringify({
              swapped:is(offKeptMeta(rec({build:'pages-B1',meta:m1,seen:3}),'/api/meta?doc=main',last)),
              same:is(offKeptMeta(rec({build:'pages-B2',meta:last}),'/api/meta?doc=main',last)),
              never:is(offKeptMeta(null,'/api/meta?doc=main',last)),
              other:is(offKeptMeta({key:'kept',docs:{rr:{build:'pages-B1',meta:m1}},old:[]},'/api/meta?doc=main',last)),
              markdown:is(offKeptMeta(rec({build:'',src:5,meta:null}),'/api/meta?doc=main',{doc:'main'})),
              before:is(offKeptMeta(rec({build:'pages-B1'}),'/api/meta?doc=main',last)),
              wrong:is(offKeptMeta(rec({build:'pages-B1',meta:{doc:'main',pages_build:'pages-B0'}}),'/api/meta?doc=main',last)),
              byAddress:is(offKeptMeta(rec({build:'pages-B1',meta:m1}),'/api/meta?x=1&doc=main',{pages_build:'pages-B2'})),
              noDoc:is(offKeptMeta({key:'kept',docs:{'':{build:'pages-B1',meta:{pages_build:'pages-B1'}}},old:[]},'/api/meta',{pages_build:'pages-B2'}))}));
            """
        )
        self.assertEqual(
            got,
            {
                "swapped": "pages-B1",
                "same": None,
                "never": None,
                "other": None,
                "markdown": None,
                "before": None,
                "wrong": None,
                "byAddress": "pages-B1",
                "noDoc": "pages-B1",
            },
        )

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

    def test_a_meta_answer_says_whether_the_server_counts_a_hold_per_holder(self):
        """As the key: every meta answer carries it, and one without it is a server with one hold per build - where
        this browser lets go of nothing."""
        got = self._run(
            """
            const seen=[];
            offStash('/api/meta?light=1',{hold_holder:true},200,null); seen.push(OFF.holder);
            offStash('/api/pins?all=1',[],200,null); seen.push(OFF.holder);
            offStash('/api/meta?doc=ms',{pages:[]},200,null); seen.push(OFF.holder);
            offStash('/api/meta',{hold_holder:true},500,null); seen.push(OFF.holder);
            console.log(JSON.stringify(seen));
            """
        )
        self.assertEqual(got, [True, True, False, False])

    def test_every_meta_answer_and_only_a_meta_answer_tells_the_follow_what_the_server_shows(self):
        """A kept copy learns that a document's build moved from the meta answers the viewer already gets - the light
        poll's above all - so following adds no request of its own. A refusal says nothing about the builds."""
        got = self._run(
            """
            offStash('/api/meta?light=1&doc=main',{doc:'main',pages_build:'pages-2'},200,null);
            offStash('/api/meta?doc=ms',{doc:'ms',pages_build:'pages-3'},200,null);
            offStash('/api/pins?all=1',[],200,null);
            offStash('/api/docs',{docs:[]},200,null);
            offStash('/api/meta',{error:'x'},500,null);
            console.log(JSON.stringify(FOLLOW_SEEN.map(function(d){return d.pages_build;})));
            """
        )
        self.assertEqual(got, ["pages-2", "pages-3"])

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
var API_WAIT={POLL:8000,READ:8000,PICK:8000,SAVE:10000,SEND:30000},API_OUT=false;   // api.js's own, beside api()
function offReadKey(url,o){return (!o||!o.method||o.method==='GET')&&url==='/api/pins?all=1'?url:null;}   // the one read with a store here
// What fetch does: 'down' rejects as a lost connection does, 'up' answers, 'mute' neither - the request waits until
// its signal ends it, and for ever if it was given none (a tailnet with no internet behind it).
var NET='down',ASKED=0;
globalThis.fetch=function(url,init){ASKED++;
  if(NET==='mute')return new Promise(function(res,rej){if(init&&init.signal)init.signal.addEventListener('abort',function(){rej(new Error('ended'));});});
  return NET==='down'?Promise.reject(new TypeError('Failed to fetch'))
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
        names = ("offlineNow", "offlineMayServe", "offStaleSaid", "offlineBack", "apiUnanswered", "api")
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

    def test_a_read_left_waiting_is_ended_at_its_wait_and_is_a_read_that_failed(self):
        """The server neither refuses nor answers. A read with a stored answer waits API_WAIT.READ and no longer: on a
        visit's first reads the store answers, and while the viewer is connected the failure is said."""
        got = self._run(
            """
            NET='mute'; API_WAIT.READ=20; OFF.boot=true;
            read().then(function(first){OFF.boot=false; API_OUT=false;
              return read().then(function(second){console.log(JSON.stringify({first:first,second:second,said:SAID.length}));});});
            """
        )
        self.assertEqual(got, {"first": "stored", "second": "failed", "said": 1})

    def test_once_a_request_went_unanswered_the_first_reads_do_not_ask(self):
        """A visit's first reads are made one after another. After one that got no answer the store answers the rest
        without a request each - until anything answers: then reads ask again."""
        got = self._run(
            """
            OFF.boot=true;
            read().then(function(){const one=ASKED;
              return read().then(function(v){const two=ASKED; NET='up';
                return api('/api/meta?light=1',{silent:true}).then(function(){
                  return read().then(function(w){console.log(JSON.stringify({one:one,two:two,second:v,after:w,asked:ASKED}));});});});});
            """
        )
        self.assertEqual(got, {"one": 1, "two": 1, "second": "stored", "after": "fresh", "asked": 3})

    def test_a_request_with_no_wait_is_not_ended(self):
        """A rebuild or a revision's build takes as long as the server needs: only a request given a wait, and a read
        with a stored answer, is ended. A wait the caller gives ends any request."""
        got = self._run(
            """
            NET='mute'; const seen={};
            api('/api/rebuild?async=1',{method:'POST',silent:true}).then(function(){seen.slow='answered';},function(){seen.slow='ended';});
            api('/api/pick',{method:'POST',silent:true,wait:20}).then(function(){seen.pick='answered';},function(){seen.pick='ended';})
              .then(function(){setTimeout(function(){console.log(JSON.stringify({slow:seen.slow||'waiting',pick:seen.pick,out:API_OUT})); process.exit(0);},60);});
            """
        )
        self.assertEqual(got, {"slow": "waiting", "pick": "ended", "out": True})


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

    def test_a_lost_answer_is_asked_about_by_the_key_and_that_ends_it(self):
        """The first answer never came, but the write landed. The next visit asks by the key alone and drops the
        record - without placing it again, and without looking through the pin list for something like it."""
        got = self._run(
            """
            OFF.idem=true;
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a];
            // A pin of mine that looks exactly like it is already there: the looking would have taken it for this one.
            OPEN_ALL=[{id:40,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'n1'}];
            ANSWERS={pick:[found(10)],pin:[{throw:new Error('network')}]};
            offlineFlush().then(function(){const mid=QUEUE.length,mark=QUEUE[0].sent;
              KNOWN['key-aaaaaaaaaaaaaaaa']=41;   // it had been written
              return offlineFlush().then(function(){console.log(JSON.stringify({mid:mid,mark:mark,left:QUEUE.length,
                writes:PINS_SENT.length,asked:PROBES,picks:PICKS.length}));});});
            """
        )
        self.assertEqual((got["mid"], got["mark"]), (1, True), "no answer: the record waits, marked as attempted")
        self.assertEqual(got["left"], 0)
        self.assertEqual(got["writes"], 1, "the pin is not written a second time")
        self.assertEqual(got["asked"], ["key-aaaaaaaaaaaaaaaa"])
        self.assertEqual(got["picks"], 1, "and it is not placed again")

    def test_a_pin_that_was_written_is_recovered_even_when_its_place_is_gone(self):
        """What blocked the recovery: the place is looked for first, and by now it is gone - the held build expired,
        or the lines were edited by whoever handled that very pin. Held there, the key was never tried and the pin
        stood on the server while its record stayed in the queue."""
        got = self._run(
            """
            OFF.idem=true;
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; a.sent=true; QUEUE=[a];
            KNOWN['key-aaaaaaaaaaaaaaaa']=41;
            ANSWERS={pick:[{error:'pdf_build_gone',pdf_build_gone:true}],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,held:OFF.held,
              picks:PICKS.length,writes:PINS_SENT.length}));});
            """
        )
        self.assertEqual(got, {"left": 0, "held": 0, "picks": 0, "writes": 0})

    def test_an_attempt_that_never_reached_the_server_is_placed_and_written(self):
        """The key is unknown there: nothing was written, so the record goes on as any other."""
        got = self._run(
            """
            OFF.idem=true;
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; a.sent=true; QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[{id:41}]};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,asked:PROBES.length,
              writes:PINS_SENT.map(function(b){return [b.idem,b.lo,!!b.replay_only];})}));});
            """
        )
        self.assertEqual(got, {"left": 0, "asked": 1, "writes": [["key-aaaaaaaaaaaaaaaa", 10, False]]})

    def test_a_key_the_server_does_not_know_takes_the_attempt_mark_off(self):
        """The server says no pin was made by this key, and the place is gone too: the record is held, and it is no
        longer one that may be on the server - which is what lets [다시 찍기] take it back (offline-ui.js)."""
        got = self._run(
            """
            OFF.idem=true;
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; a.sent=true; QUEUE=[a];
            ANSWERS={pick:[{error:'pdf_build_gone',pdf_build_gone:true}],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,held:QUEUE[0].held,
              sent:QUEUE[0].sent,asked:PROBES.length,writes:PINS_SENT.length}));});
            """
        )
        self.assertEqual(got, {"left": 1, "held": True, "sent": False, "asked": 1, "writes": 0})

    def test_a_question_with_no_answer_leaves_the_attempt_mark_on(self):
        """No answer is not 'unknown': the pin may be there, so the record stays one that may be on the server."""
        got = self._run(
            """
            OFF.idem=true; KNOWN='down';
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; a.sent=true; QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[]};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,sent:QUEUE[0].sent}));});
            """
        )
        self.assertEqual(got, {"left": 1, "sent": True})

    def test_a_question_with_no_answer_leaves_the_record_as_it_was(self):
        """Not placed, not held: nothing is known yet."""
        got = self._run(
            """
            OFF.idem=true; KNOWN='down';
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; a.sent=true; QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[{id:41}]};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,held:QUEUE[0].held,
              picks:PICKS.length,writes:PINS_SENT.length}));});
            """
        )
        self.assertEqual(got, {"left": 1, "held": False, "picks": 0, "writes": 0})

    def test_a_lost_answer_is_never_settled_by_a_pin_that_looks_like_it(self):
        """Where the server knows the key, the pin list is not looked through at all. A pin of mine that appears
        meanwhile at the same lines with the same note - from another device, say - is not this record's write, and
        the looking would have dropped the record on its strength."""
        got = self._run(
            """
            OFF.idem=true; const a=rec(1,'alike'); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a];
            ANSWERS={pick:[found(10),found(10)],pin:[{throw:new Error('network')},{id:61}]};
            const realLoad=loadPins; let reads=0;
            loadPins=function(){reads++;
              if(reads===2)OPEN_ALL=[{id:50,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'alike'}];
              return realLoad();};
            offlineFlush().then(function(){const mid=QUEUE.length;
              return offlineFlush().then(function(){console.log(JSON.stringify({mid:mid,left:QUEUE.length,
                written:PINS_OK,asked:PROBES.length}));});});
            """
        )
        self.assertEqual(got["mid"], 1, "the look-alike does not answer for it")
        self.assertEqual((got["left"], got["written"], got["asked"]), (0, [61], 1))

    def test_the_server_is_asked_what_it_can_do_before_a_way_of_sending_is_chosen(self):
        """What it could do when last heard from is not what it can do now. A tab drawn from stored reads has heard
        nothing this visit; a server may have been rolled back to a Limn that drops the key."""
        got = self._run(
            """
            // Last heard: keyed. Now: rolled back. The question by key alone must not be put to a server that would
            // read it as a pin with no place.
            OFF.idem=true; SERVER_IDEM=false;
            const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; a.sent=true; a.top=0; QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[{id:41}]};
            offlineFlush().then(function(){
              // Last heard: nothing (a visit drawn from stored reads). Now: keyed.
              OFF.idem=false; SERVER_IDEM=true;
              const b=rec(2); b.idem='key-bbbbbbbbbbbbbbbb'; b.sent=true; QUEUE=[b]; KNOWN['key-bbbbbbbbbbbbbbbb']=77;
              const before=PROBES.length;
              return offlineFlush().then(function(){console.log(JSON.stringify({rolledBackAsked:before,
                keyedAsked:PROBES.length-before,left:QUEUE.length,metaAsked:META_ASKED}));});});
            """
        )
        self.assertEqual(got["rolledBackAsked"], 0, "a server without the key is not asked by the key")
        self.assertEqual(got["keyedAsked"], 1, "a server with it is, though this visit had not heard so yet")
        self.assertEqual((got["left"], got["metaAsked"]), (0, 2))

    def test_no_answer_about_what_the_server_can_do_sends_nothing(self):
        """The connection is not there after all; and the send is free to start again when it is."""
        got = self._run(
            """
            META_DOWN=true; QUEUE=[rec(1)]; ANSWERS={pick:[found(10)],pin:[{id:41}]};
            offlineFlush().then(function(){const first={picks:PICKS.length,left:QUEUE.length,busy:OFF.flushing};
              META_DOWN=false;
              return offlineFlush().then(function(){console.log(JSON.stringify({first:first,left:QUEUE.length}));});});
            """
        )
        self.assertEqual(got["first"], {"picks": 0, "left": 1, "busy": False})
        self.assertEqual(got["left"], 0)

    def test_a_rolled_back_server_does_not_let_an_older_look_alike_answer_for_a_keyed_attempt(self):
        """The attempt was made by key and wrote nothing (a 5xx). The server then goes back to a Limn without the key,
        and the record is looked for in the list. The attempt has to have noted the pins that existed before it, or
        any older pin like it answers for it and the record is deleted unwritten."""
        got = self._run(
            """
            OFF.idem=true;
            OPEN_ALL=[{id:40,author:'me',doc:'main',file:'main.tex',lo:10,hi:11,note:'alike'}];   // there before the attempt
            const a=rec(1,'alike'); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a];
            ANSWERS={pick:[found(10),found(10)],pin:[{refuse:500},{id:41}]};
            offlineFlush().then(function(){const top=QUEUE[0].top;
              SERVER_IDEM=false;   // rolled back
              return offlineFlush().then(function(){console.log(JSON.stringify({top:top,written:PINS_OK,left:QUEUE.length}));});});
            """
        )
        self.assertEqual(got["top"], 40, "the keyed attempt notes what existed before it")
        self.assertEqual((got["written"], got["left"]), ([41], 0))

    def test_a_rolled_back_server_does_not_let_a_twin_s_pin_answer_for_a_keyed_attempt(self):
        """Two records alike; one written by key, the other's keyed attempt wrote nothing. Looked for after a
        rollback, the first's pin must be known as this queue's own - the keyed write records it too."""
        got = self._run(
            """
            OFF.idem=true;
            const a=rec(1,'twin'),b=rec(2,'twin'); a.idem='key-aaaaaaaaaaaaaaaa'; b.idem='key-bbbbbbbbbbbbbbbb';
            QUEUE=[a,b];
            ANSWERS={pick:[found(10),found(10),found(10)],pin:[{refuse:500},{id:72},{id:73}]};
            offlineFlush().then(function(){
              SERVER_IDEM=false;   // rolled back
              return offlineFlush().then(function(){console.log(JSON.stringify({written:PINS_OK,left:QUEUE.length}));});});
            """
        )
        self.assertEqual(got, {"written": [72, 73], "left": 0})

    def test_a_record_never_sent_is_not_asked_about(self):
        got = self._run(
            """
            OFF.idem=true; const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[{id:41}]};
            offlineFlush().then(function(){console.log(JSON.stringify({asked:PROBES.length,writes:PINS_SENT.length,left:QUEUE.length}));});
            """
        )
        self.assertEqual(got, {"asked": 0, "writes": 1, "left": 0})

    def test_a_refusal_is_kept_with_what_the_server_said(self):
        got = self._run(
            """
            OFF.idem=true; const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[{refuse:403}]};
            offlineFlush().then(function(){console.log(JSON.stringify({left:QUEUE.length,held:QUEUE[0].held,why:QUEUE[0].why,
              sent:QUEUE[0].sent}));});
            """
        )
        self.assertEqual((got["left"], got["held"]), (1, True))
        self.assertTrue(got["why"])
        self.assertFalse(
            got["sent"], "the server said no: nothing was written, so there is nothing to ask about next time"
        )

    def test_a_server_error_is_not_a_refusal(self):
        """A 5xx may follow a write that went through. The record is not held as refused; it stays marked as
        attempted, so the next visit asks by the key before doing anything else."""
        got = self._run(
            """
            OFF.idem=true; const a=rec(1); a.idem='key-aaaaaaaaaaaaaaaa'; QUEUE=[a];
            ANSWERS={pick:[found(10)],pin:[{refuse:502}]};
            offlineFlush().then(function(){const first={held:QUEUE[0].held,sent:QUEUE[0].sent};
              KNOWN['key-aaaaaaaaaaaaaaaa']=41;   // the gateway's 502 came back over a write that had landed
              return offlineFlush().then(function(){console.log(JSON.stringify({first:first,left:QUEUE.length,
                asked:PROBES.length,writes:PINS_SENT.length}));});});
            """
        )
        self.assertEqual(got["first"], {"held": False, "sent": True})
        self.assertEqual((got["left"], got["asked"], got["writes"]), (0, 1, 1))

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


def _shipped_const(name):
    """The line of offline.js declaring name - the constants a pulled function reads, as shipped."""
    src = (Path(__file__).resolve().parent.parent / "js" / "offline.js").read_text(encoding="utf-8")
    m = re.search(r"^const %s=[^;]*;" % name, src, re.M)
    assert m, name
    return m.group(0)


# The page scope the follow runs in: the kept record and the queue (stand-ins for the state store and the pins store), the
# worker's cache, the server (meta per document, holds) and the clock. LOG says what went out, in order.
FOLLOW_SCOPE = r"""
var API_WAIT={POLL:8000,READ:8000,PICK:8000,SAVE:10000,SEND:30000};   // api.js: how long a request waits (the real waits are test_viewer_offline_live's)
var NOW=1800000000000; Date.now=function(){return NOW;};
var ONLINE=true; function offlineNow(){return !ONLINE;}
var DOC='main',OFF_STATE='state';
var OFF={n:0,held:0,flushing:false,prep:false,following:false,kept:undefined,keptAt:0,seen:{},timer:undefined,fails:0,after:0,failSaid:false,holder:false,me:''};
var ME='me-aaaaaaaaaaaaaaaa'; function offHolderId(){return Promise.resolve(ME);}   // this browser's name among a build's holders
var SHOWN=0; function offKeptShow(){SHOWN++;}   // [더보기]'s row says the instance is kept (read in the real viewer, test_viewer_offline_ui)
var DOC_KIND={MARKDOWN:'markdown',TEXT:'text'}; function rendersInBrowser(k){return k===DOC_KIND.MARKDOWN||k===DOC_KIND.TEXT;}
var NOTICE_KIND={OK:'ok',WARN:'warn',ERR:'err',INFO:'info'},NOTES=[]; function lineNote(msg,kind,act){NOTES.push({msg:msg,kind:kind,act:!!act}); return {};}
function offlinePrepare(){}
var copy=function(v){return v==null?null:JSON.parse(JSON.stringify(v));};
var KEPT=null;   // the state store's kept record, as two tabs of one browser share it
function offKept(){return Promise.resolve(copy(KEPT));}
function offKeptUpdate(fn){const v=fn(copy(KEPT)); if(v)KEPT=copy(v); return Promise.resolve(v||null);}
var QUEUE=[],QUEUE_DOWN=false;   // the pins store; QUEUE_DOWN: the read fails, as IndexedDB answers null
function offTx(mode,fn){return Promise.resolve(QUEUE_DOWN?null:QUEUE.slice());}
var CACHE=new Set(),FAIL=[],WORKER_DOWN=false,LOG=[],SLOW=[];
function later(n,v){return n?new Promise(function(r){setImmediate(r);}).then(function(){return later(n-1,v);}):Promise.resolve(v);}
function offlineAsk(msg){if(WORKER_DOWN)return Promise.resolve(null);
  if(msg.type==='keep'&&msg.urls.some(function(u){return SLOW.some(function(f){return u.indexOf(f)>=0;});}))
    return later(20).then(function(){const s=SLOW; SLOW=[]; return offlineAsk(msg).finally(function(){SLOW=s;});});
  if(msg.type==='keep'){LOG.push('keep '+msg.urls.length);
    const failed=msg.urls.filter(function(u){return FAIL.some(function(f){return u.indexOf(f)>=0;});});
    msg.urls.forEach(function(u){if(failed.indexOf(u)<0)CACHE.add(u);});
    if(ON_KEEP)ON_KEEP();
    return Promise.resolve({kept:msg.urls.length-failed.length,failed:failed});}
  if(msg.type==='drop'){LOG.push('drop '+msg.urls.length); let n=0; msg.urls.forEach(function(u){if(CACHE.delete(u))n++;});
    return Promise.resolve({dropped:n});}
  throw new Error('unexpected ask '+msg.type);}
var ON_KEEP=null;
// The server: each document's kind, build and source time now; the holds it has; whether it has the hold route at all.
// COUNTS: the server counts a hold per holder (SHARES: build -> the holders with a share); else a hold is one per build.
// LET_GO_DOWN: a hold let go (days 0) gets no answer.
var SERVER={main:{kind:'tex',build:'pages-B2',src:2}},HOLDS={},HOLD_ROUTE=true,HOLD_REFUSE=0,DOWN=false,COUNTS=false,SHARES={},NAMED=[],LET_GO_DOWN=false;
function metaOf(k){const s=SERVER[k]; return {doc:k,kind:s.kind,pages_build:s.build,built_at:'at-'+s.build,src_mtime:s.src,
  pages:[{name:'page-1.png'},{name:'page-2.png'}]};}
function api(url,o){const method=(o&&o.method)||'GET',path=url.split('?')[0];
  const k=decodeURIComponent((url.split('doc=')[1]||DOC).split('&')[0]);
  if(DOWN||!ONLINE){LOG.push('down '+path); return Promise.reject(new TypeError('Failed to fetch'));}
  if(path==='/api/meta'){LOG.push('meta '+k); const d=metaOf(k); offlineFollowSeen(d);   // as offStash hands every meta answer on
    return Promise.resolve({status:200,data:d});}
  if(path==='/api/outline-labels')return Promise.resolve({status:200,data:{labels:[]}});
  if(['/api/docs','/api/pins','/api/pins/dropped','/api/people'].indexOf(path)>=0)return Promise.resolve({status:200,data:[]});
  if(path==='/api/source'){LOG.push('source '+k); return Promise.resolve({status:200,data:{lines:['x']}});}
  if(path==='/api/hold'){const b=o.body.build,d=o.body.days; LOG.push('hold '+b+' '+d);
    if(HOLD_REFUSE){const e=new Error('HTTP '+HOLD_REFUSE); e.status=HOLD_REFUSE; return Promise.reject(e);}
    if(!HOLD_ROUTE){if((o.expect||[]).indexOf(404)>=0)return Promise.resolve({status:404,data:{error:'not found',reason:'not_found'}});
      const e=new Error('HTTP 404'); e.status=404; return Promise.reject(e);}   // as api() throws a status it was not told to expect
    NAMED.push(o.body.holder===undefined?null:o.body.holder);
    if(d===0&&LET_GO_DOWN)return Promise.reject(new TypeError('Failed to fetch'));
    if(COUNTS){const h=o.body.holder||'',sh=SHARES[b]=SHARES[b]||{};
      if(d===0)delete sh[h]; else sh[h]=1;
      if(Object.keys(sh).length)HOLDS[b]=NOW; else{delete HOLDS[b]; delete SHARES[b];}
      return Promise.resolve({status:200,data:{build:b,until:HOLDS[b]?'later':null}});}
    if(d===0)delete HOLDS[b]; else HOLDS[b]=NOW;
    return Promise.resolve({status:200,data:{build:b,until:d?'later':null}});}
  throw new Error('unexpected call '+method+' '+url);}
// navigator.locks as a browser has it: a tab gets the lock unless another holds it (ifAvailable answers null then).
var LOCK_HELD=false,LOCKED=0;
Object.defineProperty(globalThis,'navigator',{configurable:true,value:{locks:{request:function(name,opt,cb){
  if(LOCK_HELD)return Promise.resolve(cb(null)); LOCK_HELD=true; LOCKED++;
  return Promise.resolve(cb({name:name})).finally(function(){LOCK_HELD=false;});}}}});
var TIMERS=[]; setTimeout=function(fn,ms){TIMERS.push({fn:fn,ms:ms}); return TIMERS.length;};
clearTimeout=function(id){if(id)TIMERS[id-1]=null;};
function pending(){return TIMERS.filter(Boolean);}
// The record a press of [오프라인으로 받기] leaves for a document on build b, its copies in the cache.
function keptOn(b,at){const files=offlineDocFiles('main',{pages_build:b,built_at:'at-'+b,pages:[{name:'page-1.png'},{name:'page-2.png'}]});
  files.forEach(function(u){CACHE.add(u);}); HOLDS[b]=NOW; if(COUNTS)(SHARES[b]=SHARES[b]||{})[ME]=1;
  return {key:'kept',docs:{main:{build:b,files:files,at:at===undefined?NOW:at,seen:NOW-1}},old:[]};}
function has(b){return Array.from(CACHE).filter(function(u){return u.indexOf(b)>=0;}).length;}
function out(extra){console.log(JSON.stringify(Object.assign({kept:KEPT&&KEPT.docs.main?KEPT.docs.main.build:null,
  old:KEPT?KEPT.old.map(function(o){return o.build;}):null,b1:has('pages-B1'),b2:has('pages-B2'),
  holds:Object.keys(HOLDS).sort(),log:LOG},extra||{})));}
// A light poll's answer for the document on screen, as offStash hands it on.
function poll(){offlineFollowSeen({doc:'main',kind:SERVER.main.kind,pages_build:SERVER.main.build,src_mtime:SERVER.main.src});}
"""

FOLLOW_FUNCTIONS = (
    "dq",
    "offlineDocFiles",
    "offKeptSet",
    "offSeenIn",
    "offBehind",
    "offFree",
    "offRenewDue",
    "offKeptWith",
    "offKeptHeld",
    "offKeptPart",
    "offHold",
    "offlineFollowSeen",
    "offFollowCheck",
    "offlineFollow",
    "offFollowRun",
    "offFollowDoc",
    "offFollowTidy",
    "offFollowDone",
)


class KeptCopyFollows(unittest.TestCase):
    """A kept copy keeps itself current while connected (offline.js offlineFollow, docs/handbook/viewer.md
    §끊긴 채 보기와 핀 쌓기 '스스로 최신으로').

    What it protects: a person who pressed [오프라인으로 받기] once flies with the build the server is on, held - without
    pressing again after every rebuild - and never with less than they had: the old build goes only once the new one is
    whole, and never while a queued pin was drawn on it.
    """

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        consts = "\n".join(_shipped_const(n) for n in ("OFF_KEEP_CHUNK", "OFF_KEPT"))
        js = "\n".join(
            [
                FOLLOW_SCOPE.replace("var OFF_STATE='state';", ""),
                consts,
                "var OFF_STATE='state';",
                *(extract_js_fn(n) for n in FOLLOW_FUNCTIONS),
                scenario,
            ]
        )
        return json.loads(run_node(js))

    def test_a_changed_build_is_followed_without_pressing_again(self):
        """Kept on B1; the server is on B2. The follow fetches B2 whole, holds it, and only then drops B1's copies - the
        copy is B2's now, with nothing of B1 left on the device. B1's hold is not let go: it lapses on its own."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll();
            offlineFollow().then(function(){out({meta:KEPT.docs.main.meta.pages_build});});
            """
        )
        self.assertEqual((got["kept"], got["old"], got["b1"], got["b2"]), ("pages-B2", [], 0, 3))
        self.assertEqual(got["meta"], "pages-B2", "the build is recorded with the meta it was kept with")
        self.assertEqual(got["holds"], ["pages-B1", "pages-B2"])
        # Everything of the new build comes before anything of the old goes.
        log = got["log"]
        self.assertLess(log.index("hold pages-B2 7"), log.index("drop 3"), log)
        self.assertLess(log.index("keep 3"), log.index("hold pages-B2 7"), log)
        self.assertNotIn("hold pages-B1 0", log)

    def test_a_light_poll_sets_a_follow_going_once_the_build_stands_still(self):
        """A build seen moving sets one follow, after OFF_SETTLE_MS; a later poll with nothing new leaves it as it is,
        and a poll that sees the build move again starts the wait over - a run of builds is followed once, to the last."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT);
            poll(); const one=pending().length,ms=pending()[0].ms,first=OFF.timer;
            poll(); poll(); const still=OFF.timer===first?pending().length:-1;   // the same wait, not one started again
            SERVER.main.build='pages-B3'; poll(); const again=pending().length;
            pending()[0].fn();
            setImmediate(function(){setImmediate(function(){setImmediate(function(){
              out({one:one,ms:ms,still:still,again:again,b3:has('pages-B3')});});});});
            """
        )
        self.assertEqual((got["one"], got["still"], got["again"]), (1, 1, 1))
        self.assertGreaterEqual(got["ms"], 5000, "it waits for things to stand still")
        # Only the last build was fetched.
        self.assertEqual([x for x in got["log"] if x.startswith("meta")], ["meta main"])

    def test_nothing_is_done_when_nothing_changed(self):
        """Kept on the build the server is on, its hold fresh: a poll sets nothing going, and a follow asks nothing."""
        got = self._run(
            """
            SERVER.main.build='pages-B1'; KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT);
            poll(); poll(); const timers=pending().length;
            offlineFollow().then(function(){out({timers:timers});});
            """
        )
        self.assertEqual(got["timers"], 0)
        self.assertEqual(got["log"], [])
        self.assertEqual((got["kept"], got["b1"]), ("pages-B1", 3))

    def test_an_instance_never_kept_fetches_nothing(self):
        """No kept record: a poll that sees a new build sets nothing going, and a follow asks the server nothing."""
        got = self._run(
            """
            OFF.kept=null; OFF.keptAt=NOW; poll(); const timers=pending().length;
            offlineFollow().then(function(){out({timers:timers,cache:CACHE.size});});
            """
        )
        self.assertEqual((got["timers"], got["log"], got["cache"], got["kept"]), (0, [], 0, None))

    def test_a_new_build_half_fetched_leaves_the_old_one_whole(self):
        """One page of B2 cannot be fetched: B1 stays kept, its copies and its hold untouched, and B2 is not held -
        a half build is not one to fly with, nor to follow from. What was fetched of B2 is noted with the old builds,
        never held, and stays while the server still shows B2 (the next try fetches it whole)."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); FAIL=['pages-B2/page-2'];
            offlineFollow().then(function(){out({fails:OFF.fails});});
            """
        )
        self.assertEqual((got["kept"], got["old"], got["b1"], got["b2"]), ("pages-B1", ["pages-B2"], 3, 2))
        self.assertEqual(got["holds"], ["pages-B1"])
        self.assertFalse([x for x in got["log"] if x.startswith("drop") or x.startswith("hold")], got["log"])
        self.assertEqual(got["fails"], 1)

    def test_a_worker_that_does_not_answer_leaves_the_old_one_whole(self):
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); WORKER_DOWN=true;
            offlineFollow().then(function(){out();});
            """
        )
        self.assertEqual((got["kept"], got["b1"], got["holds"]), ("pages-B1", 3, ["pages-B1"]))

    def test_the_connection_lost_while_fetching_leaves_the_old_one_whole_and_is_no_failure(self):
        """Cut off after the first files: nothing is recorded or dropped, and the next connection tries again without
        a wait - a flight leaving is not the follow failing."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll();
            ON_KEEP=function(){ONLINE=false;};
            offlineFollow().then(function(){out({fails:OFF.fails,after:OFF.after});});
            """
        )
        self.assertEqual((got["kept"], got["b1"], got["holds"]), ("pages-B1", 3, ["pages-B1"]))
        self.assertEqual((got["fails"], got["after"]), (0, 0))

    def test_the_build_moving_again_while_fetching_follows_the_last_one(self):
        """B2's pages are gone by the time they are asked for (two more builds came): B1 stays; the poll that sees B3
        sets the next follow at once, which keeps B3 and drops B1."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); FAIL=['pages-B2/'];
            offlineFollow().then(function(){
              const first={kept:KEPT.docs.main.build,b1:has('pages-B1')};
              FAIL=[]; SERVER.main.build='pages-B3'; poll();
              return offlineFollow().then(function(){out({first:first,b3:has('pages-B3'),timers:pending().length});});});
            """
        )
        self.assertEqual(got["first"], {"kept": "pages-B1", "b1": 3})
        self.assertEqual((got["kept"], got["b1"], got["b2"], got["b3"]), ("pages-B3", 0, 0, 3))
        self.assertEqual(got["holds"], ["pages-B1", "pages-B3"])
        # B2 was never held by this browser, and nothing of any hold is let go.
        self.assertNotIn("hold pages-B2 0", got["log"])

    def test_a_server_without_the_hold_route_is_still_followed(self):
        """An older Limn answers the hold 404: that is no failure. The new build is fetched and kept, the old one's
        copies dropped; nothing is held because nothing can be."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); HOLDS={}; HOLD_ROUTE=false; poll();
            offlineFollow().then(function(){out({fails:OFF.fails,at:KEPT.docs.main.at});});
            """
        )
        self.assertEqual((got["kept"], got["old"], got["b1"], got["b2"], got["fails"]), ("pages-B2", [], 0, 3, 0))
        self.assertEqual(got["holds"], [])
        self.assertIsNotNone(got["at"])

    def test_a_hold_with_no_answer_does_not_record_the_new_build(self):
        """The files came, the hold got no answer (a 5xx, or the connection): B2 is not recorded and B1 not dropped -
        a build that is not held may be gone by the time its pins are sent."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); HOLD_REFUSE=503;
            offlineFollow().then(function(){out();});
            """
        )
        self.assertEqual((got["kept"], got["b1"]), ("pages-B1", 3))
        self.assertFalse([x for x in got["log"] if x.startswith("drop")], got["log"])

    def test_an_old_build_a_queued_pin_was_drawn_on_keeps_its_hold_and_its_copies(self):
        """A pin queued on B1 waits. B2 is followed, and B1 stays - held, its copies in the cache - until that pin has
        gone; the follow after that drops its copies (its hold is left to lapse)."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll();
            QUEUE=[{id:1,doc:'main',build:'pages-B1',page:1}];
            offlineFollow().then(function(){
              const first={kept:KEPT.docs.main.build,old:KEPT.old.map(function(o){return o.build;}),b1:has('pages-B1'),
                holds:Object.keys(HOLDS).sort()};
              QUEUE=[];
              return offlineFollow().then(function(){out({first:first});});});
            """
        )
        self.assertEqual(
            got["first"], {"kept": "pages-B2", "old": ["pages-B1"], "b1": 3, "holds": ["pages-B1", "pages-B2"]}
        )
        self.assertEqual((got["old"], got["b1"], got["holds"]), ([], 0, ["pages-B1", "pages-B2"]))

    def test_a_queue_that_cannot_be_read_lets_nothing_go(self):
        """Read as empty, an unreadable queue would let go the build a waiting pin needs."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); QUEUE_DOWN=true;
            offlineFollow().then(function(){out();});
            """
        )
        self.assertEqual((got["kept"], got["old"], got["b1"]), ("pages-B2", ["pages-B1"], 3))
        self.assertEqual(got["holds"], ["pages-B1", "pages-B2"])

    def test_a_pin_kept_on_an_old_build_while_two_new_builds_pass(self):
        """A pin on B1 waits through B2 and B3: B1 stays all along; B2, which no pin was drawn on, goes."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); QUEUE=[{id:1,doc:'main',build:'pages-B1'}]; poll();
            offlineFollow().then(function(){SERVER.main.build='pages-B3'; poll();
              return offlineFollow().then(function(){out({b3:has('pages-B3')});});});
            """
        )
        self.assertEqual((got["kept"], got["old"]), ("pages-B3", ["pages-B1"]))
        self.assertEqual((got["b1"], got["b2"], got["b3"]), (3, 0, 3))
        self.assertEqual(got["holds"], ["pages-B1", "pages-B2", "pages-B3"])
        self.assertNotIn("hold pages-B1 0", got["log"])

    def test_this_browser_lets_go_of_its_own_share_and_another_device_s_keeps_the_build(self):
        """The server counts a hold per holder. A tablet of the same person, cut off, has pins queued on B1 and its own
        share of B1's hold. This browser follows to B2: B1's copies leave this device and its own share is let go - by
        its name - and B1 stays held for the tablet. Nothing of B1 is asked again here."""
        got = self._run(
            """
            COUNTS=true; OFF.holder=true; KEPT=keptOn('pages-B1'); SHARES['pages-B1'].tablet=1; OFF.kept=copy(KEPT); poll();
            offlineFollow().then(function(){const first=LOG.slice(),named=NAMED.slice(); LOG.length=0; NOW+=25*3600000;
              return offlineFollow().then(function(){out({first:first,named:named,
                shares:Object.keys(SHARES['pages-B1']||{})});});});
            """
        )
        self.assertEqual((got["kept"], got["old"], got["b1"]), ("pages-B2", [], 0))
        self.assertEqual(got["first"][-2:], ["drop 3", "hold pages-B1 0"])
        self.assertEqual(set(got["named"]), {"me-aaaaaaaaaaaaaaaa"}, "every hold, kept or let go, names this browser")
        self.assertEqual(got["shares"], ["tablet"])
        self.assertIn("pages-B1", got["holds"])
        self.assertEqual(got["log"], ["hold pages-B2 7"], "a day later only the build kept is asked again")

    def test_the_last_share_let_go_ends_the_hold(self):
        """No other device holds B1: once this browser lets go, the server holds B2 alone - nothing piles up to push
        another device's hold past the limit."""
        got = self._run(
            """
            COUNTS=true; OFF.holder=true; KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll();
            offlineFollow().then(function(){out();});
            """
        )
        self.assertEqual((got["kept"], got["old"], got["b1"], got["holds"]), ("pages-B2", [], 0, ["pages-B2"]))

    def test_a_share_let_go_with_no_answer_is_let_go_on_the_next_try(self):
        """The copies are gone but the server did not hear the share was let go: the build stays in the old list, the
        follow counts as not done, and the next one lets go."""
        got = self._run(
            """
            COUNTS=true; OFF.holder=true; KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); LET_GO_DOWN=true;
            offlineFollow().then(function(){const mid={old:KEPT.old.map(function(o){return o.build;}),fails:OFF.fails,
                held:Object.keys(HOLDS).sort()};
              LET_GO_DOWN=false; NOW+=3600000;
              return offlineFollow().then(function(){out({mid:mid});});});
            """
        )
        self.assertEqual(got["mid"], {"old": ["pages-B1"], "fails": 1, "held": ["pages-B1", "pages-B2"]})
        self.assertEqual((got["old"], got["holds"]), ([], ["pages-B2"]))

    def test_a_build_half_fetched_was_never_held_here_and_is_not_let_go(self):
        """A build whose files did not all come was never held by this browser (unheld): its copies go in turn, and no
        share is let go for it."""
        got = self._run(
            """
            COUNTS=true; OFF.holder=true; KEPT=keptOn('pages-B2');
            KEPT.old=[{doc:'main',build:'pages-B1',files:[],at:0,unheld:true}]; OFF.kept=copy(KEPT); poll();
            offlineFollow().then(function(){out();});
            """
        )
        self.assertEqual(got["old"], [])
        self.assertNotIn("hold pages-B1 0", got["log"])

    def test_a_dropped_build_s_hold_is_never_let_go_nor_asked_again(self):
        """A server with one hold per build (it does not say hold_holder): another device of the same person, cut off,
        may have pins queued on B1 that this browser cannot see, and letting go would take the build from it. So B1's
        copies leave this device, but its hold is neither let go nor asked again - it lapses in 7 days - while B2's is
        asked again the next day."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll();
            offlineFollow().then(function(){LOG.length=0; NOW+=25*3600000;
              return offlineFollow().then(function(){out();});});
            """
        )
        self.assertEqual((got["kept"], got["old"], got["b1"]), ("pages-B2", [], 0))
        self.assertEqual(got["log"], ["hold pages-B2 7"])
        self.assertIn("pages-B1", got["holds"])

    def test_holds_are_asked_again_once_a_day(self):
        """A hold answered 23 hours ago is left; at 25 hours it is asked again for 7 days - the build each document
        keeps and an old build a queued pin still needs. A poll sets that going on its own."""
        got = self._run(
            """
            SERVER.main.build='pages-B1'; KEPT=keptOn('pages-B1',NOW-23*3600000);
            KEPT.old=[{doc:'main',build:'pages-B0',files:[],at:NOW-25*3600000}]; QUEUE=[{id:1,doc:'main',build:'pages-B0'}];
            OFF.n=1; OFF.kept=copy(KEPT); poll(); const early=pending().length;
            offlineFollow().then(function(){const a=LOG.slice(); LOG.length=0;
              NOW+=2*3600000; poll(); const late=pending().length;
              return offlineFollow().then(function(){out({early:early,late:late,a:a,at:KEPT.docs.main.at===NOW});});});
            """
        )
        self.assertEqual(got["a"], ["hold pages-B0 7"], "only the old build's hold was due")
        self.assertEqual(got["early"], 1)
        self.assertEqual(got["late"], 1)
        self.assertEqual(got["log"], ["hold pages-B1 7"])
        self.assertTrue(got["at"])

    def test_two_follows_started_together_run_once(self):
        """Reconnecting answers several polls in one tick: the flag is taken before anything is awaited."""
        got = self._run(
            """
            delete navigator.locks;   // this tab's own flag, not the lock among tabs
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll();
            Promise.all([offlineFollow(),offlineFollow()]).then(function(){out();});
            """
        )
        self.assertEqual([x for x in got["log"] if x.startswith("meta")], ["meta main"])
        self.assertEqual(got["kept"], "pages-B2")

    def test_a_follow_another_tab_is_running_is_not_run_again_here(self):
        """Two tabs of one browser share the cache and the store: while one holds the lock the other does nothing."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); LOCK_HELD=true;
            offlineFollow().then(function(){out({following:OFF.following});});
            """
        )
        self.assertEqual((got["log"], got["kept"], got["following"]), ([], "pages-B1", False))

    def test_two_tabs_following_at_once_end_as_one_would(self):
        """Without a lock both follow. Tab A reads B2, tab B a moment later reads B3; A's fetch is slower, so A writes
        last. The newer reading still wins, and every file A fetched is accounted for and dropped: what is left on the
        device is B3's copies, nothing of B1 or B2 - as one tab following to B3 would leave."""
        got = self._run(
            """
            delete navigator.locks;
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); SLOW=['pages-B2'];
            const realApi=api,seq=['pages-B2','pages-B3'];
            api=function(url,o){if(url.indexOf('/api/meta')===0&&seq.length){SERVER.main.build=seq.shift(); NOW+=1;} return realApi(url,o);};
            const a=offlineFollow(); OFF.following=false;   // another tab: its own flag
            const b=offlineFollow();
            Promise.all([a,b]).then(function(){out({b3:has('pages-B3')});});
            """
        )
        self.assertEqual((got["kept"], got["old"]), ("pages-B3", []))
        self.assertEqual((got["b1"], got["b2"], got["b3"]), (0, 0, 3))
        self.assertFalse([x for x in got["log"] if x.endswith(" 0")], got["log"])

    def test_nothing_is_followed_while_cut_off_or_while_a_pressed_keep_runs(self):
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); poll(); ONLINE=false;
            offlineFollow().then(function(){ONLINE=true; OFF.prep=true; return offlineFollow();}).then(function(){out();});
            """
        )
        self.assertEqual((got["log"], got["kept"]), ([], "pages-B1"))

    def test_a_press_that_starts_while_following_stops_it_after_the_document_in_hand(self):
        """Two documents are behind; the person presses [오프라인으로 받기] while the first is fetched. The follow does
        not go on to the second, nor drop anything: the press does the work now."""
        got = self._run(
            """
            SERVER.rr={kind:'tex',build:'pages-R2',src:1};
            KEPT=keptOn('pages-B1'); KEPT.docs.rr={build:'pages-R1',files:[],at:NOW,seen:1}; OFF.kept=copy(KEPT);
            offlineFollowSeen({doc:'main',kind:'tex',pages_build:'pages-B2',docs:[{key:'main',kind:'tex',pages_build:'pages-B2'},
              {key:'rr',kind:'tex',pages_build:'pages-R2'}]});
            ON_KEEP=function(){OFF.prep=true; ON_KEEP=null;};
            offlineFollow().then(function(){out({rr:KEPT.docs.rr.build,fails:OFF.fails});});
            """
        )
        self.assertEqual([x for x in got["log"] if x.startswith("meta")], ["meta main"])
        self.assertFalse([x for x in got["log"] if x.startswith("drop")], got["log"])
        self.assertEqual((got["rr"], got["fails"]), ("pages-R1", 0))

    def test_a_document_the_server_no_longer_lists_is_left_as_it_is(self):
        """rr was kept and is gone from the instance: nothing of it is fetched, dropped or let go."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); KEPT.docs.rr={build:'pages-R1',files:['/pages/pages-R1/page-1.png?doc=rr'],at:NOW,seen:1};
            CACHE.add('/pages/pages-R1/page-1.png?doc=rr'); HOLDS['pages-R1']=NOW; OFF.kept=copy(KEPT);
            offlineFollowSeen({doc:'main',kind:'tex',pages_build:'pages-B2',docs:[{key:'main',kind:'tex',pages_build:'pages-B2'}]});
            offlineFollow().then(function(){out({rr:KEPT.docs.rr.build,r1:has('pages-R1')});});
            """
        )
        self.assertEqual((got["rr"], got["r1"]), ("pages-R1", 1))
        self.assertIn("pages-R1", got["holds"])
        self.assertFalse([x for x in got["log"] if "rr" in x or "R1" in x], got["log"])

    def test_a_markdown_document_reads_its_source_again_when_it_changes(self):
        """A Markdown document has no pages: its kept copy is the stored source read, read again when the source time
        moves, and nothing else is fetched or held."""
        got = self._run(
            """
            SERVER={notes:{kind:'markdown',build:'',src:5}};
            KEPT={key:'kept',docs:{notes:{build:'',files:[],at:0,src:4,seen:1}},old:[]}; OFF.kept=copy(KEPT);
            offlineFollowSeen({doc:'notes',kind:'markdown',pages_build:'',src_mtime:5});
            offlineFollow().then(function(){const first=LOG.slice(); LOG.length=0;
              offlineFollowSeen({doc:'notes',kind:'markdown',pages_build:'',src_mtime:5});
              return offlineFollow().then(function(){console.log(JSON.stringify({first:first,then:LOG,src:KEPT.docs.notes.src,
                timers:pending().length}));});});
            """
        )
        self.assertEqual(got["first"], ["meta notes", "source notes"])
        self.assertEqual((got["then"], got["src"]), ([], 5))

    def test_a_document_added_to_a_kept_instance_is_kept_too(self):
        got = self._run(
            """
            SERVER.rr={kind:'tex',build:'pages-R1',src:1}; SERVER.main.build='pages-B1';
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT);
            offlineFollowSeen({doc:'main',kind:'tex',pages_build:'pages-B1',docs:[{key:'main',kind:'tex',pages_build:'pages-B1'},
              {key:'rr',kind:'tex',pages_build:'pages-R1'}]});
            offlineFollow().then(function(){out({rr:KEPT.docs.rr&&KEPT.docs.rr.build,r1:has('pages-R1')});});
            """
        )
        self.assertEqual((got["rr"], got["r1"], got["kept"]), ("pages-R1", 3, "pages-B1"))

    def test_failing_again_and_again_is_said_once_and_waits_longer_each_time(self):
        """A failed follow waits before the next try, longer each time; the third failure in a row is said, once, with a
        way to press the keep again. Success is never said."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); FAIL=['page-1']; poll();
            const waits=[]; let p=Promise.resolve();
            const counts=[];
            for(let i=0;i<4;i++)p=p.then(function(){return offlineFollow();}).then(function(){waits.push(OFF.after-NOW); NOW=OFF.after; counts.push(NOTES.length);});
            p.then(function(){FAIL=[]; return offlineFollow().then(function(){
              out({waits:waits,counts:counts,notes:NOTES,fails:OFF.fails});});});
            """
        )
        w = got["waits"]
        self.assertTrue(all(b > a for a, b in zip(w, w[1:], strict=False)), w)
        self.assertEqual(got["counts"], [0, 0, 1, 1], "said at the third failure in a row, and only then")
        self.assertTrue(got["notes"][0]["act"], "the message offers to keep again")
        self.assertEqual((got["fails"], len(got["notes"]), got["kept"]), (0, 1, "pages-B2"))

    def test_a_failed_follow_waits_unless_something_new_is_seen(self):
        """After a failure a poll with nothing new sets nothing going until the wait is over; a new build is a new
        chance at once."""
        got = self._run(
            """
            KEPT=keptOn('pages-B1'); OFF.kept=copy(KEPT); FAIL=['page-1']; poll();
            offlineFollow().then(function(){TIMERS.length=0; OFF.timer=undefined;   // the follow's own wait has run
              poll(); const waiting=pending().length;
              SERVER.main.build='pages-B3'; poll(); out({waiting:waiting,now:pending().length});});
            """
        )
        self.assertEqual((got["waiting"], got["now"]), (0, 1))


class PressedKeep(unittest.TestCase):
    """[오프라인으로 받기] turns following on, and records each document only once all its files are kept."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        stubs = r"""
        var DOCS=[{key:'main',kind:'tex'},{key:'rr',kind:'tex'}],NOTICES=new Map(),NOTICE_LIFE={TIMER:'t',CLICK:'c'};
        function docInfo(k){return DOCS.find(function(d){return d.key===k;})||null;}
        function offlineWorker(){return Promise.resolve({});} function offlineUrls(){return ['/'];}
        function endNotice(){} function drawStatus(){}
        """
        consts = "\n".join(_shipped_const(n) for n in ("OFF_KEEP_CHUNK", "OFF_KEPT"))
        js = "\n".join(
            [
                FOLLOW_SCOPE.replace("var OFF_STATE='state';", ""),
                consts,
                "var OFF_STATE='state';",
                stubs,
                *(extract_js_fn(n) for n in (*FOLLOW_FUNCTIONS, "offlinePrepare")),
                scenario,
            ]
        )
        return json.loads(run_node(js))

    def test_a_press_records_the_documents_kept_whole_and_the_build_kept_before_goes_old(self):
        """main was kept on B0 and is now on B1; rr's second page cannot be fetched. main is recorded on B1 with B0 among
        the old builds (dropped by the next follow), and rr is not recorded - it is not kept whole, so a follow will
        try it again. A follow is set going to drop B0."""
        got = self._run(
            """
            SERVER={main:{kind:'tex',build:'pages-B1',src:1},rr:{kind:'tex',build:'pages-R1',src:1}};
            KEPT={key:'kept',docs:{main:{build:'pages-B0',files:['/pages/pages-B0/page-1.png?doc=main'],at:1,seen:1}},old:[]};
            FAIL=['pages-R1/page-2'];
            offlinePrepare().then(function(){console.log(JSON.stringify({docs:Object.keys(KEPT.docs).sort(),
              main:KEPT.docs.main.build,old:KEPT.old.map(function(o){return o.build;}),timers:pending().length,
              held:KEPT.docs.main.at===NOW,meta:KEPT.docs.main.meta.pages_build,oldMeta:'meta' in KEPT.old[0]}));});
            """
        )
        self.assertEqual(
            got,
            {
                "docs": ["main"],
                "main": "pages-B1",
                "old": ["pages-B0"],
                "timers": 1,
                "held": True,
                "meta": "pages-B1",  # the meta it was kept with, for a tab opened again with no network
                "oldMeta": False,
            },
        )

    def test_a_press_turns_following_on_even_when_nothing_could_be_kept(self):
        """The person chose this instance; the worker failing this time does not unchoose it."""
        got = self._run(
            """
            SERVER={main:{kind:'tex',build:'pages-B1',src:1},rr:{kind:'tex',build:'pages-R1',src:1}}; WORKER_DOWN=true;
            offlinePrepare().then(function(){console.log(JSON.stringify({on:!!KEPT,docs:Object.keys(KEPT.docs)}));});
            """
        )
        self.assertEqual(got, {"on": True, "docs": []})


class WorkerDrop(unittest.TestCase):
    """sw.js 'drop': the copies kept under exactly the given addresses go - a document's PDF and page images only."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_only_a_documents_own_files_are_dropped_and_only_at_their_exact_address(self):
        sw = (Path(__file__).resolve().parent.parent / "sw.js").read_text(encoding="utf-8")
        js = (
            r"""
        const L={},store=new Map(),O='http://h';
        globalThis.self={location:{origin:O},addEventListener:function(t,f){L[t]=f;},skipWaiting:function(){},clients:{claim:function(){}}};
        globalThis.caches={open:function(){return Promise.resolve({delete:function(r){return Promise.resolve(store.delete(r.url));}});}};
        ['/','/vendor/pdfjs/pdf.min.mjs?v=1','/pdf?build=B1&v=t&doc=main','/pages/B1/page-1.png?doc=main','/pages/B2/page-1.png?doc=main']
          .forEach(function(u){store.set(O+u,1);});
        """
            + sw
            + r"""
        let wait=null;
        L.message({data:{type:'drop',urls:['/','/vendor/pdfjs/pdf.min.mjs?v=1','/pdf?build=B1&v=t&doc=main',
            '/pages/B1/page-1.png?doc=main','/pages/B2/page-1.png','http://elsewhere/pages/B2/page-1.png?doc=main']},
          ports:[{postMessage:function(v){console.log(JSON.stringify({said:v,left:Array.from(store.keys()).map(function(u){return u.slice(O.length);}).sort()}));}}],
          waitUntil:function(p){wait=p;}});
        """
        )
        got = json.loads(run_node(js))
        self.assertEqual(got["said"], {"dropped": 2})
        self.assertEqual(got["left"], ["/", "/pages/B2/page-1.png?doc=main", "/vendor/pdfjs/pdf.min.mjs?v=1"])


class KeptRecord(unittest.TestCase):
    """The pure rules the follow stands on (offline.js offFree, offKeptWith, offBehind)."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")

    def _run(self, scenario):
        js = "\n".join(
            [
                _shipped_const("OFF_KEPT"),
                "function rendersInBrowser(k){return k==='markdown'||k==='text';}",
                *(extract_js_fn(n) for n in ("offFree", "offKeptWith", "offKeptPart", "offBehind", "offSeenIn")),
                scenario,
            ]
        )
        return json.loads(run_node(js))

    def test_a_build_a_queued_pin_was_drawn_on_is_never_free(self):
        got = self._run(
            """
            const old=[{doc:'main',build:'B1'},{doc:'main',build:'B2'},{doc:'rr',build:'B1'},{doc:'rr',build:'R1'}];
            const free=function(q){return offFree(old,q).map(function(o){return o.doc+':'+o.build;});};
            console.log(JSON.stringify({
              none:free([]),
              mine:free([{doc:'main',build:'B1'}]),
              other:free([{doc:'rr',build:'R1'}]),
              nodoc:free([{build:'B1'}]),
              nobuild:free([{doc:'main',build:''},{doc:'main'}]),
            }));
            """
        )
        self.assertEqual(got["none"], ["main:B1", "main:B2", "rr:B1", "rr:R1"])
        self.assertEqual(got["mine"], ["main:B2", "rr:B1", "rr:R1"])
        self.assertEqual(got["other"], ["main:B1", "main:B2", "rr:B1"])
        self.assertEqual(got["nodoc"], ["main:B2", "rr:R1"], "a record with no document protects that build anywhere")
        self.assertEqual(got["nobuild"], ["main:B1", "main:B2", "rr:B1", "rr:R1"])

    def test_the_newer_reading_wins_in_whichever_order_two_tabs_write(self):
        """Tab A read B2 at 10, tab B read B3 at 20, both from B1. Whichever writes first, B3 is kept and B1 and B2 are
        both old - so both are dropped, and nothing either tab fetched is left unaccounted for."""
        got = self._run(
            """
            const start={key:'kept',docs:{main:{build:'B1',files:['f1'],at:1,seen:1}},old:[]};
            const a={build:'B2',files:['f2'],at:10,seen:10},b={build:'B3',files:['f3'],at:20,seen:20};
            const ab=offKeptWith(offKeptWith(start,'main',a),'main',b),ba=offKeptWith(offKeptWith(start,'main',b),'main',a);
            const view=function(k){return {cur:k.docs.main.build,old:k.old.map(function(o){return o.build;}).sort()};};
            const same=offKeptWith(offKeptWith(start,'main',a),'main',{build:'B2',files:['f2'],at:11,seen:11});
            const again=offKeptWith({key:'kept',docs:{main:b},old:[{doc:'main',build:'B2',files:[],at:0}]},'main',{build:'B2',files:[],at:30,seen:30});
            console.log(JSON.stringify({ab:view(ab),ba:view(ba),same:view(same),again:view(again)}));
            """
        )
        self.assertEqual(got["ab"], {"cur": "B3", "old": ["B1", "B2"]})
        self.assertEqual(got["ba"], got["ab"])
        self.assertEqual(got["same"], {"cur": "B2", "old": ["B1"]}, "the same build twice is one build")
        self.assertEqual(got["again"], {"cur": "B2", "old": ["B3"]}, "a build kept again is not old")

    def test_a_half_fetched_build_is_noted_old_unless_it_is_the_one_kept(self):
        """Another tab may keep B2 while this one fails to: B2 is then what main keeps, and noting it old would drop
        the copies the device is to fly with."""
        got = self._run(
            """
            const kept={key:'kept',docs:{main:{build:'B2',files:['f2'],at:1,seen:1}},old:[]};
            const part=offKeptPart(kept,'main','B3',['f3']),twice=offKeptPart(part,'main','B3',['f3','g3']);
            console.log(JSON.stringify({kept:offKeptPart(kept,'main','B2',['f2']),part:part.old,twice:twice.old}));
            """
        )
        self.assertIsNone(got["kept"])
        self.assertEqual(got["part"], [{"doc": "main", "build": "B3", "files": ["f3"], "at": 0, "unheld": True}])
        self.assertEqual(got["twice"], [{"doc": "main", "build": "B3", "files": ["f3", "g3"], "at": 0, "unheld": True}])

    def test_what_is_behind(self):
        got = self._run(
            """
            const kept={docs:{main:{build:'B1'},notes:{src:4},same:{build:'S1'}}};
            const seen=offSeenIn({doc:'main',kind:'tex',pages_build:'B2',docs:[
              {key:'main',kind:'tex',pages_build:'B2'},{key:'notes',kind:'markdown',pages_build:'',src_mtime:5},
              {key:'same',kind:'pdf',pages_build:'S1'},{key:'fresh',kind:'tex',pages_build:''},{key:'new',kind:'tex',pages_build:'N1'}]});
            console.log(JSON.stringify({behind:offBehind(kept,seen),never:offBehind(null,{a:{build:'',kind:'tex'}})}));
            """
        )
        self.assertEqual(sorted(got["behind"]), ["main", "new", "notes"])
        self.assertEqual(got["never"], [])


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

    def test_this_browser_has_one_name_among_a_build_s_holders(self):
        """Made once, of the shape the server takes, and kept in the state store: every later ask - another tab, another
        visit - reads the same name. A stored name of another shape is made again. A browser that refuses the store has
        none, and asks its holds with no name."""
        js = "\n".join(
            [
                """
                var OFF={me:''},OFF_STATE='state',OFF_HOLDER='holder',STORE=new Map(),DB_DOWN=false;
                // The state store as IndexedDB answers it: the request's handler runs later, then the transaction ends.
                function offDb(){if(DB_DOWN)return Promise.resolve(null);
                  return Promise.resolve({transaction:function(){const tx={objectStore:function(){return {
                    get:function(k){const rq={result:STORE.get(k)};
                      setImmediate(function(){rq.onsuccess(); setImmediate(function(){tx.oncomplete();});}); return rq;},
                    put:function(v){STORE.set(v.key,v);}};}}; return tx;}});}
                """,
                extract_js_fn("offlineKey"),
                extract_js_fn("offHolderId"),
                """
                (async function(){
                  const first=await offHolderId(),stored=STORE.get('holder').id;
                  OFF.me=''; const again=await offHolderId();                       // another visit
                  OFF.me=''; STORE.set('holder',{key:'holder',id:'short'}); const remade=await offHolderId();
                  OFF.me=''; DB_DOWN=true; const none=await offHolderId();
                  console.log(JSON.stringify({first:first,same:first===stored&&first===again,remade:remade,
                    kept:STORE.get('holder').id===remade,none:none}));})();
                """,
            ]
        )
        got = json.loads(run_node(js))
        self.assertRegex(got["first"], r"^[A-Za-z0-9_-]{16,64}$")
        self.assertRegex(got["remade"], r"^[A-Za-z0-9_-]{16,64}$")
        self.assertNotEqual(got["remade"], "short")
        self.assertEqual((got["same"], got["kept"], got["none"]), (True, True, ""))

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
