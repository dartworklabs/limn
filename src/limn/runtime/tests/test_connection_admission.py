"""Composition-root cleanup preserves actual fatal process status after real listener and runtime teardown."""

import pytest

from limn.web.tests.fatal_process_support import assert_retired_port, run_fatal_child


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
