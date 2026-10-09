"""Real child MainThread outcomes pin fatal uncertainty, diagnostics and irreversible ownership fencing."""

import pytest

from limn.web.tests.fatal_process_support import assert_retired_port, run_fatal_child


@pytest.mark.parametrize(
    "scenario,cause",
    [
        ("no-worker", "RuntimeError"),
        ("claimed", "RuntimeError"),
        ("interrupt", "KeyboardInterrupt"),
        ("zero", "SystemExit"),
    ],
)
def test_invoked_start_failure_exits_nonzero_with_safe_diagnostic(tmp_path, scenario, cause):
    """Failure inside invoked start exits the actual main thread, preserves cause and reports its safe type."""
    result = run_fatal_child(tmp_path, scenario)
    assert result.status > 0, result
    assert result.observation["main_thread"]
    assert result.observation["original_retained"]
    assert result.observation["listener_closed"]
    assert result.observation["admission_fenced"]
    assert cause in result.stderr, result
    assert "owned native startup failure" not in result.stderr
    assert_retired_port(result.address)


@pytest.mark.parametrize("scenario", ["pending", "claimed", "no-worker"])
def test_uncertain_worker_keeps_lease_until_its_own_cleanup(tmp_path, scenario):
    """Parent real FD closure cannot return a possible worker's lease or allow pending handler entry."""
    result = run_fatal_child(tmp_path, scenario)
    assert result.status > 0, result
    seen = result.observation
    assert seen["held_before_cleanup"] == 1, result
    assert seen["parent_closed_connection"], result
    assert seen["held_after_cleanup"] == (1 if scenario == "no-worker" else 0), result
    assert seen["handler_after_release"] == (scenario == "claimed"), result
    assert_retired_port(result.address)


@pytest.mark.parametrize(
    "effect",
    [
        "before",
        "after",
        "fallback",
        "diagnostic",
        "parent",
        "coordination",
        "fuse-coordination",
        "fuse-parent",
        "all-coordination-parent",
    ],
)
def test_secondary_fatal_effects_keep_nonzero_and_primary_cause(tmp_path, effect):
    """Real before/after close, fallback, parent close, logging and coordination faults remain subordinate."""
    result = run_fatal_child(tmp_path, "pending", effect)
    assert result.status > 0, result
    seen = result.observation
    assert seen["original_retained"], result
    assert seen["admission_fenced"], result
    assert seen["held_before_cleanup"] == 1, result
    assert not seen["handler_after_release"], result
    assert seen["listener_closed"] == (effect != "fallback"), result
    assert_retired_port(result.address)


@pytest.mark.parametrize("effect", ["none", "coordination"])
def test_worker_cleanup_zero_exit_reaches_main_loop_without_releasing_lease(tmp_path, effect):
    """A daemon cleanup fault publishes nonzero to the real main loop even if state recording also fails."""
    result = run_fatal_child(tmp_path, "cleanup", effect)
    assert result.status > 0, result
    assert result.observation["original_retained"], result
    assert result.observation["admission_fenced"], result
    assert result.observation["held_before_cleanup"] == 1, result
    assert result.observation["held_after_cleanup"] == 1, result
    assert not result.observation["parent_closed_connection"], result
    assert "SystemExit (code 0)" in result.stderr, result
    assert_retired_port(result.address)


def test_constructor_failure_with_live_makefile_ref_cannot_reclaim_real_fd(tmp_path):
    """socket.close with a live makefile ref is insufficient physical attestation for pre-call recovery."""
    result = run_fatal_child(tmp_path, "construction")
    assert result.status > 0, result
    assert result.observation["original_retained"], result
    assert result.observation["held_before_cleanup"] == result.observation["held_after_cleanup"] == 1, result
    assert not result.observation["parent_closed_connection"], result
    assert result.observation["connection_closed_after_stream"], result
    assert not result.observation["handler_after_release"], result
    assert_retired_port(result.address)


def test_cleanup_fuse_fences_pending_entry_before_blocked_coordination(tmp_path):
    """A pending handler cannot enter while fatal cleanup coordination is still blocked before stop."""
    result = run_fatal_child(tmp_path, "cleanup-barrier")
    assert result.status > 0, result
    seen = result.observation
    assert seen["original_retained"], result
    assert seen["main_thread"] and seen["listener_closed"], result
    assert seen["coordinator_blocked"] and not seen["pure_state_stopped_before_poll"], result
    assert not seen["pending_handler_entered"], result
    assert not seen["failing_connection_closed"] and seen["pending_connection_closed"], result
    assert seen["held_before_cleanup"] == seen["held_after_cleanup"] == 1, result
    assert_retired_port(result.address)
