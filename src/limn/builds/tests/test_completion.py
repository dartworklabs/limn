"""Completion payload contracts, bounded history properties, and pure dependency guards."""

import ast
from pathlib import Path

import pytest
from hypothesis import example, given, strategies as st

from limn.builds import completion, values as build_values
from limn.builds.completion import project_completion, render_progress
from limn.builds.values import (
    BUILD_STATES,
    BuildAborted,
    BuildFailed,
    BuildOk,
    BuildOkWithErrors,
    CopyFailed,
    PagesDrawn,
)


@pytest.mark.parametrize(
    ("result", "state", "errors", "elapsed", "head", "pull", "pages", "entry"),
    [
        (
            BuildOk("log", 1.2, {"state": "ok"}, 9.0, "hash", "abc", "pages-1", 3),
            "ok",
            [],
            1.2,
            "abc",
            {"state": "ok"},
            3,
            {"build": "pages-1", "src_mtime": 7.0, "src_hash": "hash", "finished_at": "finish"},
        ),
        (
            BuildOkWithErrors([{"msg": "bad"}], "log", 2.0, None, 9.0, None, "abc", "", 2),
            "ok_errors",
            [{"msg": "bad"}],
            2.0,
            "abc",
            None,
            2,
            None,
        ),
        (CopyFailed("copy", 3.0, {"state": "skip"}, 9.0), "fail", [], 3.0, None, {"state": "skip"}, 0, None),
        (
            BuildFailed("no_pdf", "", "raw", [{"msg": "bad"}], 4.0, None, 9.0, "hash"),
            "fail",
            [{"msg": "bad"}],
            4.0,
            None,
            None,
            0,
            None,
        ),
        (BuildAborted("crashed", "detail"), "fail", [], 0.0, None, None, 0, None),
    ],
    ids=["ok", "ok_errors_without_directory", "copy_failed", "build_failed", "aborted"],
)
def test_completion_payloads_for_every_outcome(result, state, errors, elapsed, head, pull, pages, entry):
    """Every outcome preserves history, publication values and JSON insertion order."""
    value = project_completion(result, "finish", "start", 7.0, "rendered log")
    expected_last = {
        "state": state,
        "errors": errors,
        "finished_at": "finish",
        "elapsed_s": elapsed,
        "log_tail": "rendered log",
        "head": head,
        "pull": pull,
        "started_at": "start",
    }
    assert value.last == expected_last
    assert list(value.last) == list(expected_last)
    assert value.entry == entry
    if entry is not None:
        assert list(value.entry) == list(entry)
    expected_live = {
        "state": state,
        "phase": None,
        "start_ts": None,
        "seq": 12,
        "finished_at": "finish",
        "elapsed_s": elapsed,
        "last_s": elapsed,
        "pages": pages,
        "errors": errors,
        "head": head,
        "pull": pull,
        "log_tail": "rendered log",
        "built_at": "built",
        "last": {"state": state, "errors": errors, "finished_at": "finish", "seq": 12, "head": head, "pull": pull},
    }
    live = value.publication(12, "built")
    assert live == expected_live
    assert list(live) == list(expected_live)
    assert list(live["last"]) == list(expected_live["last"])


@example("prefix" + "x" * 4000, [8, 6, 4, 2, 0, -2])
@given(st.text(max_size=5000), st.lists(st.integers(), max_size=20))
def test_history_is_bounded_suffix_and_errors_are_stable_prefix(log, lines):
    """History retains a suffix and the earliest five errors, while live output loses no log text."""
    errors = [{"line": line, "msg": str(index)} for index, line in enumerate(lines)]
    result = BuildFailed("no_pdf", "", None, errors, 1.0, None, None, None)
    value = project_completion(result, "finish", None, None, log)
    tail = value.last["log_tail"]
    visible = value.last["errors"]
    assert len(tail) == min(len(log), 4000)
    assert log.endswith(tail)
    assert len(visible) == min(len(errors), 5)
    assert all(actual == expected for actual, expected in zip(visible, errors, strict=False))
    assert result.errors == errors
    assert value.publication(1, None)["log_tail"] == log
    assert value.entry is None


@given(st.text(min_size=1), st.floats(allow_nan=False, allow_infinity=False))
def test_successful_history_uses_explicit_baseline_and_directory(directory, baseline):
    """Successful builds retain arbitrary directory text and the compiled baseline supplied by the shell."""
    result = BuildOkWithErrors([], "", 1.0, None, 99.0, "hash", "head", directory, 1)
    value = project_completion(result, "finish", None, baseline, "")
    assert value.entry == {
        "build": directory,
        "src_mtime": baseline,
        "src_hash": "hash",
        "finished_at": "finish",
    }


@example(0, 0)
@example(-1, 3)
@example(4, 3)
@example(3, 3)
@given(st.integers(min_value=-5, max_value=1000), st.integers(min_value=-5, max_value=1000))
def test_pages_drawn_exists_only_for_a_count_within_a_counted_pdf(done, total):
    """A render's count is made exactly when the PDF has pages (total > 0) and 0 <= done <= total; any other pair is
    refused when it is made, so GET /api/build never carries a share outside 0..1 or a page count of zero."""
    if total > 0 and 0 <= done <= total:
        assert (PagesDrawn(done, total).done, PagesDrawn(done, total).total) == (done, total)
    else:
        with pytest.raises(ValueError):
            PagesDrawn(done, total)


@pytest.mark.parametrize(("done", "total"), [(True, 3), (1, True), (1.0, 3), (1, "3")])
def test_pages_drawn_refuses_what_is_not_a_plain_integer(done, total):
    """A bool or a non-integer count is refused like an out-of-range one (bool is an int to Python, not a page count)."""
    with pytest.raises(ValueError):
        PagesDrawn(done, total)


@pytest.mark.parametrize(
    ("state", "phase", "drawn", "expected"),
    [
        ("running", "render", PagesDrawn(0, 3), {"done": 0, "total": 3}),
        ("running", "render", PagesDrawn(2, 3), {"done": 2, "total": 3}),
        ("running", "render", PagesDrawn(3, 3), {"done": 3, "total": 3}),
        ("running", "render", None, None),
        ("running", "latex", None, None),
        ("running", "latex", PagesDrawn(3, 3), None),
        ("running", "copy", PagesDrawn(1, 3), None),
        ("running", "pull", None, None),
        ("running", None, None, None),
        ("ok", None, PagesDrawn(3, 3), None),
        ("ok_errors", None, PagesDrawn(3, 3), None),
        ("fail", None, PagesDrawn(1, 3), None),
        ("fail", "render", PagesDrawn(1, 3), None),
        ("idle", None, None, None),
    ],
    ids=[
        "render_counted",
        "render_midway",
        "render_all_drawn",
        "render_before_pdfinfo",
        "latex",
        "latex_after_an_earlier_render",
        "copy_after_an_earlier_render",
        "pull",
        "running_without_phase",
        "finished_ok",
        "finished_ok_errors",
        "failed",
        "failed_in_render",
        "idle",
    ],
)
def test_progress_is_the_page_count_only_while_a_running_build_renders(state, phase, drawn, expected):
    """GET /api/build `progress` is {done, total} only while a running build draws its pages and has counted them; a
    TeX pass, the copy, the pull, a render still counting pages, a finished build and a count left over from an earlier
    render all answer None (the viewer's bar then does not know its end)."""
    got = render_progress(state, phase, drawn)
    assert got == expected
    if got is not None:
        assert list(got) == ["done", "total"]


@given(
    st.sampled_from(BUILD_STATES),
    st.sampled_from(["pull", "copy", "latex", "render", None]),
    st.one_of(st.none(), st.integers(1, 500).flatmap(lambda n: st.builds(PagesDrawn, st.integers(0, n), st.just(n)))),
)
def test_progress_is_a_share_of_a_counted_render_or_nothing(state, phase, drawn):
    """Whatever the build state holds, progress is None outside a running render, and in one it is a share 0..1 of a
    PDF with pages (0 <= done <= total, total > 0)."""
    got = render_progress(state, phase, drawn)
    if state != "running" or phase != "render":
        assert got is None
    if got is not None:
        assert 0 <= got["done"] <= got["total"] and got["total"] > 0


@pytest.mark.parametrize("module", [completion, build_values])
def test_completion_dependency_closure_has_no_io_imports(module):
    """The projection and its shared outcome owner cannot import clocks, files, or effectful build helpers."""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported <= {"dataclasses", "typing", "collections.abc", "limn.builds.values"}
