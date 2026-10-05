"""Shared fixtures of the message tests (test_viewer_notices, test_viewer_notices_seen; docs/handbook/viewer.md §알림 자리):
the two screens they run on, the init scripts that mark first-visit hints seen and watch for toasts, and the node guard of
their pure rules."""

import os
import shutil

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


def node_or_skip(case):
    """Skip case without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
    if not shutil.which("node"):
        if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
            case.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
        case.skipTest("node not available")
