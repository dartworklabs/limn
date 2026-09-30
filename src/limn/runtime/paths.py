"""Fixed state-file locations shared by run configuration and persistence owners."""

from dataclasses import dataclass
from pathlib import Path

PEOPLE_FILE = "people.json"
EVENTS_FILE = "events.jsonl"
AUDIT_FILE = "audit.jsonl"


@dataclass(frozen=True)
class PinFiles:
    """Where the pin store keeps its files: fixed names under one state directory."""

    state: Path

    @property
    def pins_jsonl(self) -> Path:
        """The live pins."""
        return self.state / "pins.jsonl"

    @property
    def pins_md(self) -> Path:
        """The agents' work list, rendered from the live pins."""
        return self.state / "pins.md"

    @property
    def dropped(self) -> Path:
        """The Trash."""
        return self.state / "pins.dropped.jsonl"

    @property
    def seq(self) -> Path:
        """The last pin id handed out."""
        return self.state / "pins.seq"
