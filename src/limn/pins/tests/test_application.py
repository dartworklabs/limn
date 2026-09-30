"""Public pin read contracts expose projections without models or storage."""

import subprocess
import sys
import unittest

from limn.pins import PinReadView
from limn.pins.model import parse_pin


class PinReadViewTests(unittest.TestCase):
    """Consumers receive counts, people facts, and one revision projection."""

    def setUp(self) -> None:
        """Bind three records in different documents and states."""
        head = "a" * 40
        self.head = head
        self.records = [
            {
                "id": 1,
                "doc": "paper",
                "file": "/old/paper/main.tex",
                "lo": 4,
                "hi": 4,
                "author": {"login": "alice@example.com", "name": "Alice"},
                "done_at": "now",
                "changes_at": "now",
                "close_ref": head[:8],
                "changes": [{"file": "/old/paper/main.tex", "lo": 10, "hi": 12}],
            },
            {"id": 2, "doc": "paper", "done": True, "review": True},
            {"id": 3, "doc": "removed"},
        ]
        pins = [parse_pin(record) for record in self.records]
        self.view = PinReadView(
            _read=lambda: (pins, []),
            _snapshot=lambda: pins,
            _document_key=lambda record: str(record.get("doc") or "paper"),
        )

    def test_counts_and_people_are_plain_read_facts(self) -> None:
        """Document and collaboration consumers do not receive mutable pin values."""
        counts, other = self.view.counts_by_document({"paper"})

        self.assertEqual((counts, other), ({"paper": 1, "removed": 1}, 1))
        self.assertEqual(self.view.state_counts(), {"n_open": 2, "n_done": 0, "n_review": 1})
        self.assertEqual(self.view.people_records()[0]["author"]["login"], "alice@example.com")
        self.assertIsNot(self.view.people_records()[0], self.records[0])

    def test_revision_projection_resolves_current_paths(self) -> None:
        """The view selects the document's pin and resolves every stored path before crossing."""
        projection = self.view.revision_pin(
            1,
            "paper",
            None,
            lambda path: "paper/main.tex" if str(path).startswith("/old/") else None,
            self.head,
            [{"id": self.head}],
        )

        self.assertIsNotNone(projection)
        assert projection is not None
        self.assertEqual(projection.relative_path, "paper/main.tex")
        self.assertEqual(projection.changes, (("paper/main.tex", 10, 12),))
        self.assertIsNone(self.view.revision_pin(1, "other", None, lambda _path: None, self.head, []))

    def test_people_projection_contains_only_detached_actor_facts(self) -> None:
        """Collaboration cannot observe source paths or mutate nested pin attribution."""
        actors = self.view.people_records()[0]
        self.assertEqual(set(actors), {"author", "thread"})
        actors["author"]["name"] = "Changed"
        self.assertEqual(self.view.people_records()[0]["author"]["name"], "Alice")

    def test_importing_pin_read_view_does_not_load_http_adapters(self) -> None:
        """The read contract remains importable without initializing pin routes."""
        code = (
            "import sys; from limn.pins import PinReadView; "
            "print(sorted(n for n in sys.modules if n.startswith('limn.pins.') and (n.endswith('.http') or n.endswith('.routes'))))"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "[]"), result.stderr)
