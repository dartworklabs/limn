"""Layout work counted from a Chrome trace, for the browser tests that hold a cost by a count rather than a duration
(docs/handbook/verification.md): test_viewer_list_scroll (the pin cards, #305) and test_viewer_verdict_scroll (the page
verdict lines, #322).

Each page PDF.js draws for the first time adds its embedded fonts to document.fonts, and every font added makes the
browser lay out all the text in the page again. SCROLL_ADDING_FONTS does that as PDF.js does (a FontFace from bytes under
a family no text uses) while it scrolls the PDF area, so it needs no PDF with embedded fonts; traced() runs it under a
Chrome trace, and laid_out() reads what each layout walked (the Layout event's dirtyObjects).
"""

import base64
import json
import time

TRACE_FLUSH_S = 30
# Scrolls the PDF area in steps and, at each, adds one font the way PDF.js does for a page it draws first (a FontFace from
# the font file's bytes under a name of its own, added to document.fonts), waits for it and for two frames. Returns the
# long tasks' durations (ms) seen meanwhile.
SCROLL_ADDING_FONTS = """async (steps) => {
  const L = document.querySelector('#left'), frames = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const bytes = await (await fetch('/vendor/pretendard/PretendardVariable.subset.0.woff2')).arrayBuffer();
  const long = [], po = new PerformanceObserver(l => { for (const e of l.getEntries()) long.push(Math.round(e.duration)); });
  po.observe({type: 'longtask'});
  for (let i = 0; i < steps; i++) {
    L.scrollTop += 120;
    const f = new FontFace('limn-test-pdf-font-' + i, bytes.slice(0)); document.fonts.add(f); await f.loaded;
    await frames();
  }
  po.disconnect();
  return long;
}"""


def traced(page, script, arg):
    """Run the async page function script(arg) under a Chrome trace of the devtools timeline; return its value and the
    trace's events."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Tracing.start", {"categories": "devtools.timeline", "transferMode": "ReturnAsStream"})
    value = page.evaluate(script, arg)
    done = []
    cdp.on("Tracing.tracingComplete", lambda e: done.append(e))
    cdp.send("Tracing.end")
    # Wait for tracingComplete - the trace flushed to its stream - up to TRACE_FLUSH_S. The sync session delivers an event
    # only while it waits on a command, so it waits on cheap ones until the event has come or the time is out.
    until = time.monotonic() + TRACE_FLUSH_S
    while not done and time.monotonic() < until:
        cdp.send("Runtime.evaluate", {"expression": "0"})
    assert done, "Tracing.tracingComplete did not come within %ds" % TRACE_FLUSH_S
    chunks = []
    while True:
        part = cdp.send("IO.read", {"handle": done[0]["stream"], "size": 1 << 20})
        chunks.append(base64.b64decode(part["data"]).decode() if part.get("base64Encoded") else part["data"])
        if part.get("eof"):
            break
    cdp.send("IO.close", {"handle": done[0]["stream"]})
    cdp.detach()
    data = json.loads("".join(chunks))
    return value, data["traceEvents"] if isinstance(data, dict) else data


def laid_out(events):
    """The layout objects each layout in the trace events walked (the Layout event's dirtyObjects), in their order."""
    return [
        e["args"]["beginData"]["dirtyObjects"]
        for e in events
        if e.get("name") == "Layout" and "beginData" in e.get("args", {})
    ]
