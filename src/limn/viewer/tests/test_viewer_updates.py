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
        the rows (more); a merge commit's own subject gives way to the commit under it; no seen commit, nothing."""
        got = node_json(
            ["prOf", "describeCommits"],
            """const rows=[{id:'m1',subject:'Merge pull request #13 from bob/x',author:'Bob Park',time:'t3'},
              {id:'c2',subject:'Fix the axis names',author:'Bob Park',time:'t2'},
              {id:'c1',subject:'Shorten the introduction (#12)',author:'Carol Lee',time:'t1'},
              {id:'c0abcdef',subject:'Initial',author:'A',time:'t0'}];
            console.log(JSON.stringify([prOf('Title (#7)'),prOf('Merge pull request #9 from a/b'),prOf('No PR'),
              describeCommits(rows,'c0a'),describeCommits(rows,'zzz'),describeCommits(rows,''),describeCommits(rows.slice(2),'c0abcdef')]));""",
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
            },
        )
        self.assertEqual((got[4]["n"], got[4]["more"]), (4, True))
        self.assertEqual(got[5]["n"], 0)
        self.assertEqual((got[6]["n"], got[6]["prs"], got[6]["subject"]), (1, [12], "Shorten the introduction"))

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
    "digestTake", "newsSlot",
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

    def view(self, init=SEEN):
        page = self.open(0, init=init, **SCREENS["desktop"])
        until(
            page,
            "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md [data-line],#md [data-lo]')",
            20,
        )
        settle(page)
        return page

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
