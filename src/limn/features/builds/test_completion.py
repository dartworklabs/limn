"""Completion payload contracts, bounded history properties, and pure dependency guards."""

import ast
from pathlib import Path

import pytest
from hypothesis import example, given, strategies as st

from limn import build_values
from limn.build_values import BuildAborted, BuildFailed, BuildOk, BuildOkWithErrors, CopyFailed
from limn.features.builds import completion
from limn.features.builds.completion import project_completion


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
    assert imported <= {"dataclasses", "typing", "collections.abc", "limn.build_values"}
