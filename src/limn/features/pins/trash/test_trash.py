"""Tests for the Trash and bulk clear feature slice.

Colocated feature tests verifying:
- Input parsing for clear endpoint (parse_clear, confirmation phrase)
- HTTP routes and protocol adapter (drop, restore, purge, clear)
- Invariant enforcement (not in trash -> 404, already live -> 409)
"""

from collections.abc import Mapping
from typing import Any

import pytest

from limn.features.pins.trash import http, input as trash_input
from limn.features.pins.trash.input import CLEAR_CONFIRM, ClearConfirmed
from limn.features.pins.trash.rules import AlreadyLive, NotInTrash
from limn.pins.model import OpenPin, PinNotFound, Record, TrashedPin
from limn.web.errors import HTTPError, InputRejected

# ---------------------------------------------------------------------------
# Test Stubs
# ---------------------------------------------------------------------------


class StubPinTrash:
    """Stub PinTrash implementation for exercising HTTP answers."""

    def __init__(self) -> None:
        self.drop_result: TrashedPin | PinNotFound = PinNotFound(1)
        self.restore_result: OpenPin | NotInTrash | AlreadyLive = NotInTrash(1)
        self.purge_result: TrashedPin | NotInTrash = NotInTrash(1)
        self.clear_result: dict[str, Any] = {"cleared": 0, "archive": "pins_bak.jsonl"}

    def drop_pin(self, pid: int, actor: Mapping[str, Any]) -> TrashedPin | PinNotFound:
        return self.drop_result

    def restore_pin(self, pid: int, actor: Mapping[str, Any]) -> OpenPin | NotInTrash | AlreadyLive:
        return self.restore_result

    def purge_pin(self, pid: int, actor: Mapping[str, Any]) -> TrashedPin | NotInTrash:
        return self.purge_result

    def clear_pins(self, actor: Mapping[str, Any]) -> dict[str, Any]:
        return self.clear_result


class StubTrashApp:
    """App implementing TrashApp protocol with stub services."""

    def __init__(self, pin_trash: Any) -> None:
        self.pin_trash = pin_trash

    def public(self, record: Record) -> dict[str, Any]:
        return dict(record)


# ---------------------------------------------------------------------------
# 1. Input Parsing Tests
# ---------------------------------------------------------------------------


class TestTrashInputParsing:
    """Unit tests for parse_clear."""

    def test_parse_clear_valid_confirmation(self) -> None:
        res = trash_input.parse_clear({"confirm": CLEAR_CONFIRM})
        assert isinstance(res, ClearConfirmed)

    def test_parse_clear_invalid_confirmation(self) -> None:
        for bad in ({}, {"confirm": "wrong"}, {"confirm": None}, {"confirm": "clear all"}):
            res = trash_input.parse_clear(bad)
            assert isinstance(res, InputRejected)
            assert res.reason == "confirm_required"


# ---------------------------------------------------------------------------
# 2. HTTP Adapter & Invariant Tests
# ---------------------------------------------------------------------------


class TestTrashHttpAdapter:
    """HTTP endpoint logic tests using TrashApp protocol."""

    def test_drop_found_and_not_found(self) -> None:
        stub = StubPinTrash()
        app = StubTrashApp(stub)
        actor = {"login": "alice"}

        # Not found
        stub.drop_result = PinNotFound(1)
        res = http.drop(app, 1, actor)
        assert res == {"ok": False}

        # Found and trashed
        pin_record = {
            "id": 1,
            "file": "x.tex",
            "lo": 1,
            "hi": 2,
            "dropped_at": "2026-09-28 12:00:00",
            "dropped_by": actor,
        }
        stub.drop_result = TrashedPin.from_record(pin_record)
        res = http.drop(app, 1, actor)
        assert res == {"ok": True}

    def test_restore_success(self) -> None:
        stub = StubPinTrash()
        app = StubTrashApp(stub)
        actor = {"login": "alice"}

        restored_pin = OpenPin.from_record({"id": 1, "file": "x.tex", "lo": 1, "hi": 2})
        stub.restore_result = restored_pin

        res = http.restore(app, 1, actor)
        assert res["ok"] is True
        assert res["pin"] == restored_pin.record

    def test_restore_not_in_trash_raises_404(self) -> None:
        stub = StubPinTrash()
        app = StubTrashApp(stub)
        actor = {"login": "alice"}

        stub.restore_result = NotInTrash(42)
        with pytest.raises(HTTPError) as exc_info:
            http.restore(app, 42, actor)

        err = exc_info.value
        assert err.code == 404
        assert err.body["reason"] == "not_in_trash"

    def test_restore_already_live_raises_409(self) -> None:
        stub = StubPinTrash()
        app = StubTrashApp(stub)
        actor = {"login": "alice"}

        stub.restore_result = AlreadyLive(42)
        with pytest.raises(HTTPError) as exc_info:
            http.restore(app, 42, actor)

        err = exc_info.value
        assert err.code == 409
        assert err.body["reason"] == "pin_exists"

    def test_purge_success(self) -> None:
        stub = StubPinTrash()
        app = StubTrashApp(stub)
        actor = {"login": "alice"}

        pin_record = {
            "id": 5,
            "file": "x.tex",
            "lo": 1,
            "hi": 2,
            "dropped_at": "2026-09-28 12:00:00",
            "dropped_by": actor,
        }
        stub.purge_result = TrashedPin.from_record(pin_record)

        res = http.purge(app, 5, actor)
        assert res == {"ok": True, "purged": 5}

    def test_purge_not_in_trash_raises_404(self) -> None:
        stub = StubPinTrash()
        app = StubTrashApp(stub)
        actor = {"login": "alice"}

        stub.purge_result = NotInTrash(5)
        with pytest.raises(HTTPError) as exc_info:
            http.purge(app, 5, actor)

        err = exc_info.value
        assert err.code == 404
        assert err.body["reason"] == "not_in_trash"

    def test_clear_phrase_enforcement(self) -> None:
        stub = StubPinTrash()
        app = StubTrashApp(stub)
        actor = {"login": "alice"}

        # Bad confirm phrase -> 400
        with pytest.raises(HTTPError) as exc_info:
            http.clear(app, actor, {"confirm": "no"})
        assert exc_info.value.code == 400
        assert exc_info.value.body["reason"] == "confirm_required"

        # Correct phrase -> 200 with result
        stub.clear_result = {"cleared": 3, "archive": "pins_123.bak"}
        res = http.clear(app, actor, {"confirm": CLEAR_CONFIRM})
        assert res["ok"] is True
        assert res["cleared"] == 3
        assert res["archive"] == "pins_123.bak"
