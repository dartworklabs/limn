"""What came while a person was viewing (docs/handbook/viewer.md §새 소식, js/updates.js, notices.js groupNote and the gathering).

The pure rules - the changed lines of a redrawn source, the commits a document's update names and their PR numbers, others'
new pins, the gathered line, how long a person was away, the status item of a newer Limn - run under node with the served
functions; grouping and gathering run under node with the notice store and a fake clock; the flows run in Chromium against
the in-process server on a desktop (1440x900): a Markdown document changed on disk, a co-author's new pin, an agent closing
pins one by one, a reply with the browser-notification switch off, and a return after a while; a newer Limn runs against a
real server process (src/limn/server.py from a copy of the package), its files changed and then restarted.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_updates.py
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

import limn
from limn.administration import serve_documents as startup_documents
from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import HTML, add_pin, extract_js_fn, js_i18n, ps, req, run_node
from helpers_access import ALICE, BOB, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, ChromiumTestCase, settle, until
from helpers_figure import BUILD1, viewer_build
from helpers_notices import SCREENS, SEEN, node_or_skip


def node_json(names, body, lang="ko"):
    """Run body after the served functions names (and the messages of lang); its JSON output."""
    return json.loads(run_node("\n".join([js_i18n(lang)] + [extract_js_fn(n) for n in names] + [body])))


class PureRules(unittest.TestCase):
    """The decisions of updates.js and of the status item it adds, under node."""

    def setUp(self):
        node_or_skip(self)

    def test_changed_lines_are_the_new_lines_that_differ_and_a_removal_marks_the_line_after_it(self):
        """lineChanges: nothing for the same lines; a changed line, an inserted run and two separate places in order; a
        removed line marks the line that now stands where it was (the last line at the end); past the edit steps it may try,
        the whole middle between the common head and tail is one place."""
        got = node_json(
            ["lineChanges"],
            """const a=['a','b','c','d','e','f'];
            console.log(JSON.stringify([
              lineChanges(a,a.slice(),50),
              lineChanges(a,['a','B','c','d','e','f'],50),
              lineChanges(a,['a','b','x','y','c','d','e','f'],50),
              lineChanges(a,['a','B','c','d','E','f'],50),
              lineChanges(a,['a','b','d','e','f'],50),
              lineChanges(a,['a','b','c','d','e'],50),
              lineChanges(['1','2','3','4'],['5','6','7','8'],2),
              lineChanges([],['x'],50)]));""",
        )
        self.assertEqual(
            got,
            [
                [],
                [{"lo": 2, "hi": 2}],
                [{"lo": 3, "hi": 4}],
                [{"lo": 2, "hi": 2}, {"lo": 5, "hi": 5}],
                [{"lo": 3, "hi": 3}],
                [{"lo": 5, "hi": 5}],
                [{"lo": 1, "hi": 4}],
                [{"lo": 1, "hi": 1}],
            ],
        )

    def test_the_commits_above_the_last_seen_one_name_their_prs_authors_and_newest_subject(self):
        """describeCommits and prOf: a squash merge's '(#12)' and a merge commit's 'Merge pull request #13' are PR numbers;
        the commits counted are those above the last seen one (a prefix of it will do), all of them when it is not among
        the rows (more); a merge commit's own subject gives way to the commit under it; no seen commit, or rows not known
        (null), names none and says so (unknown); no rows (no history), nothing."""
        got = node_json(
            ["prOf", "describeCommits"],
            """const rows=[{id:'m1',subject:'Merge pull request #13 from bob/x',author:'Bob Park',time:'t3'},
              {id:'c2',subject:'Fix the axis names',author:'Bob Park',time:'t2'},
              {id:'c1',subject:'Shorten the introduction (#12)',author:'Carol Lee',time:'t1'},
              {id:'c0abcdef',subject:'Initial',author:'A',time:'t0'}];
            console.log(JSON.stringify([prOf('Title (#7)'),prOf('Merge pull request #9 from a/b'),prOf('No PR'),
              describeCommits(rows,'c0a'),describeCommits(rows,'zzz'),describeCommits(rows,''),describeCommits(rows.slice(2),'c0abcdef'),
              describeCommits(null,'c0a'),describeCommits([],'c0a')]));""",
        )
        self.assertEqual(got[:3], [7, 9, 0])
        self.assertEqual(
            got[3],
            {
                "n": 3,
                "more": False,
                "prs": [13, 12],
                "authors": ["Bob Park", "Carol Lee"],
                "subject": "Fix the axis names",
                "time": "t3",
                "top": "m1",
                "unknown": False,
            },
        )
        self.assertEqual((got[4]["n"], got[4]["more"]), (4, True))
        self.assertEqual(
            (got[5]["n"], got[5]["prs"], got[5]["authors"], got[5]["unknown"], got[5]["top"]), (0, [], [], True, "m1")
        )
        self.assertEqual((got[7]["n"], got[7]["unknown"], got[7]["top"]), (0, True, ""))
        self.assertEqual((got[8]["n"], got[8]["unknown"]), (0, False))
        self.assertEqual((got[6]["n"], got[6]["prs"], got[6]["subject"]), (1, [12], "Shorten the introduction"))

    def test_what_a_built_document_showed_is_its_builds_commit_not_the_checkouts_newest(self):
        """checkDocUpdate with docBuild and shownRows: a first visit while build A shows and the checkout is already at
        commit B records A's commit, so build B then says the one commit B with its PR, not 'files changed without a
        commit'. A build whose commit touched none of the document's files carries all its commits, unless it is behind
        the checkout (stale_build): then which of them it carries is not known - a first visit records no commit, and
        the next build names none (unknown), never a commit the first had already as new (B's PR #12 here); a build at
        such a commit, still behind, after a known one names none either and leaves no commit as seen."""
        got = node_json(
            ["prOf", "describeCommits", "shownRows", "docBuild", "verAfter", "checkDocUpdate"],
            """const DOC='ms',META_BY=new Map(),GROUPS=new Map(),said=[]; let META=null,rec=null,state=null,ROWS=[];
            function rendersInBrowser(){return false;} function updDocState(){return state;} function seenDoc(){return rec;}
            function setSeenDoc(k,r){rec=r;} async function docRows(){return ROWS;} function dq(u){return u;}
            async function api(){throw new Error('not asked');} function docUpdateView(){}
            function groupNote(g,d){said.push({n:d.commits.n,prs:d.commits.prs,top:d.top,unknown:d.commits.unknown});}
            const C=(id,subject)=>({id,subject,author:'Bob Park',time:'t'});
            const show=async(build,head,stale,rows)=>{META={pages_build:build,head,stale_build:stale}; state={ver:'build:'+build,name:'본문',kind:'tex'}; ROWS=rows; await checkDocUpdate('ms',{});};
            (async()=>{const out={};
              const A=C('aaaa1111aaaa','Initial'),B=C('bbbb2222bbbb','Update introduction (#12)'),Cc=C('cccc3333cccc','Fix the axis (#13)');
              await show('A','aaaa111',true,[B,A]); out.first=rec.rev; await show('B','bbbb222',false,[B,A]); out.later=said.pop();
              rec=null; await show('A','ffff999',true,[B,A]); out.behind=rec.rev; await show('B','eeee888',false,[Cc,B,A]); out.unrelated=said.pop();
              rec=null; await show('A','ffff999',false,[B,A]); out.current=rec.rev;
              rec={ver:'build:A',rev:A.id}; await show('B','ffff999',true,[Cc,B,A]); out.stillBehind=said.pop();
              console.log(JSON.stringify(out));})();""",
        )
        self.assertEqual(got["first"], "aaaa1111aaaa")
        self.assertEqual(got["later"], {"n": 1, "prs": [12], "top": "bbbb2222bbbb", "unknown": False})
        self.assertEqual(got["behind"], "")
        self.assertEqual(got["unrelated"], {"n": 0, "prs": [], "top": "cccc3333cccc", "unknown": True})
        self.assertEqual(got["current"], "bbbb2222bbbb")
        self.assertEqual(got["stillBehind"], {"n": 0, "prs": [], "top": "", "unknown": True})

    def test_a_version_older_than_the_one_seen_is_no_change(self):
        """checkDocUpdate with verAfter: a tab showing an older source or build than this device has seen (a drawn
        document come back to, still showing the lines it was left with, whose change was said and dismissed while it was
        off screen; another tab that saw a newer build) says nothing, reads no history and keeps the record; a newer one
        is said. The built document is not the one on screen (ms beside nt): its meta is the one kept for it, so the
        build is known and only the order of versions keeps the older one from being said."""
        got = node_json(
            ["describeCommits", "shownRows", "docBuild", "verAfter", "checkDocUpdate"],
            """const DOC='nt',META_BY=new Map(),GROUPS=new Map(),said=[]; let META=null,rec=null,state=null,reads=0;
            function rendersInBrowser(k){return k==='md';} function updDocState(){return state;} function seenDoc(){return rec;}
            function setSeenDoc(k,r){rec=r;} async function docRows(){reads++; return [];} function dq(u){return u;}
            async function api(){throw new Error('not asked');} function docUpdateView(){}
            function groupNote(g,d){said.push(d.ver);}
            const check=async(k,s)=>{reads=0; said.length=0; state=s; await checkDocUpdate(k,{}); return [said.slice(),reads,rec.ver];};
            const ms=build=>{META_BY.set('ms',{pages_build:build,head:'',stale_build:false}); return {ver:'build:'+build,name:'본문',kind:'tex'};};
            (async()=>{const out=[];
              rec={ver:'src:200',rev:''}; out.push(await check('nt',{ver:'src:100',name:'노트',kind:'md'}));
              out.push(await check('nt',{ver:'src:300',name:'노트',kind:'md'}));
              rec={ver:'build:pages-20261105100000',rev:''}; out.push(await check('ms',ms('pages-20261105090000')));
              out.push(await check('ms',ms('pages-20261105110000')));
              console.log(JSON.stringify(out));})();""",
        )
        self.assertEqual(
            got,
            [
                [[], 0, "src:200"],
                [["src:300"], 1, "src:200"],
                [[], 0, "build:pages-20261105100000"],
                [["build:pages-20261105110000"], 1, "build:pages-20261105100000"],
            ],
        )

    def test_what_another_tab_saw_while_the_history_was_read_is_what_counts(self):
        """checkDocUpdate reads what this device has seen again once the history has answered (another tab writes the
        same limnSeen). Seen A, build C shows: another tab seeing C itself or a later build D meanwhile leaves nothing to
        say - what this tab kept for the change goes (updForget) - and one seeing B, between them, leaves C alone to say,
        counted from B's commit."""
        got = node_json(
            ["prOf", "describeCommits", "shownRows", "docBuild", "verAfter", "checkDocUpdate"],
            """const DOC='ms',META_BY=new Map(),GROUPS=new Map(); let META=null,rec=null,later=null,said=[],forgot=[];
            function rendersInBrowser(){return false;} function seenDoc(){return rec;} function setSeenDoc(k,r){rec=r;}
            function updDocState(){return {ver:'build:pages-20261105120000',name:'본문',kind:'tex'};}
            function dq(u){return u;} async function api(){throw new Error('not asked');} function docUpdateView(){}
            function updForget(k){forgot.push(k);}
            function groupNote(g,d){said.push({n:d.commits.n,prs:d.commits.prs,seenRev:d.seenRev,top:d.top});}
            const C=(id,subject)=>({id,subject,author:'Bob Park',time:'t'});
            const A=C('aaaa1111aaaa','Initial'),B=C('bbbb2222bbbb','Update introduction (#12)'),Cc=C('cccc3333cccc','Fix the axis (#13)');
            async function docRows(){if(later)rec=later; return [Cc,B,A];}   // the other tab writes while the read is out
            (async()=>{const out={};
              META={pages_build:'pages-20261105120000',head:'cccc333',stale_build:false};
              const check=async(seen,meanwhile)=>{rec=seen; later=meanwhile; said=[]; forgot=[]; await checkDocUpdate('ms',{});
                return {said,forgot,rec:rec.ver};};
              const a={ver:'build:pages-20261105100000',rev:A.id};
              out.none=await check(a,null);
              out.same=await check(a,{ver:'build:pages-20261105120000',rev:Cc.id});
              out.newer=await check(a,{ver:'build:pages-20261105130000',rev:''});
              out.between=await check(a,{ver:'build:pages-20261105110000',rev:B.id});
              console.log(JSON.stringify(out));})();""",
        )
        both = {"n": 2, "prs": [13, 12], "seenRev": "aaaa1111aaaa", "top": "cccc3333cccc"}
        self.assertEqual(got["none"], {"said": [both], "forgot": [], "rec": "build:pages-20261105100000"})
        self.assertEqual(got["same"], {"said": [], "forgot": ["ms"], "rec": "build:pages-20261105120000"})
        self.assertEqual(got["newer"], {"said": [], "forgot": ["ms"], "rec": "build:pages-20261105130000"})
        one = {"n": 1, "prs": [13], "seenRev": "bbbb2222bbbb", "top": "cccc3333cccc"}
        self.assertEqual(got["between"], {"said": [one], "forgot": [], "rec": "build:pages-20261105110000"})

    def test_a_seen_record_only_moves_forward(self):
        """setSeenDoc with verAfter: an older tab dismissing its message (an earlier mtime, an earlier build) keeps the
        newer record another tab wrote; a later one, a first one or one of another kind is written. Build ids order by
        their time, then their count."""
        got = node_json(
            ["seenStore", "seenSave", "seenDoc", "setSeenDoc", "verAfter"],
            """let SEEN_MEM=null; const M=new Map(); const localStorage={getItem:k=>M.has(k)?M.get(k):null,setItem:(k,v)=>M.set(k,String(v))};
            const out=[]; const at=()=>seenDoc('d').ver;
            setSeenDoc('d',{ver:'src:200.5',rev:'b'}); setSeenDoc('d',{ver:'src:100.25',rev:'a'}); out.push(at());
            setSeenDoc('d',{ver:'src:300',rev:'c'}); out.push(at());
            setSeenDoc('d',{ver:'build:pages-20261105100000',rev:'x'}); out.push(at());
            setSeenDoc('d',{ver:'build:pages-20261105090000-3',rev:'y'}); out.push(at());
            setSeenDoc('d',{ver:'build:pages-20261105100000-2',rev:'z'}); out.push(at());
            setSeenDoc('d',{ver:'build:pages-20261105100000-1',rev:'w'}); out.push(at());
            console.log(JSON.stringify(out));""",
        )
        self.assertEqual(
            got,
            [
                "src:200.5",
                "src:300",
                "build:pages-20261105100000",
                "build:pages-20261105100000",
                "build:pages-20261105100000-2",
                "build:pages-20261105100000-2",
            ],
        )

    def test_new_pins_are_those_above_the_top_seen_not_made_by_me(self):
        """freshPins: numbered above the highest seen, not mine, in number order."""
        got = node_json(
            ["freshPins"],
            """const rows=[{id:7,author:{login:'bob'}},{id:3,author:{login:'bob'}},{id:6,author:{login:'me'}},{id:5,author:{login:'local'}}];
            console.log(JSON.stringify(freshPins(rows,4,'me').map(p=>p.id)));""",
        )
        self.assertEqual(got, [5, 7])

    def test_the_gathered_line_names_each_thing_once_with_how_many(self):
        """digestLine: each brief once, in the order they came; a brief ending in a count (new pins per document) adds its
        counts up, any other counts how many said it."""
        got = node_json(
            ["digestLine"],
            "console.log(JSON.stringify([digestLine(['본문이 바뀌었습니다','나를 부름','나를 부름','새 핀 2']),"
            "digestLine(['검토 대기 3','새 핀 1','메모가 바뀌었습니다','새 핀 1'])]));",
        )
        self.assertEqual(
            got, ["본문이 바뀌었습니다 · 나를 부름 2 · 새 핀 2", "검토 대기 3 · 새 핀 2 · 메모가 바뀌었습니다"]
        )

    def test_away_time_reads_in_minutes_hours_then_days(self):
        """awayTitle: minutes under an hour, hours under a day, then days; the lost connection has its own words."""
        got = node_json(
            ["awayTitle"],
            "console.log(JSON.stringify([awayTitle(150000,false),awayTitle(3*3600000,false),awayTitle(2*86400000,true)]));",
        )
        self.assertEqual(got, ["자리를 비운 사이 (3분)", "자리를 비운 사이 (3시간)", "연결이 끊긴 사이 (2일)"])

    def test_a_newer_limn_is_a_status_item_after_a_lost_connection_and_before_messages_on_every_band(self):
        """statusList: the server's other version is an item right after a lost connection, before the line's other
        messages, with [새로 고침] (act reload); the desktop's line shows it too (statusShown), in its long words."""
        got = node_json(
            ["statusProgress", "statusList", "statusShown", "statusText"],
            """const n={kind:'ok',title:'소식',desc:'',alert:false};
            const l=statusList({notices:[n],offline:true,outdated:'0.4.52'});
            console.log(JSON.stringify([l.map(i=>i.kind),l[1].act,statusShown(l,true).map(i=>i.kind),statusText(l[1],'long')[0],statusText(l[1],'short')[0]]));""",
        )
        self.assertEqual(got[0], ["offline", "outdated", "notice"])
        self.assertEqual(got[1], "reload")
        self.assertEqual(got[2], ["outdated", "notice"])
        self.assertEqual(got[3], "Limn 0.4.52(으)로 바뀌었습니다 · 새로 고치면 새 화면을 씁니다")
        self.assertEqual(got[4], "Limn 업데이트됨")


# The notice store with its groups and gathering, pulled as served, on a fake clock (as test_viewer_notices_store).
GROUP_FNS = [
    "msgSplit", "noticeDupe", "noticeDot", "makeNotice", "lineNote", "endNotice", "noticeText", "armNotice", "noticeHeld",
    "lineHeld", "holdLine", "releaseLine", "lineHoverOut", "lineVisible", "noticeAct", "noticeClose", "noticeFocusBack",
    "sourceEntry", "sourceOk", "isUndo", "lineCap", "sameWords", "noticeDots", "holdsDot", "groupNote", "regroup",
    "digestBegin", "digestSoon", "digestHold", "digestEnd", "digestBrief", "digestLine", "digestNote", "digestReplay",
    "digestTake", "newsSlot", "keysHeld", "noticeLess", "newsWithout", "digestClosed", "newsDupe", "foldedNews",
    "foldedLess", "digestRetitle", "foldedGone", "digestDots", "reviewPins", "reviewNewsStale", "dropStaleReview",
    "noticeSeen", "endTopic",
]  # fmt: skip
GROUP_PRELUDE = r"""
let NOW=0,QID=0; const Q=[];
function setTimeout(fn,ms){const id=++QID; Q.push({id,at:NOW+Math.max(0,Number(ms)||0),fn}); return id;}
function clearTimeout(id){const i=Q.findIndex(t=>t.id===id); if(i>=0)Q.splice(i,1);}
Date.now=()=>NOW;
function tick(ms){const end=NOW+ms; for(;;){Q.sort((a,b)=>a.at-b.at||a.id-b.id); const t=Q[0]; if(!t||t.at>end)break; Q.shift(); NOW=t.at; t.fn();} NOW=end;}
const stub=()=>({open:false,hidden:true,addEventListener(){},getClientRects:()=>[],matches:()=>false,querySelector:()=>null,querySelectorAll:()=>[],remove(){}});
const ELS={}; const $=s=>ELS[s]||(ELS[s]=stub());
const BODY=new Set(); let LISTED=0;
const document={body:{classList:{add:c=>BODY.add(c),remove:c=>BODY.delete(c),contains:c=>BODY.has(c)}},querySelectorAll:()=>[],activeElement:null,addEventListener(){},removeEventListener(){},contains:()=>false};
let SIDE_OPEN=false,STATUS_TOP=0,STATUS_SIG=''; const EDITOR={current:null}; let REPLY=null;
function announce(){} function drawStatus(){} function toggleStatusList(){LISTED++;} function pageVerdictsOn(){return false;}
const NOTICES=new Map(),LINE=[],BANNERS=new Map(),GROUPS=new Map(); let NOTICE_SEQ=0,LINE_HOVER=false,DIGEST=null;
const view=g=>({msg:g.ids.length===1?'#'+g.ids[0]+' 검토 대기':'핀 '+g.ids.length+'개 검토 대기 — #'+g.ids.join(', #'),kind:NOTICE_KIND.OK,act:null,o:{dot:NOTICE_DOT.RV,brief:'검토 대기 '+g.ids.length}});
const merge=(a,b)=>({ids:[...a.ids,...b.ids]});
const said=()=>LINE.map(n=>n.title+(n.desc?' — '+n.desc:''));
"""
GROUP_CONSTS = r"^const (?:NOTICE_MS|NOTICE_HOLD_MAX|LINE_MAX|DIGEST_MAX_MS)=\d+;"


class Grouping(unittest.TestCase):
    """groupNote and the gathering with the real notice store, under node."""

    def setUp(self):
        node_or_skip(self)

    def run_store(self, body):
        consts = "\n".join(re.findall(GROUP_CONSTS, HTML, re.M))
        return json.loads(
            run_node("\n".join([js_i18n("ko"), GROUP_PRELUDE, consts] + [extract_js_fn(n) for n in GROUP_FNS] + [body]))
        )

    def test_twelve_pins_closed_one_by_one_are_one_message_that_grows(self):
        """Twelve events of one group a second apart: one message on the line, saying all twelve, the newest first."""
        got = self.run_store(
            """for(let i=1;i<=12;i++){groupNote('review',{ids:[i]},view,merge); tick(1000);}
            lineNote('다른 소식',NOTICE_KIND.INFO);
            console.log(JSON.stringify([LINE.length,said()[1],GROUPS.size]));"""
        )
        self.assertEqual(got[0], 2)
        self.assertEqual(got[1], "핀 12개 검토 대기 — #1, #2, #3, #4, #5, #6, #7, #8, #9, #10, #11, #12")
        self.assertEqual(got[2], 1)

    def test_a_group_starts_again_once_its_message_went(self):
        """After [x] the next event of the group is a new message with that event alone."""
        got = self.run_store(
            """groupNote('review',{ids:[1]},view,merge); groupNote('review',{ids:[2]},view,merge);
            noticeClose(LINE[0].n); groupNote('review',{ids:[3]},view,merge);
            console.log(JSON.stringify(said()));"""
        )
        self.assertEqual(got, ["#3 검토 대기"])

    def test_what_came_while_away_is_one_line_and_unfolds_into_each_message(self):
        """A gathering of a group and two other groups' messages ends as one line with their briefs and the dots; [펼치기]
        puts each on the line and opens the list; the screen's own message (a restored draft) and an error are never
        gathered - only news, a message of a group; one thing alone is said as itself, behind what the line says."""
        got = self.run_store(
            """digestBegin('자리를 비운 사이 (5분)');
            groupNote('review',{ids:[1]},view,merge); groupNote('review',{ids:[2]},view,merge);
            lineNote('핀 #4 · 본문 — Bob님이 불렀습니다: 봐 주세요',NOTICE_KIND.OK,null,{literal:true,brief:'나를 부름',dot:NOTICE_DOT.SIDE,group:'m4'});
            lineNote('핀 #5 · 본문 — Bob님이 불렀습니다: 또',NOTICE_KIND.OK,null,{literal:true,brief:'나를 부름',group:'m5'});
            lineNote('작성 중이던 메모를 되살렸습니다',NOTICE_KIND.INFO);
            lineNote('저장 실패 — 서버',NOTICE_KIND.ERR);
            const during=said(); digestEnd(); const folded=said(),dots=[...BODY].sort();
            noticeAct(LINE.find(n=>n.items).n); const open=said();
            tick(1); digestBegin('x'); lineNote('하나뿐',NOTICE_KIND.INFO,null,{group:'one'}); digestEnd();
            console.log(JSON.stringify({during,folded,dots,open,listed:LISTED,one:said()[said().length-1]}));"""
        )
        self.assertEqual(got["during"], ["저장 실패 — 서버", "작성 중이던 메모를 되살렸습니다"])
        self.assertEqual(
            got["folded"],
            [
                "저장 실패 — 서버",
                "작성 중이던 메모를 되살렸습니다",
                "자리를 비운 사이 (5분) — 검토 대기 2 · 나를 부름 2",
            ],
        )
        self.assertEqual(got["dots"], ["dot-rv", "dot-side"])
        self.assertEqual(
            got["open"],
            [
                "핀 #5 · 본문 — Bob님이 불렀습니다: 또",
                "핀 #4 · 본문 — Bob님이 불렀습니다: 봐 주세요",
                "핀 2개 검토 대기 — #1, #2",
                "저장 실패 — 서버",
                "작성 중이던 메모를 되살렸습니다",
            ],
        )
        self.assertEqual(got["listed"], 1)
        self.assertEqual(got["one"], "하나뿐")

    def test_one_event_on_both_paths_is_gathered_once(self):
        """The event addressed to me (rank 2) and the list comparison (rank 1) of the same review: gathered once, the
        event's, whichever came first; another document's news is named after this one's."""
        got = self.run_store(
            """digestBegin('지난 방문 뒤');
            lineNote('#1 검토 대기',NOTICE_KIND.OK,null,{group:'review',keys:['review_requested:1'],rank:1,brief:'검토 대기 1'});
            lineNote('핀 #1 · 본문 — 검토 대기: 고침',NOTICE_KIND.OK,null,{group:'ev:review_requested',keys:['review_requested:1'],rank:2,brief:'검토 대기'});
            lineNote('#1 검토 대기',NOTICE_KIND.OK,null,{group:'review',keys:['review_requested:1'],rank:1,brief:'검토 대기 1'});
            lineNote('메모가 바뀌었습니다 — 커밋 1개',NOTICE_KIND.INFO,null,{literal:true,group:'upd:notes',back:true});
            lineNote('본문이 바뀌었습니다 — 커밋 1개',NOTICE_KIND.INFO,null,{literal:true,group:'upd:main'});
            digestEnd(); console.log(JSON.stringify(said()));"""
        )
        self.assertEqual(got, ["지난 방문 뒤 — 검토 대기 · 본문이 바뀌었습니다 · 메모가 바뀌었습니다"])

    def test_an_event_said_on_a_higher_path_leaves_only_its_own_pins_out_of_a_batch(self):
        """Dedupe per event, not per message (the list comparison's review group with its newsWithout): #2 then #1 sent
        to review are one message; the event addressed to me for #1 comes later and takes #1 alone out of it, which says
        #2 in place. The other way round, a batch of #4 and #5 after the event for #4 says #5 alone. Gathered, the same:
        #6 and #7, then the event for #6, unfold into #7 and the event."""
        got = self.run_store(
            """const kv=g=>({msg:g.ids.length===1?'#'+g.ids[0]+' 검토 대기':'핀 '+g.ids.length+'개 검토 대기 — #'+g.ids.join(', #'),kind:NOTICE_KIND.OK,act:null,
              o:{keys:g.ids.map(i=>'review_requested:'+i),brief:'검토 대기 '+g.ids.length}});
            const less=newsWithout('review_requested','ids'),reset=()=>{LINE.slice().forEach(n=>endNotice(n,true)); tick(9000);};
            const ev=id=>lineNote('핀 #'+id+' · 본문 — 검토 대기: 고침',NOTICE_KIND.OK,null,{literal:true,group:'ev:review_requested',keys:['review_requested:'+id],rank:2,brief:'검토 대기'});
            groupNote('review',{ids:[2]},kv,merge,less); tick(20000); groupNote('review',{ids:[1]},kv,merge,less); ev(1); const late=said(); reset();
            ev(4); groupNote('review',{ids:[4,5]},kv,merge,less); const early=said(); reset();
            digestBegin('지난 방문 뒤'); groupNote('review',{ids:[6,7]},kv,merge,less); ev(6); digestEnd(); const f=LINE.find(n=>n.items); if(f)noticeAct(f.n);
            console.log(JSON.stringify({late,early,gathered:said()}));"""
        )
        self.assertEqual(got["late"], ["핀 #1 · 본문 — 검토 대기: 고침", "#2 검토 대기"])
        self.assertEqual(got["early"], ["#5 검토 대기", "핀 #4 · 본문 — 검토 대기: 고침"])
        self.assertEqual(sorted(got["gathered"]), ["#7 검토 대기", "핀 #6 · 본문 — 검토 대기: 고침"])

    def test_an_event_that_grows_its_message_takes_its_pin_out_of_a_batch_said_between(self):
        """The event for #1 (rank 2), the list comparison's batch of #2 and #3, then the event for #2, which grows the
        event's message rather than making one: #2 leaves the batch all the same, which says #3 in place."""
        got = self.run_store(
            """const kv=g=>({msg:'#'+g.ids.join(', #')+' 검토 대기',kind:NOTICE_KIND.OK,act:null,o:{keys:g.ids.map(i=>'review_requested:'+i)}});
            const ev=g=>({msg:'나에게 검토 대기 — #'+g.ids.join(', #'),kind:NOTICE_KIND.OK,act:null,o:{keys:g.ids.map(i=>'review_requested:'+i),rank:2}});
            groupNote('ev:review_requested',{ids:[1]},ev,merge); tick(1000);
            groupNote('review',{ids:[2,3]},kv,merge,newsWithout('review_requested','ids')); tick(1000);
            groupNote('ev:review_requested',{ids:[2]},ev,merge);
            console.log(JSON.stringify(said()));"""
        )
        self.assertEqual(got, ["나에게 검토 대기 — #1, #2", "#3 검토 대기"])

    def test_an_event_after_a_folded_line_takes_its_pins_out_of_what_it_holds(self):
        """Gathered and folded: the list comparison's #2 and #3, and another group's #4. The event for #2 comes after:
        the folded line counts what is left and [펼치기] says #3 and #4 beside the event - #2 once. The other way round, a
        batch of #5 and #6 after a folded event for #5 says #6 alone. A folded message whose every pin an event says leaves
        the line, its group with it, and a folded line left with nothing goes."""
        got = self.run_store(
            """const kv=g=>({msg:'#'+g.ids.join(', #')+' 검토 대기',kind:NOTICE_KIND.OK,act:null,o:{keys:g.ids.map(i=>'review_requested:'+i),brief:'검토 대기 '+g.ids.length}});
            const ev=g=>({msg:'나에게 검토 대기 — #'+g.ids.join(', #'),kind:NOTICE_KIND.OK,act:null,o:{keys:g.ids.map(i=>'review_requested:'+i),rank:2,brief:'나에게 검토 대기'}});
            const less=newsWithout('review_requested','ids'),reset=()=>{LINE.slice().forEach(n=>endNotice(n,true)); GROUPS.clear(); tick(9000);};
            digestBegin('지난 방문 뒤'); groupNote('review',{ids:[2,3]},kv,merge,less); groupNote('other',{ids:[4]},kv,null); digestEnd();
            groupNote('ev:review_requested',{ids:[2]},ev,merge); const folded=said(); noticeAct(LINE.find(n=>n.items).n); const open=said(); reset();
            digestBegin('지난 방문 뒤'); groupNote('ev:review_requested',{ids:[5]},ev,merge); groupNote('other',{ids:[9]},kv,null); digestEnd();
            groupNote('review',{ids:[5,6]},kv,merge,less); const later=said(); reset();
            digestBegin('지난 방문 뒤'); groupNote('review',{ids:[7]},kv,merge,less); groupNote('other',{ids:[8]},kv,null); digestEnd();
            groupNote('ev:review_requested',{ids:[7]},ev,merge); const one=said(),groups=[...GROUPS.keys()].sort();
            groupNote('ev:review_requested',{ids:[8]},ev,merge);
            console.log(JSON.stringify({folded,open,later,one,groups,none:said()}));"""
        )
        self.assertEqual(got["folded"], ["나에게 검토 대기 — #2", "지난 방문 뒤 — 검토 대기 2"])
        self.assertEqual(sorted(got["open"]), ["#3 검토 대기", "#4 검토 대기", "나에게 검토 대기 — #2"])
        self.assertEqual(got["later"], ["#6 검토 대기", "지난 방문 뒤 — 나에게 검토 대기 · 검토 대기 1"])
        self.assertEqual(got["one"], ["나에게 검토 대기 — #7", "지난 방문 뒤 — 검토 대기 1"])
        self.assertEqual(got["groups"], ["ev:review_requested", "other"])
        self.assertEqual(got["none"], ["나에게 검토 대기 — #7, #8"])

    def test_a_review_request_folded_in_a_gathered_line_goes_once_its_pin_left_review(self):
        """Gathered while away: the list comparison's #1 sent to review (marking [검토 M]) and two pins closed. #1 is
        confirmed and leaves the review list: the folded request goes, its group with it, the folded line says and marks
        what is left - [검토 M]'s dot goes - and [펼치기] never puts #1 back. Looking at the review section takes a folded
        request whose pin still awaits review the same way; one left stays a folded line naming it, and a folded line
        whose every message went that way goes."""
        got = self.run_store(
            """const kv=g=>({msg:'#'+g.ids.join(', #')+' 검토 대기',kind:NOTICE_KIND.OK,act:null,
              o:{keys:g.ids.map(i=>'review_requested:'+i),dot:NOTICE_DOT.RV,brief:'검토 대기 '+g.ids.length}});
            const done=g=>({msg:'#'+g.ids.join(', #')+' 완료',kind:NOTICE_KIND.OK,act:null,o:{brief:'완료 '+g.ids.length}});
            const less=newsWithout('review_requested','ids'),reset=()=>{LINE.slice().forEach(n=>endNotice(n,true)); GROUPS.clear(); tick(9000);};
            const marks=()=>[said(),[...BODY].sort(),LINE.filter(n=>n.items).map(n=>n.dots)]; let REVIEW_ALL=[{id:1},{id:2}]; const out={};
            digestBegin('지난 방문 뒤'); groupNote('review',{ids:[1]},kv,merge,less); groupNote('done',{ids:[4]},done,null); groupNote('done5',{ids:[5]},done,null); digestEnd();
            out.before=marks(); REVIEW_ALL=[{id:2}]; dropStaleReview(); out.stale=[...marks(),GROUPS.has('review')];
            noticeAct(LINE.find(n=>n.items).n); out.open=said().sort(); reset();
            digestBegin('지난 방문 뒤'); groupNote('review',{ids:[2]},kv,merge,less); groupNote('done',{ids:[6]},done,null); digestEnd();
            noticeSeen(NOTICE_DOT.RV); out.seen=marks(); reset(); REVIEW_ALL=[];
            digestBegin('지난 방문 뒤'); groupNote('review',{ids:[7]},kv,merge,less);
            lineNote('핀 #8 · 본문 — 검토 대기: 고침',NOTICE_KIND.OK,null,{literal:true,group:'ev:review_requested',keys:['review_requested:8'],rank:2,dot:NOTICE_DOT.RV,brief:'검토 대기'});
            digestEnd(); out.both=marks(); dropStaleReview(); out.none=marks();
            console.log(JSON.stringify(out));"""
        )
        self.assertEqual(got["before"], [["지난 방문 뒤 — 검토 대기 1 · 완료 2"], ["dot-rv"], [["rv"]]])
        self.assertEqual(got["stale"], [["지난 방문 뒤 — 완료 2"], [], [[]], False])
        self.assertEqual(got["open"], ["#4 완료", "#5 완료"])
        self.assertEqual(got["seen"], [["지난 방문 뒤 — 완료 1"], [], [[]]])
        self.assertEqual(got["both"], [["지난 방문 뒤 — 검토 대기 2"], ["dot-rv"], [["rv"]]])
        self.assertEqual(got["none"], [[], [], []])

    def test_closing_a_gathered_line_ends_its_groups_so_new_pins_are_seen(self):
        """A gathered line holding new pins (newPinsView) and a document's update, closed with [x]: its groups end with
        it, so the new pins' end finds no other new-pins message and records the highest pin as seen, the update is
        seen, and neither group is left standing for the next event."""
        got = self.run_store(
            extract_js_fn("newPinsView")
            + """
            const DOC='nt',UPD={top:2}; let seen=1; const ended=[];
            function setSeenPin(n){seen=n;} function docInfo(){return {name:'노트'};} function openPinFromLink(){}
            digestBegin('지난 방문 뒤');
            groupNote('new:nt',{doc:'nt',pins:[{id:2,who:'Bob Park',place:'L3',note:'새 지적'}]},newPinsView,null);
            groupNote('upd:nt',{},()=>({msg:'노트가 바뀌었습니다 — 커밋 1개',kind:NOTICE_KIND.INFO,act:null,o:{literal:true,keep:true,onEnd:(a,s)=>ended.push(s)}}),null);
            digestEnd(); noticeClose(LINE.find(n=>n.items).n);
            console.log(JSON.stringify({seen,ended,groups:[...GROUPS.keys()]}));"""
        )
        self.assertEqual(got, {"seen": 2, "ended": [True], "groups": []})

    def test_a_group_event_after_the_gathering_takes_its_message_out_of_the_folded_line(self):
        """A gathered group's next event merges with what was gathered and is said on its own; the folded line says the
        rest; dismissing the folded line runs what each gathered message held for its end, as seen."""
        got = self.run_store(
            """const ended=[]; digestBegin('지난 방문 뒤');
            groupNote('review',{ids:[1]},view,merge);
            lineNote('본문이 바뀌었습니다 — PR #12',NOTICE_KIND.INFO,null,{literal:true,group:'upd:main',onEnd:(a,s)=>ended.push([a,s])});
            lineNote('새 핀 #9 — Bob',NOTICE_KIND.INFO,null,{literal:true,brief:'새 핀 1',group:'new:main'});
            digestEnd(); groupNote('review',{ids:[2]},view,merge); const after=said();
            noticeClose(LINE.find(n=>n.items).n);
            console.log(JSON.stringify({after,ended,left:said()}));"""
        )
        self.assertEqual(got["after"], ["핀 2개 검토 대기 — #1, #2", "지난 방문 뒤 — 본문이 바뀌었습니다 · 새 핀 1"])
        self.assertEqual(got["ended"], [[False, True]])
        self.assertEqual(got["left"], ["핀 2개 검토 대기 — #1, #2"])


SOURCE = "# 메모\n\n첫 문단이다.\n\n## 할 일\n\n- 하나\n- 둘\n- 셋\n\n끝 문단이다.\n"
LINE_TEXT = "() => document.querySelector('#status') ? document.querySelector('#status').innerText : ''"


class UpdateFlows(BrowserBase):
    """The flows on a desktop, as Alice, on an instance with a Markdown document (nt, first) and the LaTeX manuscript (ms)."""

    def setUp(self):
        super().setUp()
        self.src = self.main.parent
        self.md = self.src / "notes.md"
        self.md.write_text(SOURCE, encoding="utf-8")
        docs = startup_documents.make_docs(["nt=노트:notes.md", "ms=본문:main.tex"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        self.nt, self.ms = docs
        viewer_build(self.ms, BUILD1)

    DRAWN = "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md [data-line],#md [data-lo]')"

    def view(self, init=SEEN):
        page = self.open(0, init=init, **SCREENS["desktop"])
        until(page, self.DRAWN, 20)
        settle(page)
        return page

    def tab(self, page):
        """Another tab of page's browser: a page in the same context, so the two share localStorage (limnSeen)."""
        other = page.context.new_page()
        errors = []
        other.on("pageerror", lambda e: errors.append(str(e)))
        other.route("**/*", self.route)
        other.goto("http://viewer.test/?lang=ko")
        until(other, "typeof LIGHT_TIMER!=='undefined'&&!!LIGHT_TIMER&&(%s)" % self.DRAWN, 20)
        settle(other)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return other

    def line(self, page):
        return page.evaluate("LINE.map(n=>n.title+(n.desc?' — '+n.desc:''))")

    def poll(self, page):
        """One light poll now, and what it set going."""
        page.evaluate("pollLight()")
        settle(page)

    def test_a_changed_markdown_source_says_so_tints_its_lines_and_is_seen_only_when_dismissed(self):
        """The source changed on disk: the redraw says '노트가 바뀌었습니다 — 커밋 없이 파일이 바뀌었습니다 · 바뀐 곳 2' with
        [바뀐 곳], and the changed lines carry the tint; [바뀐 곳] keeps the message and goes to a place; [x] takes the tint
        away and records it as seen, so a reload says nothing."""
        page = self.view()
        until(page, "!!localStorage.getItem('limnSeen')&&!!JSON.parse(localStorage.getItem('limnSeen')).docs.nt")
        self.md.write_text(
            SOURCE.replace("- 둘\n", "- 둘 반\n").replace("끝 문단이다.", "끝 문단을 고쳤다."), encoding="utf-8"
        )
        self.poll(page)
        until(page, "LINE.some(n=>n.group==='upd:nt')")
        self.assertIn("노트가 바뀌었습니다 — 커밋 없이 파일이 바뀌었습니다 · 바뀐 곳 2", self.line(page))
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#md .md-upd')].length>=2"), True)
        page.evaluate("noticeAct(LINE.find(n=>n.group==='upd:nt').n)")
        self.assertTrue(page.evaluate("LINE.some(n=>n.group==='upd:nt')"))  # [바뀐 곳] leaves it standing
        page.evaluate("noticeClose(LINE.find(n=>n.group==='upd:nt').n)")
        self.assertEqual(page.evaluate("document.querySelectorAll('#md .md-upd').length"), 0)
        page.reload()
        until(page, "typeof LIGHT_TIMER!=='undefined'&&!!LIGHT_TIMER", 20)
        settle(page)
        page.wait_for_timeout(600)
        self.assertFalse(any("바뀌었습니다" in t for t in self.line(page)), self.line(page))

    def test_a_second_change_before_the_first_is_seen_keeps_the_first_places(self):
        """L3 changes, and before that is seen L11 changes too: the message says both places and both lines are tinted
        (the lines are compared with those before the first change, not with those just drawn). Once dismissed, the next
        change is compared with what was seen: only its own place."""
        from limn.builds.artifacts import expire_src_mtime

        def change(text):
            self.md.write_text(text, encoding="utf-8")
            expire_src_mtime(self.nt)
            self.poll(page)
            until(page, "MD.lines.join('\\n')===%s" % json.dumps(text.rstrip("\n")))
            settle(page)

        page = self.view()
        until(page, "!!seenDoc('nt')&&LIGHT_INFLIGHT===null")
        first = SOURCE.replace("첫 문단이다.", "고친 첫 문단이다.")
        change(first)
        until(page, "UPD.lines.has('nt')")
        change(first.replace("끝 문단이다.", "고친 끝 문단이다."))
        self.assertEqual(page.evaluate("UPD.lines.get('nt').ranges"), [{"lo": 3, "hi": 3}, {"lo": 11, "hi": 11}])
        self.assertIn("바뀐 곳 2", page.evaluate("LINE.find(n=>n.group==='upd:nt').desc"))
        tinted = "[...document.querySelectorAll('#md .md-upd')].map(e=>e.textContent.trim())"
        self.assertEqual(sorted(page.evaluate(tinted)), ["고친 끝 문단이다.", "고친 첫 문단이다."])
        page.evaluate("noticeClose(LINE.find(n=>n.group==='upd:nt').n)")
        change(first.replace("끝 문단이다.", "고친 끝 문단이다.").replace("- 둘\n", "- 둘 반\n"))
        self.assertEqual(page.evaluate("UPD.lines.get('nt').ranges"), [{"lo": 8, "hi": 8}])

    def test_a_markdown_document_left_behind_says_its_change_and_a_return_after_seeing_it_says_nothing(self):
        """Read on the Markdown document, then on the manuscript: the note's source changes while it is off screen, and
        the document list's new mtime says '노트가 바뀌었습니다' with [열기] - the lines drawn before are not what it shows.
        Back to it with that message standing, the redraw joins it, tinting and counting the place ([바뀐 곳]). Off
        screen again, a second change said there and dismissed: back to it, nothing is said again and nothing is tinted."""
        from limn.builds.artifacts import expire_src_mtime

        def change(text):
            self.md.write_text(text, encoding="utf-8")
            expire_src_mtime(self.nt)
            self.poll(page)

        def to(k):
            page.evaluate("switchDoc(%s)" % json.dumps(k))
            until(page, "DOC===%s&&!!META&&META.doc===%s" % (json.dumps(k), json.dumps(k)))
            settle(page)

        def drawn(text):
            until(page, "MD.shown==='nt'&&MD.lines.join('\\n')===%s" % json.dumps(text.rstrip("\n")))
            settle(page)

        page = self.view()
        until(page, "!!seenDoc('nt')&&!!seenDoc('ms')&&LIGHT_INFLIGHT===null")
        page.evaluate("clearInterval(LIGHT_TIMER); digestEnd()")
        to("ms")
        first = SOURCE.replace("첫 문단이다.", "고친 첫 문단이다.")
        change(first)
        until(page, "LINE.some(n=>n.group==='upd:nt')")
        said = page.evaluate(
            "(()=>{const n=LINE.find(x=>x.group==='upd:nt'); return [n.title,n.desc,n.act&&n.act.label];})()"
        )
        self.assertEqual(said, ["노트가 바뀌었습니다", "커밋 없이 파일이 바뀌었습니다", "열기"])
        to("nt")
        drawn(first)
        until(page, "UPD.lines.has('nt')")
        said = page.evaluate("(()=>{const n=LINE.find(x=>x.group==='upd:nt'); return [n.desc,n.act&&n.act.label];})()")
        self.assertEqual(said, ["커밋 없이 파일이 바뀌었습니다 · 바뀐 곳 1", "바뀐 곳"])
        tinted = "[...document.querySelectorAll('#md .md-upd')].map(e=>e.textContent.trim())"
        self.assertEqual(page.evaluate(tinted), ["고친 첫 문단이다."])
        page.evaluate("noticeClose(LINE.find(n=>n.group==='upd:nt').n)")
        to("ms")
        second = first.replace("끝 문단이다.", "고친 끝 문단이다.")
        change(second)
        until(page, "LINE.some(n=>n.group==='upd:nt')")
        page.evaluate("noticeClose(LINE.find(n=>n.group==='upd:nt').n)")
        to("nt")
        drawn(second)
        page.wait_for_timeout(300)
        self.assertEqual(self.line(page), [t for t in self.line(page) if "바뀌었습니다" not in t])
        self.assertEqual(page.evaluate(tinted), [])
        self.assertFalse(page.evaluate("UPD.lines.has('nt')"))

    def test_a_change_another_tab_saw_past_while_this_one_read_its_history_is_not_said(self):
        """Two tabs of one browser on the note. Its source changes (B): tab A draws it and reads the note's history to say
        the change - that read is held. The source changes again (C) and tab B says C, whose [x] records C as seen (the
        tabs share limnSeen). A's answer comes then: C, newer than B, has been seen, so A says nothing and tints nothing,
        not B's change again; and drawing C later says nothing either."""
        from limn.builds.artifacts import expire_src_mtime

        def change(text, at):
            self.md.write_text(text, encoding="utf-8")
            os.utime(self.md, (at, at))
            expire_src_mtime(self.nt)

        def drawn(page, text):
            return page.evaluate("MD.shown==='nt'&&MD.lines.join('\\n')===%s" % json.dumps(text.rstrip("\n")))

        a = self.view()
        until(a, "!!seenDoc('nt')&&!!seenDoc('ms')&&LIGHT_INFLIGHT===null")
        b = self.tab(a)
        for page in (a, b):
            page.evaluate("clearInterval(LIGHT_TIMER); digestEnd()")
            settle(page)
        held = []

        def hold(route):
            if held:
                return route.fallback()
            held.append(route)

        a.route(re.compile(r"/api/revisions\?"), hold)
        t0 = self.md.stat().st_mtime
        first = SOURCE.replace("첫 문단이다.", "고친 첫 문단이다.")
        change(first, t0 + 10)
        a.evaluate("pollLight()")
        until(a, lambda: drawn(a, first) and bool(held))
        second = first.replace("끝 문단이다.", "고친 끝 문단이다.")
        change(second, t0 + 20)
        b.evaluate("pollLight()")
        until(b, "LINE.some(n=>n.group==='upd:nt')")
        b.evaluate("noticeClose(LINE.find(n=>n.group==='upd:nt').n)")
        self.assertEqual(a.evaluate("seenDoc('nt').ver"), b.evaluate("'src:'+MD.mtime"))
        self.assertFalse(a.evaluate("LINE.some(n=>n.group==='upd:nt')"))
        held[0].fallback()
        settle(a)
        tinted = "document.querySelectorAll('#md .md-upd').length"
        self.assertEqual(self.line(a), [t for t in self.line(a) if "바뀌었습니다" not in t])
        self.assertEqual((a.evaluate(tinted), a.evaluate("UPD.lines.has('nt')")), (0, False))
        a.evaluate("pollLight()")
        until(a, lambda: drawn(a, second))
        settle(a)
        self.assertEqual(self.line(a), [t for t in self.line(a) if "바뀌었습니다" not in t])
        self.assertEqual(a.evaluate(tinted), 0)

    def test_a_coauthors_new_pin_and_an_agent_closing_pins_one_by_one_are_one_message_each(self):
        """Bob's new pin on this document: '새 핀 #N — Bob Park · L3 · …' with [보기]. The agent closing three of Alice's
        pins poll by poll: one message that grows to '핀 3개가 검토 대기로 넘어왔습니다 — #a, #b, #c · 로컬/에이전트'."""
        ids = [
            add_pin({"file": str(self.md), "lo": n, "hi": n, "note": "a"}, actor(ALICE), doc=self.nt).record["id"]
            for n in (3, 7, 8)
        ]
        page = self.view()
        until(page, "PINS.length===3")
        bob = add_pin(
            {"file": str(self.md), "lo": 3, "hi": 3, "note": "첫 문단을 줄입시다"}, actor(BOB), doc=self.nt
        ).record["id"]
        self.poll(page)
        until(page, "LINE.some(n=>n.group==='new:nt')")
        self.assertIn("새 핀 #%d — Bob Park · L3 · 첫 문단을 줄입시다" % bob, self.line(page))
        store = ps.APP.pin_lifecycle.context().store
        for pid in ids:
            ps.APP.pin_lifecycle.close_pin(
                pid, post_authority(store, dict(LOCAL_ACTOR), "close", pid), CloseRequest(reply="고침", ref="abc1234")
            )
            self.poll(page)
        # Alice's pins: the events addressed to her (review_requested) say it, and the list comparison of the same
        # closes gives way to them (noticeDupe) - one message either way, naming the three
        cond = "LINE.filter(n=>n.title.includes('검토 대기')).length===1&&LINE.find(n=>n.title.includes('검토 대기')).desc.includes('#%d')"
        try:
            until(page, cond % ids[2])
        except AssertionError:
            raise AssertionError(
                json.dumps(page.evaluate("LINE.map(n=>[n.group,n.title,n.desc])"), ensure_ascii=False)
            ) from None
        review = [t for t in self.line(page) if "검토 대기" in t]
        self.assertEqual(
            review, ["핀 3개가 검토 대기로 넘어왔습니다 — #%d, #%d, #%d · 로컬/에이전트" % tuple(ids)], self.line(page)
        )

    def test_a_reply_to_my_pin_is_said_on_the_line_with_the_notification_switch_off(self):
        """Browser notifications off: Bob's reply on Alice's pin still comes - the poll asks for events after the cursor
        this tab set - as '핀 #N · 노트 — Bob Park님 답글: …' with [열기]."""
        pid = add_pin({"file": str(self.md), "lo": 3, "hi": 3, "note": "a"}, actor(ALICE), doc=self.nt).record["id"]
        page = self.view()
        self.poll(page)
        until(page, "localStorage.getItem('pinNotifyCursor')!==null")
        self.assertFalse(page.evaluate("notifyOn()"))
        body = json.dumps({"text": "줄였습니다"}).encode()
        code, _, out = self.talk(
            req(
                "POST",
                "/api/pins/%d/reply?doc=nt" % pid,
                body,
                {"Content-Type": "application/json", "Origin": "http://127.0.0.1:18999", **BOB},
            )
        )
        self.assertEqual(code, 200, out)
        self.poll(page)
        until(page, "LINE.some(n=>n.keys.includes('replied:%d'))" % pid)
        self.assertIn("핀 #%d · 노트 — Bob Park님 답글: 줄였습니다" % pid, self.line(page))

    def test_a_move_saved_after_the_change_was_dismissed_is_said_on_its_own(self):
        """A paragraph inserted above Alice's pin on L3: the document's update message comes and is dismissed; the
        maintenance that saves the moved place (ADR-0028) comes later, and that move is said on its own ('#N 줄 +2
        이동') - not taken into the message that has gone."""
        pid = add_pin({"file": str(self.md), "lo": 3, "hi": 3, "note": "a"}, actor(ALICE), doc=self.nt).record["id"]
        page = self.view()
        until(page, "!!seenDoc('nt')&&LIGHT_INFLIGHT===null")
        page.evaluate("clearInterval(LIGHT_TIMER); digestEnd()")
        self.md.write_text(SOURCE.replace("첫 문단이다.", "추가된 문단이다.\n\n첫 문단이다."), encoding="utf-8")
        from limn.builds.artifacts import expire_src_mtime

        expire_src_mtime(self.nt)
        page.evaluate("pollLightOnce()")
        until(page, "LINE.some(n=>n.group==='upd:nt')")
        page.evaluate("noticeClose(LINE.find(n=>n.group==='upd:nt').n)")
        ps.APP.assembly.pins.startup.maintain()
        page.evaluate("pollLightOnce()")
        until(page, "OPEN_ALL.some(p=>p.id===%d&&p.lo===5)" % pid)
        settle(page)
        self.assertIn("#%d 줄 +2 이동" % pid, self.line(page))
        self.assertFalse(page.evaluate("UPD.moved.has('nt')"))

    def test_a_browser_whose_storage_refuses_still_boots_and_keeps_what_it_saw_in_memory(self):
        """Storage throws a SecurityError on reading and writing the event cursor, and refuses writing limnSeen (a full
        quota): the boot still draws the document, loads the pins and starts polling; the cursor and the seen record live
        in memory for the visit, so a reply to Alice's pin is said once."""
        pid = add_pin({"file": str(self.md), "lo": 3, "hi": 3, "note": "a"}, actor(ALICE), doc=self.nt).record["id"]
        refuse = """;(()=>{const get=Storage.prototype.getItem,set=Storage.prototype.setItem;
          const no=n=>{throw new DOMException('storage denied',n);};
          Storage.prototype.getItem=function(k){return k==='pinNotifyCursor'?no('SecurityError'):get.call(this,k);};
          Storage.prototype.setItem=function(k,v){return k==='pinNotifyCursor'?no('SecurityError'):k==='limnSeen'?no('QuotaExceededError'):set.call(this,k,v);};})();"""
        page = self.view(init=SEEN + refuse)
        until(page, "typeof LIGHT_TIMER!=='undefined'&&!!LIGHT_TIMER&&PINS.length===1")
        page.evaluate("clearInterval(LIGHT_TIMER)")
        self.poll(page)
        until(page, "notifyCursor()!==null&&!!seenDoc('nt')")
        body = json.dumps({"text": "줄였습니다"}).encode()
        headers = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:18999", **BOB}
        code, _, out = self.talk(req("POST", "/api/pins/%d/reply?doc=nt" % pid, body, headers))
        self.assertEqual(code, 200, out)
        self.poll(page)
        until(page, "LINE.some(n=>n.keys.includes('replied:%d'))" % pid)
        self.poll(page)
        self.assertEqual(page.evaluate("LINE.filter(n=>n.keys.includes('replied:%d')).length" % pid), 1)

    def test_a_message_that_grows_is_read_out_by_one_live_region(self):
        """A group's message that grows is read out once: by the line's own region (.st-sr) while the line shows it, the
        separate #sr-news then left alone; behind an undo, which keeps the line, by #sr-news."""
        page = self.view()
        got = page.evaluate(
            """()=>{digestEnd(); LINE.slice().forEach(n=>endNotice(n,true));
            const v=d=>({msg:'새 핀 '+d.n+'개',kind:NOTICE_KIND.INFO,act:null,o:{literal:true}}),news=()=>document.querySelector('#sr-news').textContent;
            const st=()=>document.querySelector('#status .st-sr').textContent;
            groupNote('grow-test',{n:1},v,null); document.querySelector('#sr-news').textContent='';
            groupNote('grow-test',{n:2},v,null); const top={status:st(),news:news()};
            lineNote('되돌릴 수 있습니다',NOTICE_KIND.OK,{label:'되돌리기',fn:()=>{}},{undo:true,literal:true});
            document.querySelector('#sr-news').textContent='';
            groupNote('grow-test',{n:3},v,null); return {top,behind:{status:st(),news:news()}};}"""
        )
        self.assertEqual(got["top"], {"status": "새 핀 2개", "news": ""})
        self.assertEqual(got["behind"]["news"], "새 핀 3개")
        self.assertNotIn("새 핀", got["behind"]["status"])

    def test_a_rebuild_at_a_commit_outside_the_documents_history_names_no_pr_from_a_guess(self):
        """The manuscript's commits are 'Initial' and 'Old introduction (#12)'; the checkout's head is an unrelated commit
        (in none of its history), and its pages, built there, are behind an uncommitted edit. Which of its commits those
        pages carry is not known, so the first visit records no commit; the rebuild at the same head that takes the edit
        says '본문이 바뀌었습니다' with [변경 보기] - never 'PR #12 … · Alice', a commit those pages had already."""
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Alice",
            GIT_AUTHOR_EMAIL="alice@example.com",
            GIT_COMMITTER_NAME="Alice",
            GIT_COMMITTER_EMAIL="alice@example.com",
        )

        def git(*args):
            return subprocess.check_output(["git", *args], cwd=self.src, env=env, text=True, stderr=subprocess.PIPE)

        git("init", "-q")
        git("add", "main.tex", "notes.md")
        git("commit", "-q", "-m", "Initial")
        self.main.write_text(self.main.read_text() + "\n% Old introduction\n")
        git("commit", "-q", "-am", "Old introduction (#12)")
        (self.src / "unrelated.txt").write_text("unrelated")
        git("add", "unrelated.txt")
        git("commit", "-q", "-m", "Unrelated change")
        head = git("rev-parse", "HEAD").strip()
        (self.ms.dir / "head.txt").write_text(head)
        mt = self.main.stat().st_mtime
        (self.ms.dir / "built_src_mtime.txt").write_text(str(mt))
        self.main.write_text(self.main.read_text() + "\n% New uncommitted edit\n")
        os.utime(self.main, (mt + 10, mt + 10))
        from limn.builds.artifacts import expire_src_mtime

        expire_src_mtime(self.ms)
        page = self.view()
        until(page, "!!seenDoc('ms')")
        self.assertEqual(page.evaluate("seenDoc('ms').rev"), "")
        page.evaluate("clearInterval(LIGHT_TIMER); switchDoc('ms')")
        until(page, "DOC==='ms'&&!!META&&META.doc==='ms'")
        settle(page)
        self.assertTrue(page.evaluate("META.stale_build"))
        viewer_build(self.ms, "pages-20261105200000")
        (self.ms.dir / "head.txt").write_text(head)
        (self.ms.dir / "built_src_mtime.txt").write_text(str(mt + 10))
        got = page.evaluate(
            """async()=>{await refreshDoc(); await checkDocUpdate('ms',{}); const n=LINE.find(x=>x.group==='upd:ms');
            return {stale:META.stale_build,said:n?[n.title,n.desc,n.act&&n.act.label]:null,line:LINE.map(x=>x.title+' — '+x.desc)};}"""
        )
        self.assertFalse(got["stale"], got)
        self.assertEqual(got["said"], ["본문이 바뀌었습니다", "", "변경 보기"], got)
        self.assertFalse(any("#12" in t or "Alice" in t for t in got["line"]), got)

    def test_the_changes_view_of_an_update_stops_at_the_commit_its_message_named(self):
        """The manuscript's pages were built at commit B ('Update introduction (#12)'), the last seen commit is A, and C
        ('Fix the axis (#13)') is committed after them, not built. The message names B alone, and its [변경 보기] opens
        the source diff of A → B - not A → C, the checkout's newest, which the pages on screen do not carry."""
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Alice",
            GIT_AUTHOR_EMAIL="alice@example.com",
            GIT_COMMITTER_NAME="Alice",
            GIT_COMMITTER_EMAIL="alice@example.com",
        )

        def git(*args):
            return subprocess.check_output(["git", *args], cwd=self.src, env=env, text=True, stderr=subprocess.PIPE)

        git("init", "-q")
        git("add", "main.tex", "notes.md")
        git("commit", "-q", "-m", "Initial")
        a = git("rev-parse", "HEAD").strip()
        self.main.write_text(self.main.read_text() + "\n% New introduction\n")
        git("commit", "-q", "-am", "Update introduction (#12)")
        b = git("rev-parse", "HEAD").strip()
        (self.ms.dir / "head.txt").write_text(b)
        mt = self.main.stat().st_mtime
        (self.ms.dir / "built_src_mtime.txt").write_text(str(mt))
        self.main.write_text(self.main.read_text() + "\n% The axis\n")
        git("commit", "-q", "-am", "Fix the axis (#13)")
        c = git("rev-parse", "HEAD").strip()
        os.utime(self.main, (mt + 10, mt + 10))
        from limn.builds.artifacts import expire_src_mtime

        expire_src_mtime(self.ms)
        page = self.view()
        until(page, "!!seenDoc('ms')&&LIGHT_INFLIGHT===null")
        page.evaluate(
            """a=>{clearInterval(LIGHT_TIMER); digestEnd(); const all=JSON.parse(localStorage.getItem('limnSeen'));
            all.docs.ms={ver:'build:pages-20260101000000',rev:a}; localStorage.setItem('limnSeen',JSON.stringify(all));}""",
            a,
        )
        page.evaluate("switchDoc('ms')")
        until(page, "DOC==='ms'&&LINE.some(n=>n.group==='upd:ms')")
        said = page.evaluate(
            "(()=>{const n=LINE.find(x=>x.group==='upd:ms'); return [n.title,n.desc,n.act&&n.act.label];})()"
        )
        self.assertEqual(said, ["본문이 바뀌었습니다", "PR #12 Update introduction · Alice", "변경 보기"])
        page.evaluate("noticeAct(LINE.find(n=>n.group==='upd:ms').n)")
        until(page, "document.body.classList.contains('revision-open')&&REV.rowsDoc==='ms'&&!!REV.commit")
        got = page.evaluate("[REV.rows[0].id,REV.commit,REV.base,REV.range.start,REV.range.end]")
        self.assertEqual(got, [c, b, a, b, b])

    def test_an_event_that_grows_takes_its_pin_out_of_a_list_batch_said_between(self):
        """An event addressed to me for #1, then the list comparison's batch of #2 and #3, then the event for #2 grows
        the event's message: #2 leaves the batch, which says #3 alone - #2 is said once."""
        page = self.view()
        got = page.evaluate(
            """()=>{clearInterval(LIGHT_TIMER); digestEnd(); LINE.slice().forEach(n=>endNotice(n,true));
            const ev=id=>({type:EVENT_TYPE.REVIEW_REQUESTED,pin:id,doc:'nt',doc_name:'노트',by:{login:'bob@example.com',name:'Bob'},excerpt:'고침'});
            const list=g=>({msg:'#'+g.ids.join(', #')+' 검토 대기',kind:NOTICE_KIND.OK,act:null,o:{keys:g.ids.map(i=>'review_requested:'+i),literal:true}});
            notifyLine(ev(1));
            groupNote('review',{ids:[2,3]},list,(a,b)=>({ids:[...a.ids,...b.ids]}),newsWithout('review_requested','ids'));
            notifyLine(ev(2));
            return LINE.map(n=>({group:n.group,keys:n.keys,title:n.title}));}"""
        )
        held = {n["group"]: n["keys"] for n in got}
        self.assertEqual(held["ev:review_requested"], ["review_requested:1", "review_requested:2"], got)
        self.assertEqual(held["review"], ["review_requested:3"], got)
        self.assertEqual(next(n["title"] for n in got if n["group"] == "review"), "#3 검토 대기", got)

    def test_an_event_after_a_folded_line_takes_its_pin_out_of_the_gathered_batch(self):
        """Gathered while away: the list comparison's batch of #2 and #3, and another group's #4, folded into one line.
        The event addressed to me for #2 comes then: the folded batch says #3 alone, so [펼치기] says #2 once."""
        page = self.view()
        got = page.evaluate(
            """()=>{clearInterval(LIGHT_TIMER); digestEnd(); LINE.slice().forEach(n=>endNotice(n,true));
            const list=g=>({msg:'#'+g.ids.join(', #')+' 검토 대기',kind:NOTICE_KIND.OK,act:null,o:{keys:g.ids.map(i=>'review_requested:'+i),literal:true}});
            digestBegin('자리를 비운 사이 (5분)');
            groupNote('review',{ids:[2,3]},list,(a,b)=>({ids:[...a.ids,...b.ids]}),newsWithout('review_requested','ids'));
            groupNote('other',{ids:[4]},list,null); digestEnd();
            notifyLine({type:EVENT_TYPE.REVIEW_REQUESTED,pin:2,doc:'nt',doc_name:'노트',by:{name:'Bob'},excerpt:'고침'});
            const folded=LINE.find(n=>n.items); if(folded)noticeAct(folded.n);
            return LINE.map(n=>({group:n.group,keys:n.keys,title:n.title}));}"""
        )
        self.assertEqual(sum("review_requested:2" in n["keys"] for n in got), 1, got)
        self.assertEqual(
            sorted(n["title"] for n in got if n["group"] in ("review", "other")), ["#3 검토 대기", "#4 검토 대기"], got
        )

    def test_back_after_a_while_what_came_is_one_line_that_unfolds(self):
        """Away (the last answer 3 minutes ago), a co-author's pin and a closed pin come: one line '자리를 비운 사이 (3분) —
        검토 대기 1 · 새 핀 1' (in the order they came) with [펼치기], which puts each on the line."""
        pid = add_pin({"file": str(self.md), "lo": 3, "hi": 3, "note": "a"}, actor(ALICE), doc=self.nt).record["id"]
        page = self.view()
        until(page, "PINS.length===1")
        add_pin({"file": str(self.md), "lo": 7, "hi": 7, "note": "b"}, actor(BOB), doc=self.nt)
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(store, dict(LOCAL_ACTOR), "close", pid), CloseRequest(reply="고침", ref="abc1234")
        )
        page.evaluate("LIGHT_OK_AT=Date.now()-180000; pollLight()")
        until(page, "LINE.some(n=>!!n.items)", 12)
        gathered = [t for t in self.line(page) if t.startswith("자리를 비운 사이")]
        self.assertEqual(gathered, ["자리를 비운 사이 (3분) — 검토 대기 1 · 새 핀 1"], self.line(page))
        page.evaluate("noticeAct(LINE.find(n=>!!n.items).n)")
        lines = self.line(page)
        self.assertFalse(any(t.startswith("자리를 비운 사이") for t in lines), lines)
        self.assertTrue(any(t.startswith("새 핀 #") for t in lines) and any("검토 대기" in t for t in lines), lines)


class ARestartedServer(ChromiumTestCase):
    """The newer-Limn check against a real server process - src/limn/server.py run by path from a copy of the package, as
    instances start - on a Markdown document, as Alice: the page's own version is what the process served it with, and
    GET /api/version is what the process loaded at start (dartworklabs/limn#415)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pkg = root / "pkg" / "limn"
        shutil.copytree(Path(limn.__file__).parent, self.pkg, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        (root / "ms").mkdir()
        (root / "ms" / "notes.md").write_text(SOURCE, encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.log = root / "server.log"
        self.argv = [
            sys.executable,
            str(self.pkg / "server.py"),
            *("--manuscript", str(root / "ms"), "--doc", "nt=노트:notes.md", "--state-dir", str(root / "state")),
            *("--port", str(self.port), "--label", "Restart"),
        ]
        self.proc = None
        self.addCleanup(self.stop)
        self.start()

    def set_version(self, v):
        """Rewrite the copy's __version__ on disk, as a pulled checkout or an upgraded install does."""
        init = self.pkg / "__init__.py"
        init.write_text(
            re.sub(r'^__version__ = "[^"]+"', '__version__ = "%s"' % v, init.read_text("utf-8"), flags=re.M)
        )

    def start(self):
        """Start the server process and wait (up to 30 s) until it answers GET /api/version."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIMN_") and k != "PYTHONPATH"}
        with self.log.open("ab") as out:
            self.proc = subprocess.Popen(self.argv, stdout=out, stderr=subprocess.STDOUT, env=env)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                break
            try:
                self.served_version()
                return
            except OSError:
                time.sleep(0.1)
        self.fail("the server did not answer:\n" + self.log.read_text("utf-8", "replace"))

    def stop(self):
        """End the server process this test started (by its own handle), if it still runs."""
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)

    def served_version(self):
        with urllib.request.urlopen(self.base + "/api/version", timeout=2) as r:
            return json.loads(r.read())["version"]

    def checked(self, page):
        """Ask the server's version as the tab does (checkVersion) and wait for the answer; the version the tab holds."""
        page.evaluate("VERSION.server=''; checkVersion()")
        until(page, "!VERSION.busy&&!!VERSION.server")
        return page.evaluate("VERSION.server")

    def test_a_newer_limn_is_said_only_once_a_restart_runs_it_and_a_reload_ends_it(self):
        """The package files say 0.4.99 while the process still runs the old code: the server answers the old version and
        the tab says nothing, also after a reload. Restarted, the tab's next poll after the lost connection says
        'Limn 0.4.99(으)로 바뀌었습니다' with [새로 고침]; a reload gets the new page and the line says nothing."""
        old = self.served_version()
        context = self.browser.new_context(viewport={"width": 1440, "height": 900}, extra_http_headers=ALICE)
        self.addCleanup(context.close)
        context.add_init_script(SEEN)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(self.base + "/?lang=ko")
        until(page, "typeof LIGHT_TIMER!=='undefined'&&!!LIGHT_TIMER", 20)
        page.evaluate("clearInterval(LIGHT_TIMER)")  # this test drives the polls
        reload_item = "!!document.querySelector('#status [data-act=reload]')"

        self.set_version("0.4.99")
        self.assertEqual(self.checked(page), old)
        self.assertFalse(page.evaluate(reload_item))
        self.assertEqual(self.served_version(), old)
        page.reload()
        until(page, "typeof LIGHT_TIMER!=='undefined'&&!!LIGHT_TIMER", 20)
        page.evaluate("clearInterval(LIGHT_TIMER)")
        self.assertEqual(self.checked(page), old)
        self.assertFalse(page.evaluate(reload_item))

        self.stop()
        page.evaluate("(async()=>{await pollLightOnce(); await pollLightOnce();})()")
        until(page, "POLL_FAILS>=2")
        self.start()
        self.assertEqual(self.served_version(), "0.4.99")
        page.evaluate("pollLightOnce()")
        until(page, reload_item)
        self.assertIn("Limn 0.4.99(으)로 바뀌었습니다", page.evaluate(LINE_TEXT))

        page.reload()
        until(page, "typeof LIGHT_TIMER!=='undefined'&&!!LIGHT_TIMER", 20)
        page.evaluate("clearInterval(LIGHT_TIMER)")
        self.assertEqual(page.evaluate("document.querySelector('#more-foot .m-ver').textContent.trim()"), "v0.4.99")
        self.assertEqual(self.checked(page), "0.4.99")
        self.assertFalse(page.evaluate(reload_item))
        self.assertEqual(errors, [])
