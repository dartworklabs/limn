"""The service worker and the tab opened again with no network, in a real browser against the real server on a loopback
socket (docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기, docs/handbook/verification.md §실제 소켓의 브라우저 테스트).

BrowserBase serves through request interception on a fake host, which is no secure context, so no worker registers in
those tests. These run on `http://127.0.0.1:<port>` (tests/support/helpers_live.py), where the worker registers and
answers, and each fails - not skips - if the worker does not register. The landing needs a real LaTeX build and is
skipped without latexmk, synctex, pdftotext and pdftoppm (LIMN_TEST_REQUIRE_TEX=1 turns that into a failure).

Each test has its own server, state folder and port. What they assert is what the server holds, what the queue counts and
what the page draws; the page's internals are read in helpers_live.LiveTab only.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_offline_live.py
"""

from pathlib import Path

from limn.builds import artifacts as build
from limn.builds.artifacts import BuildOk

from helpers import needs_tex, ps
from helpers_live import PDF_WORDS, LiveBase

CAUGHT_UP = "a note written at 35000 feet"


class WorkerCopies(LiveBase):
    """With no network the page opens from the worker's copy; an API call is never answered from one."""

    def test_the_page_a_kept_file_and_the_pdf_open_with_no_network_and_an_api_call_does_not(self):
        """Kept online, then cut off and opened again: the page is the real viewer, a static file the page loaded is
        served from its copy, the PDF and the page images are there, and /api/* is refused - neither kept nor answered
        from a copy."""
        tab = self.open_live()
        built = tab.keep()
        urls = tab.cache_urls()
        paths = sorted({u.split("?")[0] for u in urls})
        self.assertIn("/", paths)
        self.assertIn("/pdf", paths)
        self.assertEqual([p for p in paths if p.startswith("/api/")], [], paths)
        self.assertNotIn("/sw.js", paths)
        images = [p for p in paths if p.startswith("/pages/")]
        self.assertEqual(len(images), 2, paths)
        statics = [u for u in urls if u.split("?")[0] not in ["/", "/pdf", *images]]
        self.assertTrue(statics, urls)  # PDF.js and its worker, the fonts: what the page loaded from its own origin
        pdf = next(u for u in urls if u.split("?")[0] == "/pdf")
        online = {u: tab.fetch(u) for u in [pdf, *statics]}
        self.assertTrue(all(got["ok"] for got in online.values()), online)
        tab.cut_off()
        tab.reopen()
        self.assertTrue(tab.page.evaluate("!!document.querySelector('#btn-more')"), "the page is the real viewer")
        self.assertEqual(tab.build(), built)
        for url, was in online.items():
            got = tab.fetch(url)
            self.assertTrue(got["ok"], (url, got))
            self.assertEqual(got["size"], was["size"], url)
        for url in ("/api/meta?light=1", "/api/pins?all=1", "/api/meta"):
            got = tab.fetch(url)
            self.assertFalse(got["ok"], (url, got))
        self.assertEqual([u for u in tab.cache_urls() if u.startswith("/api/")], [])


class QueueAcrossReloads(LiveBase):
    """A pin queued with no network is still there when the tab is opened again with none."""

    def test_a_queued_pin_survives_a_reload_with_no_network(self):
        """A pin saved while cut off is counted; after one reload and another, still with no network, it is still
        counted, with its note, and the server has not been sent it."""
        tab = self.open_live()
        tab.reopen()  # the first visit was not under the worker's control yet; this one is, and its page is kept
        before = len(self.pins())
        tab.cut_off()
        selection = tab.pin_offline("flight note")
        self.assertTrue(selection["offline"])
        for _ in range(2):
            tab.reopen()
            tab.wait_for("OFF.n===1")
            records = tab.queue()
            self.assertEqual([r["note"] for r in records], ["flight note"])
            self.assertEqual(records[0]["page"], 1)
            self.assertEqual(records[0]["build"], tab.build())
        self.assertEqual(len(self.pins()), before)


class StoredReads(LiveBase):
    """A document read the network refuses is answered from the store only where that is meant."""

    def test_a_read_is_answered_from_the_store_while_cut_off_but_a_poll_and_a_write_are_not(self):
        """Cut off: /api/meta comes back from the answer stored when it was last read, and the screen says it is a stored
        one; a light poll, a write and a read with nothing stored fail."""
        tab = self.open_live()
        tab.wait_for("OFF.boot===false")
        built = tab.build()
        meta = tab.read_url("/api/meta")
        tab.until(lambda: tab.stored(meta), what="boot's stored meta")
        tab.cut_off()
        got = tab.api(meta, silent=True)
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["data"]["pages_build"], len(got["data"]["pages"])), (built, 2))
        self.assertTrue(tab.stale_said())
        for call in (
            lambda: tab.api("/api/meta?light=1", silent=True),
            lambda: tab.api("/api/pin", silent=True, method="POST", body={"note": "x"}),
            lambda: tab.api("/api/build", silent=True),
        ):
            got = call()
            self.assertFalse(got["ok"], got)
        self.assertIsNone(tab.stored("/api/meta?light=1"))

    def test_a_read_that_fails_while_connected_is_a_failure_that_is_said_not_a_stored_answer(self):
        """With the viewer connected and its first reads done, a read the network refuses is not answered from the
        store: it fails, the screen says so, and the screen does not claim to be a stored one."""
        tab = self.open_live()
        tab.wait_for("OFF.boot===false")
        url = tab.read_url("/api/meta")
        tab.until(lambda: tab.stored(url), what="boot's stored meta")
        said = tab.notices()
        tab.fail_api_reads()
        got = tab.api(url, where="line")
        self.assertFalse(got["ok"], got)
        self.assertGreater(tab.notices(), said, "the failure is said")
        self.assertFalse(tab.stale_said())

    def test_the_first_reads_of_a_visit_are_answered_from_the_store_while_connected(self):
        """A tab opened again whose first reads the network refuses (the browser itself is online) is drawn from the
        stored ones; once those are done a read that fails is a failure again."""
        tab = self.open_live()
        self.server("POST", "/api/pin", {"file": str(self.main), "lo": 5, "hi": 5, "page": 1, "note": "a stored pin"})
        tab.reopen()  # this visit reads the pin list, and stores it
        tab.until(
            lambda: "a stored pin" in [p["note"] for p in (tab.stored("/api/pins?all=1") or {"data": []})["data"]],
            what="the stored list",
        )
        tab.fail_api_reads_from_the_next_visit()
        tab.reopen()
        tab.stop_polling()
        state = tab.state()
        self.assertEqual(state["pages"], 2)
        self.assertIn("a stored pin", state["notes"])
        self.assertTrue(state["stale"])
        tab.wait_for("OFF.boot===false")
        self.assertFalse(tab.api(tab.read_url("/api/meta"), silent=True)["ok"])

    def test_a_refused_answer_is_never_stored(self):
        """A read the server refuses, which its caller handles itself, is handed to the caller as the refusal it is and
        is not stored: cut off, the same read fails instead of opening as an empty document. A refusal that follows a
        stored answer does not replace it."""
        tab = self.open_live()
        tab.wait_for("OFF.boot===false")
        refused = tab.api("/api/source?doc=main", silent=True, expect=[400, 404, 413])
        self.assertTrue(refused["ok"], refused)
        self.assertGreaterEqual(refused["status"], 400)
        self.assertIsNone(tab.stored("/api/source?doc=main"))
        url = tab.read_url("/api/meta")
        tab.until(lambda: tab.stored(url), what="boot's stored meta")
        good = tab.stored(url)
        tab.answer_reads_with(404, {"error": "gone"})
        again = tab.api(url, silent=True, expect=[404])
        self.assertEqual(again["status"], 404, again)
        tab.answer_reads_with(None)
        self.assertEqual(tab.stored(url)["data"], good["data"])
        tab.cut_off()
        self.assertFalse(tab.api("/api/source?doc=main", silent=True, expect=[400, 404, 413])["ok"])


class ReopenedTab(LiveBase):
    """The whole of a flight: keep the document, lose the network, open the tab again, drag, save."""

    def test_the_reopened_tab_draws_from_stored_reads_and_a_drag_is_queued_with_its_words(self):
        """Kept, then cut off and opened again: the document and the server's pins are drawn from stored reads and the
        screen says so; a drag keeps its box and reads the words under it from the kept PDF; saving queues the pin,
        which survives one more reload and has not been sent."""
        for note in ("a kept pin", "another kept pin"):
            self.server("POST", "/api/pin", {"file": str(self.main), "lo": 5, "hi": 5, "page": 1, "note": note})
        tab = self.open_live()
        tab.until(lambda: len(tab.state()["notes"]) == 2, what="the pins on the first visit")
        built = tab.keep()
        tab.cut_off()
        tab.reopen()
        state = tab.state()
        self.assertEqual((state["build"], state["pages"]), (built, 2))
        self.assertEqual(sorted(state["notes"]), ["a kept pin", "another kept pin"])
        self.assertTrue(state["stale"])
        selection = tab.drag_over_words()
        self.assertTrue(selection["offline"])
        self.assertTrue(selection["box"], "the drag keeps its box")
        self.assertIn(PDF_WORDS, selection["quote"])
        tab.write_note("saved with no network")
        tab.wait_for("OFF.n===1")
        record = tab.queue()[0]
        self.assertEqual((record["note"], record["page"], record["build"]), ("saved with no network", 1, built))
        tab.reopen()
        tab.wait_for("OFF.n===1")
        self.assertEqual(len(self.pins()), 2, "nothing was sent")


class Landing(LiveBase):
    """The promise end to end, on a real build: the pin lands on the lines it was drawn on."""

    @needs_tex("latexmk", "synctex", "pdftotext", "pdftoppm")
    def test_a_pin_made_cut_off_lands_once_on_the_lines_of_the_build_it_was_drawn_on(self):
        """The document is kept, the network lost, a pin made, the manuscript rebuilt twice from the server side, the
        network back: exactly one pin is written, on the lines an online pick of that drag answers, picked against the
        held build; the held build's directory has lost its page images and kept its PDF and SyncTeX."""
        self.assertIsInstance(ps.APP.build_requests.build_all(self.doc), BuildOk)
        tab = self.open_live()
        held = tab.keep()
        self.assertEqual(held, build.cur_pages(self.doc).name)
        self.assertIn(held, self.holds())
        tab.cut_off()
        tab.reopen()
        tab.pin_offline(CAUGHT_UP, box=(0.2, 0.30, 0.8, 0.36))
        # What an online pick of this very drag answers: the lines the offline pin has to land on.
        want = self.server("POST", "/api/pick", tab.queued_drag(held))
        self.assertTrue(want.get("file") and isinstance(want.get("lo"), int), want)
        for _ in range(2):  # the rebuilds that used to remove the build
            self.server("POST", "/api/rebuild?force=1")
        self.assertNotEqual(self.server("GET", "/api/meta")["pages_build"], held)
        folder = self.doc.dir / held
        self.assertTrue(folder.is_dir(), "the held build is still there")
        self.assertEqual(sorted(folder.glob("page-*.png")), [], "its page images are gone")
        self.assertTrue((folder / "slim.json").is_file())
        self.assertTrue(any(folder.glob("*.pdf")), sorted(p.name for p in folder.iterdir()))
        self.assertTrue(any(folder.glob("*.synctex.gz")), sorted(p.name for p in folder.iterdir()))
        before = len(self.pins())
        tab.reconnect()
        tab.wait_for("OFF.n===0")
        rows = self.pins()
        mine = [p for p in rows if p.get("note") == CAUGHT_UP]
        self.assertEqual(len(mine), 1, [(p["id"], p["note"]) for p in rows])
        self.assertEqual(len(rows), before + 1)
        pin = mine[0]
        self.assertEqual(Path(str(pin["file"])).name, Path(str(want["file"])).name)
        self.assertEqual((pin["lo"], pin["hi"]), (want["lo"], want["hi"]))
        self.assertEqual(pin.get("pdf_build"), held, "picked against the build it was drawn on")
        self.assertTrue(pin.get("quote"), "the server's own quote of those lines")
        self.assertEqual(tab.unsent(), {"n": 0, "held": 0})
        tab.until(lambda: CAUGHT_UP in tab.state()["notes"], what="the viewer showing the pin")
        self.assertIn(CAUGHT_UP, ps.APP.C.pins_md.read_text(encoding="utf-8"), "pins.md has it for the agent")


def of_build(url, build):
    """Is url a copy of that very build's PDF or page? A rebuild within the second is named after the build before it
    (pages-<time>-1), so the name alone is not looked for inside the address."""
    return url.startswith("/pages/%s/" % build) or ("build=%s&" % build) in url


class KeepsItselfCurrent(LiveBase):
    """A copy kept once keeps itself current while connected: no second press after a rebuild."""

    def rebuild(self, old):
        """Rebuild on the server, as an agent there does -> the new build, which differs from old."""
        self.server("POST", "/api/rebuild?force=1")
        new = self.server("GET", "/api/meta")["pages_build"]
        self.assertNotEqual(new, old)
        return new

    @needs_tex("latexmk", "synctex", "pdftotext", "pdftoppm")
    def test_a_rebuild_is_followed_without_pressing_again_and_opens_cut_off(self):
        """Kept once; the server rebuilds; nobody presses again. The page follows on its own: the server holds the new
        build, the old build's copies are gone from the cache, and this browser's share of the old build's hold is let
        go - no other device holds it, so the hold ends and nothing piles up. Cut off and opened again, the new build
        opens from the worker's copies."""
        self.assertIsInstance(ps.APP.build_requests.build_all(self.doc), BuildOk)
        tab = self.open_live()
        old = tab.keep()
        self.assertTrue([u for u in tab.cache_urls() if of_build(u, old)])
        new = self.rebuild(old)
        tab.until(
            lambda: tab.kept_build(self.doc.key) == new and not tab.kept()["old"], timeout=90, what="the copy following"
        )
        holds = self.holds()
        me = tab.page.evaluate("async () => await offHolderId()")
        self.assertEqual(list(holds), [new], "the old build's hold ended with its last share")
        self.assertEqual(list(holds[new]["holders"]), [me], "the new build is held in this browser's name")
        urls = tab.cache_urls()
        self.assertEqual([u for u in urls if of_build(u, old)], [], "the old build's copies are gone")
        pdf = [u for u in urls if u.startswith("/pdf") and of_build(u, new)]
        self.assertEqual(len(pdf), 1, urls)
        pages = len(self.server("GET", "/api/meta")["pages"])
        self.assertEqual(len([u for u in urls if u.startswith("/pages/%s/" % new)]), pages, urls)
        tab.cut_off()
        tab.reopen()
        self.assertEqual(tab.build(), new)
        self.assertTrue(tab.fetch(pdf[0])["ok"], "the new build's PDF comes from the worker's copy")

    @needs_tex("latexmk", "synctex", "pdftotext", "pdftoppm")
    def test_another_device_s_share_keeps_the_old_build_held(self):
        """A tablet of the same person holds the build this browser kept - it is cut off, with pins queued there. This
        browser follows the rebuild and lets go of its own share only: the old build stays held, by the tablet."""
        self.assertIsInstance(ps.APP.build_requests.build_all(self.doc), BuildOk)
        tab = self.open_live()
        old = tab.keep()
        tablet = "tablet-0123456789abcdef"
        self.server("POST", "/api/hold", {"build": old, "holder": tablet})
        new = self.rebuild(old)
        tab.until(
            lambda: tab.kept_build(self.doc.key) == new and not tab.kept()["old"], timeout=90, what="the copy following"
        )
        holds = self.holds()
        self.assertEqual(list(holds[old]["holders"]), [tablet], "only the tablet's share of the old build is left")
        self.assertIn(new, holds)
        self.assertEqual([u for u in tab.cache_urls() if of_build(u, old)], [], "this device's copies of it are gone")

    @needs_tex("latexmk", "synctex", "pdftotext", "pdftoppm")
    def test_a_build_a_queued_pin_was_drawn_on_stays_held_until_the_pin_is_sent(self):
        """A pin is queued on the kept build and cannot be sent yet (the server is busy). The server rebuilds and the
        page follows: the old build is still held, and its copies stay. Once the pin is sent, the next follow drops its
        copies and lets go of this browser's share of its hold."""
        self.assertIsInstance(ps.APP.build_requests.build_all(self.doc), BuildOk)
        tab = self.open_live()
        old = tab.keep()
        tab.cut_off()
        tab.reopen()
        tab.pin_offline(CAUGHT_UP, box=(0.2, 0.30, 0.8, 0.36))
        busy = {"n": 0}

        def refuse(route):
            busy["n"] += 1
            route.fulfill(status=503, content_type="application/json", body='{"error": "busy"}')

        tab.page.route("**/api/pick", refuse)
        tab.reconnect()
        tab.until_routed(lambda: busy["n"] >= 1, what="the send refused")
        new = self.rebuild(old)
        tab.until_routed(lambda: tab.kept_build(self.doc.key) == new, timeout=90, what="the copy following")
        self.assertEqual([o["build"] for o in tab.kept()["old"]], [old])
        self.assertEqual(tab.unsent()["n"], 1, "the pin still waits")
        holds = self.holds()
        self.assertIn(old, holds, "the build the queued pin was drawn on is still held")
        self.assertIn(new, holds)
        self.assertTrue([u for u in tab.cache_urls() if of_build(u, old)], "and its copies stay")
        tab.page.unroute("**/api/pick")
        tab.send_queue()
        tab.wait_for("OFF.n===0")
        self.assertEqual(len([p for p in self.pins() if p.get("note") == CAUGHT_UP]), 1)
        tab.until(lambda: not tab.kept()["old"], timeout=90, what="the old build's copies dropped")
        self.assertNotIn(old, self.holds(), "its hold ended once this browser let go")
        self.assertEqual([u for u in tab.cache_urls() if of_build(u, old)], [])


class LostAnswer(LiveBase):
    """A write that landed and whose answer was lost: the idempotency key ends it without a second pin."""

    @needs_tex("latexmk", "synctex", "pdftotext", "pdftoppm")
    def test_a_write_whose_answer_was_lost_is_found_by_its_key_and_not_made_twice(self):
        """The queued pin reaches the server and the browser never hears. The record stays, marked as attempted. The
        next send asks by the key alone, learns the pin exists, and drops the record: one pin on the server, none
        written twice, and nothing left in the queue."""
        self.assertIsInstance(ps.APP.build_requests.build_all(self.doc), BuildOk)
        tab = self.open_live()
        tab.keep()
        tab.cut_off()
        tab.reopen()
        tab.pin_offline(CAUGHT_UP, box=(0.2, 0.30, 0.8, 0.36))
        lost = tab.lose_the_next_pin_answer()
        tab.reconnect()
        tab.until_routed(lambda: lost["n"] == 1 and len(self.pins()) == 1, what="the write reaching the server")
        tab.wait_for("!OFF.flushing")
        self.assertEqual(tab.unsent()["n"], 1, "the browser heard nothing, so the record waits")
        self.assertTrue(tab.record_sent(), "marked as attempted, which is what sends the next visit to ask by key")
        tab.send_queue()
        tab.wait_for("OFF.n===0")
        rows = [p for p in self.pins() if p.get("note") == CAUGHT_UP]
        self.assertEqual(len(rows), 1, "the pin is not made a second time")
        self.assertEqual(tab.unsent(), {"n": 0, "held": 0})

    @needs_tex("latexmk", "synctex", "pdftotext", "pdftoppm")
    def test_a_written_pin_is_recovered_even_after_its_place_is_gone(self):
        """The same lost answer, and then the build the pin was drawn on is released and rebuilt away. Looked for
        first, the place would not be found and the record would be held with its pin standing on the server; asked
        by the key first, it is simply done."""
        self.assertIsInstance(ps.APP.build_requests.build_all(self.doc), BuildOk)
        tab = self.open_live()
        held = tab.keep()
        tab.cut_off()
        tab.reopen()
        tab.pin_offline(CAUGHT_UP, box=(0.2, 0.30, 0.8, 0.36))
        lost = tab.lose_the_next_pin_answer()
        tab.reconnect()
        tab.until_routed(lambda: lost["n"] == 1 and len(self.pins()) == 1, what="the write reaching the server")
        tab.wait_for("!OFF.flushing")
        # The hold is released - the browser's own share, the only one - and two builds later the build is gone: a pick
        # against it now answers pdf_build_gone.
        self.server(
            "POST",
            "/api/hold",
            {"build": held, "days": 0, "holder": tab.page.evaluate("async () => await offHolderId()")},
        )
        for _ in range(2):
            self.server("POST", "/api/rebuild?force=1")
        self.assertFalse((self.doc.dir / held).exists(), "the build the pin was drawn on is gone")
        tab.send_queue()
        tab.wait_for("OFF.n===0")
        self.assertEqual(tab.unsent(), {"n": 0, "held": 0}, "not held: the pin was already there")
        self.assertEqual(len([p for p in self.pins() if p.get("note") == CAUGHT_UP]), 1)


class ServerThatDoesNotAnswer(LiveBase):
    """The server is neither refused nor heard from: requests wait. A tailnet with no internet behind it does this, and
    it is where a flight leaves a device - not the instant failure of a browser that knows it is offline."""

    NOTE = "written while nothing came back"

    def test_the_poll_says_the_connection_is_gone_and_says_it_is_back(self):
        """A poll left waiting is a poll that failed: two of them and the page keeps pins instead of sending them."""
        tab = self.open_live()
        tab.waits(POLL=300)
        self.stop_answering()
        tab.wait_for("offlineNow()")
        self.assertFalse(tab.page.evaluate("document.querySelector('#conn-lost').hidden"))
        self.answer_again()
        tab.wait_for("!offlineNow()")
        self.assertTrue(tab.page.evaluate("document.querySelector('#conn-lost').hidden"))

    def test_a_drag_opens_its_composer_and_the_pin_is_kept(self):
        """Before the poll has said anything: the drag's request waits no longer than its wait, the composer opens on a
        selection made cut off, and [핀 저장] keeps it. The next drag does not ask the server at all."""
        tab = self.open_live()
        tab.keep()
        tab.stop_polling()
        tab.waits(PICK=400, POLL=300)
        picks = tab.asked("/api/pick")
        self.stop_answering()
        selection = tab.drag_over_words()
        self.assertTrue(selection["offline"], selection)
        self.assertFalse(tab.lost(), "the poll has not counted a failure: the drag's own request said it")
        tab.write_note(self.NOTE)
        tab.wait_for("OFF.n===1")
        self.assertEqual(len(picks), 1)
        tab.drag((0.2, 0.5, 0.8, 0.56))
        self.assertTrue(tab.composer()["offline"])
        self.assertEqual(len(picks), 1, "the second drag asked nothing of a server that had just not answered")
        self.answer_again()
        self.assertEqual(self.pins(), [])

    @needs_tex("latexmk", "synctex", "pdftotext", "pdftoppm")
    def test_a_save_that_gets_no_answer_is_kept_as_tried_and_written_once(self):
        """The selection was found while connected and its save goes out as any save does - and nothing comes back. The
        pin is kept in the queue under the key the save carried, marked as tried; the composer closes. The server then
        handles the request it had been left with, and the send asks by that key: one pin, and an empty queue."""
        self.assertIsInstance(ps.APP.build_requests.build_all(self.doc), BuildOk)
        tab = self.open_live()
        tab.stop_polling()
        tab.drag((0.2, 0.30, 0.8, 0.36))
        selection = tab.composer()
        self.assertFalse(selection["offline"], selection)
        tab.waits(SAVE=400, READ=400, POLL=400)
        saves = tab.asked("/api/pin")
        self.stop_answering()
        tab.write_note(self.NOTE)
        tab.wait_for("OFF.n===1")
        record = tab.queue()[0]
        self.assertTrue(record["sent"], record)
        self.assertEqual(len(saves), 1)
        self.assertIn('"idem":"%s"' % record["idem"], saves[0])
        self.assertFalse(tab.save_failure(), "kept, not said as a failed save")
        self.answer_again()
        tab.until(lambda: len(self.pins()) == 1, what="the save the server had been left with")
        tab.send_queue()
        tab.wait_for("OFF.n===0")
        self.assertEqual([p["note"] for p in self.pins()], [self.NOTE])

    def test_the_tab_opens_again_when_answers_start_and_never_finish(self):
        """The connection goes while answers are on their way: each has its head and no body. An answer already handed
        to the page could not be taken back, so the worker reads it whole first, and when a piece does not come it
        answers from its copy; the page's own reads end at their wait and are answered from the store."""
        tab = self.open_live()
        built = tab.keep()
        self.stop_finishing()
        tab.reopen()
        self.assertEqual(tab.build(), built)
        self.assertTrue(tab.stale_said())

    def test_the_tab_opens_again_from_its_copies(self):
        """Reloaded with the server not answering: the worker's copy answers for the page once the network has had its
        wait, the page starts from the stored reads without waiting each of them out, and a drag is kept."""
        tab = self.open_live()
        built = tab.keep()
        self.stop_answering()
        tab.reopen()
        self.assertEqual(tab.build(), built)
        self.assertTrue(tab.stale_said())
        tab.pin_offline(self.NOTE)
        self.assertEqual(tab.queued(), 1)
