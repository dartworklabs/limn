"""Malformed token-store envelopes fail closed in HTTP and cannot be rewritten by the CLI."""

import json
import os
import subprocess
import sys

import pytest
from hypothesis import given, seed, settings, strategies as st

from limn.security import access

from helpers import Base, req, split_resp

MALFORMED = [
    7,
    True,
    None,
    "invalid",
    [],
    {},
    {"tokens": 7},
    {"tokens": True},
    {"tokens": "invalid"},
    {"tokens": None},
    {"tokens": {"entry": {"id": "synthetic", "name": "agent", "hash": "ignored"}}},
]


@pytest.mark.parametrize("value", MALFORMED)
def test_unusable_token_file_returns_no_rows_and_strictly_rejects_without_writing(tmp_path, value):
    """Unreadable envelopes admit no tokens and both strict CLI mutations preserve the original file."""
    path = tmp_path / "tokens.json"
    raw = (json.dumps(value) + "\n").encode("utf-8")
    path.write_bytes(raw)
    before = path.stat().st_mtime_ns
    assert access.load_tokens(tmp_path) == []
    with pytest.raises(ValueError, match="not a Limn token file"):
        access.load_tokens(tmp_path, strict=True)
    for operation in (["create", "--name", "synthetic"], ["revoke", "synthetic"]):
        result = subprocess.run(
            [sys.executable, "-m", "limn", "token", *operation, "--state-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=dict(os.environ, PYTHONPATH=str(access.__file__).rsplit("/limn/", 1)[0]),
        )
        assert result.returncode != 0
        assert "not a Limn token file" in result.stderr
        assert path.read_bytes() == raw
        assert path.stat().st_mtime_ns == before
        assert not (tmp_path / "audit.jsonl").exists()


class MalformedTokenHTTP(Base):
    """Actual HTTP authentication never falls back to editor identity when the token store is unusable."""

    def test_scalar_tokens_are_401_without_pin_or_token_writes(self):
        """Every malformed envelope denies Bearer reads and writes as bad_token, including with human headers."""
        state = self.src.parent / "state"
        path = state / "tokens.json"
        pins = state / "pins.jsonl"
        for value in MALFORMED:
            raw = (json.dumps(value) + "\n").encode()
            path.write_bytes(raw)
            before = path.stat().st_mtime_ns
            pin_before = pins.read_bytes() if pins.exists() else None
            for method, endpoint, body in [
                ("GET", "/api/pins", b""),
                (
                    "POST",
                    "/api/pin",
                    json.dumps({"file": "main.tex", "lo": 1, "hi": 1, "note": "Must not be saved"}).encode(),
                ),
            ]:
                out = self.talk(
                    req(
                        method,
                        endpoint,
                        body,
                        headers={
                            "Authorization": "Bearer limn_synthetic_unknown",
                            "Tailscale-User-Login": "alice@example.com",
                            "Tailscale-User-Name": "Alice",
                            "Content-Type": "application/json",
                        },
                    )
                )
                code, _, payload = split_resp(out)
                self.assertEqual((code, json.loads(payload).get("reason")), (401, "bad_token"), value)
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(path.stat().st_mtime_ns, before)
                self.assertEqual(pins.read_bytes() if pins.exists() else None, pin_before)


@seed(20261011)
@settings(max_examples=100, deadline=None, database=None)
@given(
    st.one_of(st.none(), st.booleans(), st.integers(), st.text(), st.dictionaries(st.text(), st.integers(), max_size=5))
)
def test_generated_nonlist_token_members_return_no_rows(value):
    """The pure token-envelope parser rejects any generated nonlist member without an exception."""
    assert access._valid_tokens({"tokens": value}) == []
