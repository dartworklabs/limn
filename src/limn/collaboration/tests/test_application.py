"""Collaboration views consume only pin read facts and fail closed."""

import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from limn.collaboration import PeopleView
from limn.pins import PinReadView
from limn.pins.model import parse_pin
from limn.security import people


class PeopleViewTests(unittest.TestCase):
    """Malformed people data never widens known people or admits agents."""

    def test_unreadable_people_file_uses_non_agent_pin_facts_only(self) -> None:
        """A broken file contributes nobody while human pin actors remain available."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "people.json"
            path.write_text("{broken", encoding="utf-8")
            pins = [
                parse_pin({"id": 1, "author": {"login": "alice@example.com", "name": "Alice"}}),
                parse_pin({"id": 2, "author": {"login": "agent:writer", "name": "Writer"}}),
            ]
            pin_view = PinReadView(lambda: (pins, []), lambda: pins, lambda _record: "paper")
            view = PeopleView.create(
                state=lambda: root,
                people_file=lambda: path,
                lock=lambda: threading.Lock(),
                seen=lambda: people.SeenMemo(),
                warning=lambda: people.UnreadableWarning(),
                pins=pin_view,
                roles=lambda: {},
                clock=lambda: 0.0,
            )

            self.assertEqual(set(view.known()), {"alice@example.com"})

    def test_importing_people_view_does_not_load_http_adapters(self) -> None:
        """The people contract remains importable without collaboration routes."""
        code = (
            "import sys; from limn.collaboration import PeopleView; "
            "print(sorted(n for n in sys.modules if n.startswith('limn.collaboration.') and (n.endswith('.http') or n.endswith('.routes'))))"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "[]"), result.stderr)
