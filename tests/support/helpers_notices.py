"""Shared fixtures of the message tests (test_viewer_notices, test_viewer_notices_seen, test_viewer_notices_store;
docs/handbook/viewer.md §알림 자리): the two screens they run on, the init scripts that mark first-visit hints seen, watch
for toasts, count confirms and record what the alert region said, the node guard of their pure rules, and NoticePage - the
page and pin helpers of their browser flows."""

import os
import shutil

from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.listing.projection import pin_state
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, find_record, ps
from helpers_access import ALICE, actor
from helpers_authority import post_authority

# The screens the flows run on: a phone (411x908, DPR 2.63, touch) and a desktop (1440x900).
SCREENS = {
    "phone": {
        "viewport": {"width": 411, "height": 908},
        "device_scale_factor": 2.63,
        "is_mobile": True,
        "has_touch": True,
    },
    "desktop": {"viewport": {"width": 1440, "height": 900}},
}
# First-visit hints already seen, so the status line starts empty unless a test wants a hint.
SEEN = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1,side:1}}))}catch(e){}"
# Records every toast-like element the page ever adds: #toasts, #coach, or anything of class toast - from the first
# script on, so the boot's own messages count too.
WATCH_TOASTS = (
    "(()=>{const seen=window.TOASTS_SEEN=[];const hit=n=>n.nodeType===1&&(n.id==='toasts'||n.id==='coach'||"
    "(n.classList&&n.classList.contains('toast'))||!!(n.querySelector&&n.querySelector('#toasts,#coach,.toast')));"
    "new MutationObserver(ms=>{for(const m of ms)for(const n of m.addedNodes)if(hit(n))seen.push(n.id||n.className);})"
    ".observe(document,{childList:true,subtree:true});})()"
)
# Records the viewer's POST /api/pins/<id>/confirm requests in window.CONFIRMS, before they are sent.
COUNT_CONFIRMS = (
    "(()=>{window.CONFIRMS=[];const f=window.fetch;window.fetch=function(u,o){"
    "if(/\\/api\\/pins\\/\\d+\\/confirm/.test(String(u)))window.CONFIRMS.push(String(u));return f.call(this,u,o);};})()"
)
# Records every text the alert region (#sr-alert) is given, in window.ALERTS_SAID, once the page has it.
WATCH_ALERTS = (
    "document.addEventListener('DOMContentLoaded',()=>{const r=document.getElementById('sr-alert'),said=window.ALERTS_SAID=[];"
    "new MutationObserver(()=>{if(r.textContent)said.push(r.textContent);}).observe(r,{childList:true,characterData:true,subtree:true});})"
)


def node_or_skip(case):
    """Skip case without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
    if not shutil.which("node"):
        if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
            case.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
        case.skipTest("node not available")


class NoticePage:
    """Page and pin helpers for a BrowserBase flow test of the viewer's messages, as Alice (mixed in before BrowserBase)."""

    def view(self, screen, init=SEEN, n_open=0):
        """The viewer on screen as Alice, with the toast watch and init (hints seen unless a test passes others)."""
        page = self._page = self.open(n_open, init=WATCH_TOASTS + ";" + init, **SCREENS[screen])
        return page

    def pin(self, lo, note):
        """An open pin by Alice on page 1, lines lo..lo+1, with a box where the mark is drawn; its id."""
        frac = [0.1, 0.05 + 0.1 * (lo % 7), 0.6, 0.03]
        return add_pin(
            {"file": str(self.main), "lo": lo, "hi": lo + 1, "page": 1, "note": note, "frac": frac}, actor(ALICE)
        ).record["id"]

    def agent_close(self, pid):
        """The agent closes pin pid (to review)."""
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(store, dict(LOCAL_ACTOR), "close", pid), CloseRequest(reply="고쳤습니다", ref="abc1234")
        )

    def state(self, pid):
        """Pin pid's state on the server, or None once it is gone."""
        rec = find_record(ps.APP.snapshot_pins(), pid)
        return pin_state(rec) if rec else None

    def compose(self, page, note):
        """A selection on page 1 with note typed in, its draft stored."""
        page.evaluate("LAST_PTR='mouse'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo", timeout=8000)
        page.fill("#note", note)
        page.wait_for_function("DRAFT.timer===0", timeout=8000)

    def line_has(self, page, text):
        """Whether one of the status line's messages says text."""
        return page.evaluate("t=>LINE.some(n=>(n.title+' '+n.desc).includes(t))", text)
