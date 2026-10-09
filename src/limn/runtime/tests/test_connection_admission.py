"""Composition-root cleanup preserves actual fatal process status after real listener and runtime teardown."""

import argparse

import pytest
from hypothesis import example, given, strategies as st

from limn import server as composition
from limn.runtime.args import positive_connections
from limn.runtime.startup import StartupRefused
from limn.web.tests.fatal_process_support import assert_retired_port, run_fatal_child

from helpers import DEFAULT_ACCESS, TEX


@given(st.text())
@example("0")
def test_connection_cap_parser_answers_any_text_with_positive_int_or_usage_error(raw):
    """Untrusted option text always has a positive result or a stable argparse rejection."""
    try:
        result = positive_connections(raw)
    except argparse.ArgumentTypeError as error:
        assert str(error) == "must be a positive integer"
    else:
        assert isinstance(result, int) and result > 0


@given(st.integers(min_value=1))
def test_connection_cap_accepts_generated_positive_integers(number):
    """A supported positive integer representation round-trips without a policy maximum."""
    assert positive_connections(str(number)) == number


@pytest.mark.parametrize("cap", [None, "1", "7"])
def test_connection_cap_parses_and_reaches_run_settings(tmp_path, cap):
    """Only an explicit positive cap reaches the frozen settings; omission stays disabled."""
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    (manuscript / "main.tex").write_text(TEX, encoding="utf-8")
    argv = ["--manuscript", str(manuscript), "--state-dir", str(tmp_path / "state"), "--port", "18300"]
    if cap is not None:
        argv.extend(["--max-connections", cap])
    parsed = composition.build_arg_parser().parse_args(argv)
    assert getattr(parsed, "max_connections", "missing") == (None if cap is None else int(cap))
    configured = composition.configure_run(parsed, DEFAULT_ACCESS)
    assert not isinstance(configured, StartupRefused)
    assert configured.config.max_connections == (None if cap is None else int(cap))


@pytest.mark.parametrize("raw", ["0", "-1", "", "1.5", "many"])
def test_invalid_connection_cap_is_a_usage_error(tmp_path, raw, capsys):
    """Invalid caps stop in argparse before creating any startup state directory."""
    state = tmp_path / "state"
    with pytest.raises(SystemExit) as result:
        composition.build_arg_parser().parse_args(
            ["--manuscript", str(tmp_path), "--state-dir", str(state), "--max-connections", raw]
        )
    assert result.value.code != 0
    assert "must be a positive integer" in capsys.readouterr().err
    assert not state.exists()


def test_missing_connection_cap_value_is_a_usage_error(tmp_path):
    """A missing N is an argparse usage failure before startup writes or listens."""
    with pytest.raises(SystemExit) as result:
        composition.build_arg_parser().parse_args(["--manuscript", str(tmp_path), "--max-connections"])
    assert result.value.code != 0


def test_long_connection_cap_follows_the_interpreters_integer_contract(tmp_path):
    """Large positive integers have no invented cap; conversion limits remain usage errors."""
    raw = "9" * 5000
    argv = ["--manuscript", str(tmp_path), "--max-connections", raw]
    try:
        expected = int(raw)
    except (ValueError, OverflowError):
        with pytest.raises(SystemExit) as result:
            composition.build_arg_parser().parse_args(argv)
        assert result.value.code != 0
    else:
        parsed = composition.build_arg_parser().parse_args(argv)
        assert parsed.max_connections == expected


@pytest.mark.parametrize("effect", ["none", "before", "after", "main-warning", "runtime-zero"])
@pytest.mark.parametrize("scenario", ["claimed", "zero"])
def test_main_retains_fatal_nonzero_through_cleanup(tmp_path, scenario, effect):
    """main keeps fatal nonzero after live claimed TCP refusal, physical cleanup and real watcher retirement."""
    result = run_fatal_child(tmp_path, scenario, effect, main=True)
    assert result.status > 0, result
    assert result.observation["original_retained"], result
    assert result.observation["main_thread"], result
    assert result.observation["runtime_stopped"], result
    assert result.observation["listener_closed"], result
    assert result.observation["held_before_cleanup"] == 1, result
    if scenario == "claimed":
        phase = result.observation["claimed_live_phase"]
        assert phase["parent_closed_connection"] and phase["held_before_cleanup"] == 1, result
        assert phase["cleanup_withheld"] and phase["child_alive_during_probe"], result
        assert phase["tcp_refused_before_cleanup"], result
        assert result.observation["held_after_cleanup"] == 0, result
    assert_retired_port(result.address)
