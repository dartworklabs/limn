"""Stored time and Unicode defects must leave healthy pins available and preserve bad bytes."""

import http.client
import json
import math
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import example, given, seed, settings, strategies as st

from limn import server
from limn.pins.location.position import epoch
from limn.pins.record import Broken, parse_record, parse_trashed
from limn.pins.store import dump_jsonl

from helpers import blank_png, minimal_pdf


@pytest.fixture
def stored_server(tmp_path):
    """Start the real loopback server with reusable valid artifacts and release its listener and runtime."""
    source, state = tmp_path / "source", tmp_path / "state"
    source.mkdir()
    (source / "main.tex").write_text("First synthetic line.\nSecond synthetic line.\n", encoding="utf-8")
    pages = state / "pages"
    pages.mkdir(parents=True)
    (pages / "main.pdf").write_bytes(minimal_pdf("Stored input fixture"))
    (pages / "page-1.png").write_bytes(blank_png(100, 100))
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    args = server.build_arg_parser().parse_args(
        [
            "--manuscript",
            str(source),
            "--main",
            "main.tex",
            "--state-dir",
            str(state),
            "--port",
            str(port),
            "--auth",
            "tailscale",
            "--no-agent-loopback",
            "--no-build",
        ]
    )
    started = server.start(args)
    assert isinstance(started, server.StartedServer), started
    worker = threading.Thread(target=started.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield source, state, started.server.server_address[1]
    finally:
        started.server.shutdown()
        started.server.server_close()
        started.runtime.stop()
        worker.join(5)
        assert not worker.is_alive()


def request(port, method="GET", path="/api/pins", body=None):
    """Send real HTTP as a synthetic admitted editor and return its status and decoded body."""
    headers = {"Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        connection.request(method, path, None if body is None else json.dumps(body), headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def row(source, pid, **changes):
    """Construct a legacy line record whose empty anchor prevents a read-time rewrite."""
    return dict(
        {
            "id": pid,
            "file": str(source / "main.tex"),
            "lo": 1,
            "hi": 1,
            "page": 1,
            "note": "Synthetic note",
            "anchor": {},
            "synced_at": time.time() + 100,
            "at": "2026-10-11 00:00:00",
        },
        **changes,
    )


@pytest.mark.parametrize("timestamp", ["0001-01-01 00:00:00", "9999-12-31 23:59:59"])
def test_out_of_local_range_timestamp_keeps_all_pins_available(stored_server, timestamp):
    """A legacy timestamp at a platform conversion bound cannot turn a healthy list into 500."""
    source, state, port = stored_server
    rows = [row(source, 100), row(source, 101, at=timestamp)]
    raw = "".join(json.dumps(value) + "\n" for value in rows).encode("utf-8")
    path = state / "pins.jsonl"
    path.write_bytes(raw)
    before = path.stat().st_mtime_ns
    code, body = request(port)
    assert code == 200, body
    assert [pin["id"] for pin in body] == [100, 101]
    assert path.read_bytes() == raw
    assert path.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    "corrupt",
    [
        {"note": "\ud800"},
        {"author": {"login": "alice@example.com", "name": "\udfff"}},
        {"future_field": {"nested": ["\ud800"]}},
        {"future_field": {"\udfff": "value"}},
        {"\ud800": "unknown key"},
    ],
)
def test_surrogate_row_is_quarantined_before_next_write(stored_server, corrupt, capfd):
    """Unencodable known or unknown strings are skipped; the next write keeps byte-exact corrupt backup."""
    source, state, port = stored_server
    good = row(source, 100, future_field={"nested": ["한글", "😀", {"unknown": True}]})
    raw = "".join(json.dumps(value, ensure_ascii=True) + "\n" for value in [good, row(source, 101, **corrupt)]).encode()
    path = state / "pins.jsonl"
    path.write_bytes(raw)
    before = path.stat().st_mtime_ns
    code, body = request(port)
    assert code == 200, body
    assert [pin["id"] for pin in body] == [100]
    assert body[0]["future_field"] == good["future_field"]
    assert path.read_bytes() == raw
    assert path.stat().st_mtime_ns == before
    assert not list(state.glob("pins.jsonl.corrupt-*.bak"))
    assert "line [2]" in capfd.readouterr().err
    code, body = request(
        port, "POST", "/api/pin", {"file": "main.tex", "lo": 2, "hi": 2, "page": 1, "note": "Healthy append"}
    )
    assert code == 200, body
    backups = list(state.glob("pins.jsonl.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [pin["id"] for pin in remaining] == [100, body["id"]]
    assert remaining[0] == good
    assert "Healthy append" in (state / "pins.md").read_text(encoding="utf-8")
    assert request(port)[0] == 200


@seed(20261011)
@settings(max_examples=100, deadline=None, database=None)
@given(
    st.one_of(
        st.text(),
        st.none(),
        st.integers(),
        st.datetimes(
            timezones=st.sampled_from(
                [None, timezone.utc, timezone(timedelta(hours=14)), timezone(timedelta(hours=-12))]
            )
        ).map(lambda value: value.isoformat(sep=" ")),
    )
)
@example("0001-01-01 00:00:00")
@example("9999-12-31 23:59:59")
def test_epoch_always_returns_a_finite_value_or_none(value):
    """Generated naive, aware, malformed and non-string inputs have a total finite-or-None parser."""
    result = epoch(value)
    assert result is None or math.isfinite(result)


@seed(20261011)
@settings(max_examples=100, deadline=None, database=None)
@given(
    st.datetimes(
        timezones=st.sampled_from([timezone.utc, timezone(timedelta(hours=14)), timezone(timedelta(hours=-12))])
    )
)
@example(datetime.min.replace(tzinfo=timezone(timedelta(hours=14))))
@example(datetime.max.replace(tzinfo=timezone(timedelta(hours=-12))))
def test_aware_time_preserves_absolute_epoch(value):
    """Explicit offsets identify an absolute instant independently of the server's local conversion limits."""
    assert epoch(value.isoformat()) == value.timestamp()


@pytest.mark.parametrize("zone", ["UTC0", "KST-9", "EST5EDT,M3.2.0,M11.1.0", "GMT+12"])
def test_epoch_local_zone_bounds_and_ordinary_local_semantics(zone):
    """Real local timezone conversion catches calendar bounds while preserving the server-local timestamp meaning."""
    previous = os.environ.get("TZ")
    try:
        os.environ["TZ"] = zone
        time.tzset()
        for value in [datetime.min, datetime.max, datetime(2024, 3, 10, 1, 30), datetime(2024, 11, 3, 1, 30)]:
            result = epoch(value.isoformat(sep=" "))
            assert result is None or math.isfinite(result)
        ordinary = datetime(2026, 6, 1, 12, 34, 56)
        assert epoch(ordinary.isoformat(sep=" ")) == ordinary.timestamp()
        assert epoch("1970-01-01T00:00:00+00:00") == 0
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def parsed_record(value, trash=False):
    """Parse a synthetic legacy record with open document and actor rules, without any I/O."""
    return (parse_trashed if trash else parse_record)(
        value, lambda key: key.isalpha(), lambda actor: isinstance(actor, dict)
    )


STORED_TEXT = st.one_of(
    st.text(),
    st.tuples(st.text(max_size=8), st.integers(min_value=0xD800, max_value=0xDFFF).map(chr), st.text(max_size=8)).map(
        lambda pieces: "".join(pieces)
    ),
)
JSON_VALUES = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(), STORED_TEXT),
    lambda values: st.one_of(st.lists(values, max_size=5), st.dictionaries(STORED_TEXT, values, max_size=5)),
    max_leaves=20,
)


@seed(20261011)
@settings(max_examples=100, deadline=None, database=None)
@given(JSON_VALUES)
@example({"nested": ["\ud800"]})
@example({"\udfff": "unknown key"})
@example({"nested": ["한글", "😀", None]})
def test_unknown_json_fields_round_trip_or_are_quarantined(value):
    """All accepted stored JSON survives UTF-8 serialization; invalid text is Broken without mutating any field."""
    record = {"id": 3, "file": "/ms/main.tex", "lo": 1, "hi": 1, "future_field": value}
    before = json.dumps(record, ensure_ascii=True)
    try:
        json.dumps(record, ensure_ascii=False).encode("utf-8")
        encodable = True
    except UnicodeEncodeError:
        encodable = False
    for trash in [False, True]:
        pin = parsed_record(record, trash)
        assert isinstance(pin, Broken) != encodable
        if encodable:
            encoded = dump_jsonl([pin.record]).encode("utf-8")
            assert json.loads(encoded) == record
            assert list(pin.record) == list(record)
    assert json.dumps(record, ensure_ascii=True) == before
