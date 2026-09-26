"""limn.audit - the audit log module on its own: its import boundary and the writer called with a state dir only.

The behaviour through the server and the CLI (clear, purge, tokens, members, mode 0600, append-only, symlink refusal,
concurrent appends) is covered in test_v031.py; this file checks that the module stands without the server.

Run: uv run pytest -q tests/test_audit.py
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path

from limn import audit

AUDIT_PY = Path(audit.__file__)


class ModuleBoundary(unittest.TestCase):
    """audit.py sits below the server and the CLI: the state directory and the clock come in as arguments."""

    def test_imports_only_the_standard_library_and_limn_files(self):
        """No server, HTTP or subprocess import; of limn only limn.files (store_lock)."""
        tree = ast.parse(AUDIT_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual({m for m in modules if m.startswith("limn")}, {"limn.files"})
        self.assertFalse({"http", "http.server", "urllib", "subprocess", "time"} & modules)

    def test_reads_no_server_global(self):
        """No run-argument object or server helper is named in the module."""
        tree = ast.parse(AUDIT_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"C", "now_str", "who", "LOCAL_ACTOR", "PIN_LOCK"})


class Append(unittest.TestCase):
    """append_audit(state, entry) with no server loaded."""

    def test_appends_one_line_per_entry_in_order(self):
        """Two entries are two lines, in the order written, each the entry's JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            first = audit.audit_entry("member_added", {"login": "u"}, "cli", {"login": "a", "role": "viewer"}, 1.0)
            second = audit.audit_entry("member_removed", {"login": "u"}, "cli", {"login": "a"}, 2.0)
            self.assertTrue(audit.append_audit(state, first))
            self.assertTrue(audit.append_audit(state, second))
            lines = (state / audit.AUDIT_FILE).read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(ln) for ln in lines], [first, second])
            self.assertEqual(first["by"], {"login": "u", "name": "u"})

    def test_os_actor_names_the_process_account(self):
        """by for the CLI is the uid's account name, used as both login and name."""
        actor = audit.os_actor()
        self.assertEqual(actor["login"], actor["name"])
        self.assertTrue(actor["login"])


if __name__ == "__main__":
    unittest.main()
