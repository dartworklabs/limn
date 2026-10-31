"""Provider queries preserve publication identity and minimize returned facts."""

import json
import unittest

import pytest

from limn.builds.artifacts import BuildMapCache
from limn.builds.queries import BuildQueries, _same_source, position_basis
from limn.runtime.documents import Doc, RunPaths

from helpers_figure import BUILD1, BUILD2, JULY, b2_map, figure_doc, viewer_map, write_build


def queries():
    """Require the owner-answered query surface before exercising its real reads."""
    cache = BuildMapCache()
    return BuildQueries(lambda: cache)


def test_historical_selection_does_not_follow_current_map(tmp_path):
    """Switching pages.cur must not change a drag's selected element geometry."""
    doc = figure_doc(
        tmp_path / "paper", RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    )
    write_build(doc, BUILD1, b2_map())
    write_build(doc, BUILD2, b2_map(july=(0.6, 0.3, 0.07, 0.12)))
    selected = queries().selection(doc, BUILD1, 1, JULY)
    assert selected.chosen.frac == JULY
    assert selected.chosen.path == ("B2", "B2/calendar", "B2/calendar/m07")
    assert selected.chosen.source == ("src/B2_calendar.py", 88, 95)
    assert tuple(level for level, _ in selected.ladder) == ("el", "el2", "fig")


def test_a_selected_element_names_each_element_on_its_path(tmp_path):
    """The chosen element carries, root first, each path element's name a person reads: its label, else its part,
    else "" (the root of b2_map() has neither); a strip without a label is named by its part."""
    doc = figure_doc(
        tmp_path / "paper", RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    )
    fmap = b2_map()
    del fmap["pages"][0]["elements"][1]["label"]
    write_build(doc, BUILD1, fmap)
    selected = queries().selection(doc, BUILD1, 1, JULY)
    assert selected.chosen.names == ("", "CalendarStrip", "7월")
    assert [el.names for _, el in selected.ladder] == [("", "CalendarStrip", "7월"), ("", "CalendarStrip"), ("",)]


def test_page_root_is_true_only_for_the_figure_of_that_page_on_that_build(tmp_path):
    """page_root answers whether an id is the root of a page on the named build's map: the figure of page 1 is, a
    panel or the figure of page 2 is not; an unknown page, a build without a map, a build name that names no page
    directory and a document without an element map all answer False."""
    paths = RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    doc = figure_doc(tmp_path / "paper", paths)
    write_build(doc, BUILD1, viewer_map())
    write_build(doc, BUILD2, None)
    ask = queries().page_root
    assert ask(doc, BUILD1, 1, "B2") is True
    assert ask(doc, BUILD1, 2, "B3") is True
    assert ask(doc, BUILD1, 1, "B2/calendar") is False
    assert ask(doc, BUILD1, 1, "B3") is False
    assert ask(doc, BUILD1, 3, "B2") is False
    assert ask(doc, BUILD2, 1, "B2") is False
    assert ask(doc, "../" + BUILD1, 1, "B2") is False
    latex = Doc("ms", "본문", "tex", tmp_path / "paper", tmp_path / "paper" / "main.tex", paths=paths)
    assert ask(latex, BUILD1, 1, "B2") is False


def test_page_facts_add_what_the_map_says_of_each_page(tmp_path):
    """On a figure document meta's pages carry, from the build's map, each page's figure (its root id), its title when
    the map has one and verdict: false only when the map says the page takes no verdict - any other verdict value is
    as if absent. A page the map does not name, a build without a loadable map and a LaTeX document keep the three
    image keys."""
    paths = RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    doc = figure_doc(tmp_path / "paper", paths)
    fmap = viewer_map()
    fmap["pages"][0]["verdict"] = False
    fmap["pages"][1]["verdict"] = "false"  # not JSON false: ignored
    write_build(doc, BUILD1, fmap)
    write_build(doc, BUILD2, None)

    def images():
        return [{"name": "page-%d.png" % n, "pt_w": 600.0, "pt_h": 800.0} for n in (1, 2, 3)]

    ask = queries().page_facts
    assert ask(doc, BUILD1, images()) == [
        {
            "name": "page-1.png",
            "pt_w": 600.0,
            "pt_h": 800.0,
            "figure": "B2",
            "title": "Deployment calendar",
            "verdict": False,
        },
        {"name": "page-2.png", "pt_w": 600.0, "pt_h": 800.0, "figure": "B3", "title": "Review flow"},
        {"name": "page-3.png", "pt_w": 600.0, "pt_h": 800.0},
    ]
    assert ask(doc, BUILD2, images()) == images()
    latex = Doc("ms", "본문", "tex", tmp_path / "paper", tmp_path / "paper" / "main.tex", paths=paths)
    assert ask(latex, BUILD1, images()) == images()


def test_page_facts_say_where_a_figure_body_is_arrived_at(tmp_path):
    """A page whose map names its figure body (<figure>/@figure) carries the body's top edge (figure_top) and the lowest
    bottom edge of the page's elements that end at or above it (figure_above): not an element beside the body starting
    with it, nor one inside it. A body with nothing above it carries no figure_above; a page without a body neither."""
    paths = RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    doc = figure_doc(tmp_path / "paper", paths)

    def el(eid, parent, frac):
        return {"id": eid, "parent": parent, "frac": frac}

    one = [
        {"id": "B2", "frac": [0, 0, 1, 1]},
        el("B2/@head", "B2", [0.05, 0.05, 0.9, 0.1]),
        el("B2/@text", "B2", [0.05, 0.2, 0.9, 0.25]),
        el("B2/@ref", "B2", [0.05, 0.5, 0.4, 0.3]),
        el("B2/@figure", "B2", [0.5, 0.5, 0.45, 0.3]),
        el("B2/@figure/axis", "B2/@figure", [0.55, 0.55, 0.3, 0.1]),
        el("B2/@caption", "B2", [0.05, 0.85, 0.9, 0.1]),
    ]
    two = [{"id": "B3", "frac": [0, 0, 1, 1]}, el("B3/@figure", "B3", [0.1, 0.1, 0.8, 0.5])]
    three = [{"id": "B4", "frac": [0, 0, 1, 1]}, el("B4/@head", "B4", [0.05, 0.05, 0.9, 0.1])]
    fmap = {"format": "limn-figure-map/1", "pdf": "figures.pdf", "pdf_sha256": "0" * 64, "pages": []}
    fmap["pages"] = [{"page": n, "figure": e[0]["id"], "elements": e} for n, e in enumerate((one, two, three), 1)]
    write_build(doc, BUILD1, fmap, pages=3)
    got = queries().page_facts(
        doc, BUILD1, [{"name": "page-%d.png" % n, "pt_w": 600.0, "pt_h": 800.0} for n in (1, 2, 3)]
    )
    assert [{k: v for k, v in p.items() if k.startswith("figure_")} for p in got] == [
        {"figure_top": 0.5, "figure_above": 0.45},
        {"figure_top": 0.1},
        {},
    ]


def test_missing_markers_are_interpreted_by_owner(tmp_path):
    """Absent stamps retain light-poll defaults and an empty outline."""
    doc = figure_doc(
        tmp_path / "paper", RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    )
    q = queries()
    assert q.heading(doc).head is None
    assert q.summary(doc, tmp_path / "state", 150).meta["head"] == "?"
    assert q.outline(doc).text == ""


def test_history_returns_source_equivalence_not_storage_entries(tmp_path):
    """Matching hashes win over different mtimes; unknown builds are never exact."""
    doc = figure_doc(
        tmp_path / "paper", RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    )
    write_build(doc, BUILD1, b2_map())
    write_build(doc, BUILD2, b2_map())
    (doc.dir / "builds.json").write_text(
        json.dumps(
            {
                "seq": 2,
                "builds": [
                    {"build": BUILD1, "src_hash": "same", "src_mtime": 10},
                    {"build": BUILD2, "src_hash": "same", "src_mtime": 20},
                ],
            }
        )
    )
    answer = queries().position(doc)
    assert answer.exact_builds == frozenset({BUILD1, BUILD2})
    assert not hasattr(answer, "by")
    assert "unknown" not in answer.exact_builds


def test_selected_publication_assets_remain_historical(tmp_path):
    """A drag's PDF and pages stay paired with its publication after current changes."""
    doc = figure_doc(
        tmp_path / "paper", RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    )
    write_build(doc, BUILD1, b2_map())
    write_build(doc, BUILD2, b2_map())
    q = queries()
    old = q.publication(doc, BUILD1, tmp_path / "state")
    current = q.publication(doc, q.heading(doc).build, tmp_path / "state")
    assert old.build == BUILD1
    assert current.build == BUILD2
    assert old.pages != current.pages
    assert old.pdf.parent == old.pages
    assert current.pdf.parent == current.pages


@pytest.mark.parametrize("history", ["not JSON", "null", '{"builds": [{"build": 3}]}'])
def test_corrupt_history_retains_missing_defaults(tmp_path, history):
    """Unreadable history is unknown, not an exception or an exact historical match."""
    doc = figure_doc(
        tmp_path / "paper", RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    )
    write_build(doc, BUILD1, b2_map())
    (doc.dir / "builds.json").write_text(history)
    facts = queries().position(doc)
    assert facts.exact_builds == frozenset()
    assert facts.built_at is None
    assert facts.built_src_mtime is None


def test_response_fragments_are_detached_from_live_build_state(tmp_path):
    """A consumer changing a returned HTTP fragment cannot mutate the build owner's state."""
    doc = figure_doc(
        tmp_path / "paper", RunPaths(tmp_path / "paper", tmp_path / "paper" / "main.tex", tmp_path / "state")
    )
    doc.bstate["last"] = {"state": "fail", "errors": [{"text": "original"}]}
    q = queries()
    first = q.summary(doc, tmp_path / "state", 150)
    first.meta["last_build"]["errors"][0]["text"] = "consumer change"
    first.meta["build"]["state"] = "consumer change"
    again = q.summary(doc, tmp_path / "state", 150)
    assert again.meta["last_build"]["errors"][0]["text"] == "original"
    assert again.meta["build"]["state"] == "idle"


class HistoryFacts(unittest.TestCase):
    """Build-owned source equivalence and legacy history defaults."""

    def test_same_source_by_hash_else_mtime_else_different(self):
        """Hashes decide when both exist; otherwise src_mtime within 0.01 s; a missing entry is a different source."""
        self.assertTrue(_same_source({"src_hash": "x", "src_mtime": 1}, {"src_hash": "x", "src_mtime": 9}))
        self.assertTrue(_same_source({"src_mtime": 100.0}, {"src_hash": "y", "src_mtime": 100.004}))
        self.assertFalse(_same_source({"src_mtime": True}, {"src_mtime": True}))
        self.assertFalse(_same_source(None, {"src_hash": "x"}))

    def test_est_basis_fills_a_current_build_missing_from_history(self):
        """Before the history has the current build, it is judged by the recorded mtime; without one, by history."""
        c = position_basis("pages-2", {}, 50.0, 60.0)
        self.assertEqual(
            (c.exact_builds, c.built_src_mtime, c.built_at),
            (frozenset({"pages-2"}), 50.0, 60.0),
        )
        self.assertEqual(position_basis("pages-2", {"pages-2": {"src_mtime": 7}}, None, None).built_src_mtime, 7.0)
        history = {"pages-1": {}}
        position_basis("pages-2", history, None, None)
        self.assertEqual(history, {"pages-1": {}})  # the history read is not changed

    def test_same_source_falls_back_to_src_mtime_without_hash(self):
        a = {"src_hash": None, "src_mtime": 100.0}
        self.assertTrue(_same_source(a, {"src_hash": None, "src_mtime": 100.0}))
        self.assertFalse(_same_source(a, {"src_hash": None, "src_mtime": 101.0}))
        self.assertFalse(_same_source(a, None))
        self.assertFalse(_same_source({"src_hash": "x"}, {"src_hash": "y", "src_mtime": 1}))
