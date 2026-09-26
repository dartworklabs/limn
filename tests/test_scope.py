"""limn.scope and limn.revisions on their own: which module may do what, and the refusal values of pin scoping.

The attribution rules themselves (blocks, hunks, the synthetic tree) are tested in test_v03.py, and every revision
route end to end through the handler in test_revisions.py and test_v03.py. Here: limn.scope stays pure (no file, process,
clock or HTTP import), neither module reads the server's globals or imports server.py or the HTTP layer, and a
refusal is a returned value of the ScopeRefusal set.

Run: uv run pytest -q tests/test_scope.py
"""
import ast
import subprocess
import sys
import typing
import unittest
from pathlib import Path

from limn import revisions, scope

PKG = Path(__file__).resolve().parent.parent / "src" / "limn"
PURE_IMPORTS = {"__future__", "re", "collections.abc", "dataclasses", "typing", "limn.mapping"}


def imports_of(path: Path) -> set:
    """Every module name a file imports (import x / from x import y)."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


class Boundaries(unittest.TestCase):
    """What each module may reach."""

    def test_scope_imports_only_pure_modules(self):
        """A file, subprocess or HTTP import in limn.scope would put an effect inside the decision (R1)."""
        self.assertLessEqual(imports_of(PKG / "scope.py"), PURE_IMPORTS)

    def test_neither_module_reads_server_globals(self):
        """The document and the instance's settings arrive as arguments (R5): no C., no cur_doc()."""
        for name in ("scope.py", "revisions.py", "documents.py"):
            with self.subTest(module=name):
                source = (PKG / name).read_text(encoding="utf-8")
                self.assertNotRegex(source, r"(?<![\w.])C\.[a-z_]")
                self.assertNotIn("cur_doc(", source)

    def test_no_current_document_anywhere(self):
        """The document is an argument (R5): server.py and the HTTP layer keep no thread-local "current document"."""
        for path in [PKG / "server.py"] + sorted((PKG / "web").glob("*.py")):
            with self.subTest(module=path.name):
                source = path.read_text(encoding="utf-8")
                for name in ("cur_doc(", "using_doc(", "threading.local("):
                    self.assertNotIn(name, source)

    def test_revisions_loads_without_server_or_the_http_layer(self):
        """limn.revisions answers with values; the HTTP layer imports it, never the other way round."""
        self.assertFalse({n for n in imports_of(PKG / "revisions.py") if n.startswith("limn.web") or n == "limn.server"})
        code = "import sys, limn.revisions; print(sorted(m for m in sys.modules if m.startswith('limn.web') or 'server' in m))"
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False,
                           cwd=str(PKG.parent))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "[]"), r.stderr)


class Refusals(unittest.TestCase):
    """A pin-scoping refusal is one frozen value per case, named together as ScopeRefusal."""

    def test_refusal_set_names_one_type_per_case(self):
        """Five cases, each a frozen dataclass without data (they differ in their answer, not their data)."""
        kinds = typing.get_args(scope.ScopeRefusal)
        self.assertEqual({k.__name__ for k in kinds},
                         {"PinNotInDoc", "ScopeUnreadable", "ScopeMismatch", "UnsafePath", "ScopeUnwritable"})
        for k in kinds:
            self.assertEqual(k(), k())
        self.assertIn(scope.PinNotInDoc, typing.get_args(revisions.DiffRefusal))

    def test_plan_refuses_with_values(self):
        """plan_scope_writes returns its refusal instead of raising: nothing to read, or a path that could escape."""
        self.assertEqual(scope.plan_scope_writes(None, [], "."), scope.ScopeUnreadable())
        f = scope.FileChange("../x.tex", "../x.tex", (b"a\n",), (b"b\n",), (scope.Block(0, 1, 0, 1),), False)
        self.assertEqual(scope.plan_scope_writes([f], [("../x.tex", "../x.tex", 0, 1, 0, 1)], "."), scope.UnsafePath())
        self.assertEqual(scope.plan_scope_writes([], [], "."), [])


if __name__ == "__main__":
    unittest.main()
