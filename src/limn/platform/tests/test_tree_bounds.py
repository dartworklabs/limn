"""The tree rule judged against bounds taken once is the tree rule (limn.platform.files).

tree_bounds resolves a tree's root and state folder once; part_within and file_within then judge a path without
resolving the two folders again. The judgments must be the ones tree_part and file_in_tree gave before the bounds
existed, for every path: these tests hold them to a reference that resolves all three paths on every call, over a
tree with every kind of place the rule refuses (a link out of the tree, a link into a dot folder, a state folder
inside the root, a link loop, a missing file).

Run: uv run pytest -q src/limn/platform/tests/test_tree_bounds.py
"""

import ast
import os
import tempfile
import unittest
from pathlib import Path

from hypothesis import given, settings, strategies as st

from limn.platform.files import (
    PATH_MAX_CHARS,
    BadPath,
    ManuscriptFile,
    NotAFile,
    OutsideTree,
    TreeBounds,
    file_in_tree,
    file_within,
    part_within,
    tree_bounds,
    tree_part,
)


def reference_part(p: Path, root: Path, state: Path) -> Path | None:
    """The tree rule as it stood before bounds: the root, the path and the state folder resolved on every call. The
    oracle for tree_part and part_within; it shares no code with them."""
    try:
        base = root.resolve()
        real = p.resolve()
        rel = real.relative_to(base)
        held = state.resolve()
    except (ValueError, OSError, RuntimeError):
        return None
    if any(part.startswith(".") for part in rel.parts):
        return None
    if held.is_relative_to(base) and real.is_relative_to(held):
        return None
    return rel


def reference_file(p: object, root: Path, state: Path) -> tuple[str, Path | None, Path | None]:
    """file_in_tree as it stood before bounds, as (outcome name, shown path, resolved path): the oracle for
    file_in_tree and file_within, built on reference_part alone."""
    if not isinstance(p, str) or not p or "\x00" in p or len(p) > PATH_MAX_CHARS:
        return "BadPath", None, None
    q = Path(p)
    if not q.is_absolute():
        q = root / q
    rel = reference_part(q, root, state)
    if rel is None:
        return "OutsideTree", None, None
    out = root / rel
    try:
        resolved, base, held = out.resolve(), root.resolve(), state.resolve()
        if reference_part(resolved, base, held) is None:
            return "OutsideTree", None, None
        if not resolved.is_file():
            return "NotAFile", None, None
    except (OSError, RuntimeError, ValueError):
        return "OutsideTree", None, None
    return "ManuscriptFile", out, resolved


def judged(found: ManuscriptFile | BadPath | OutsideTree | NotAFile) -> tuple[str, Path | None, Path | None]:
    """A file judgment in reference_file's form, so the two compare as values."""
    if isinstance(found, ManuscriptFile):
        return "ManuscriptFile", found.path, found._resolved
    return type(found).__name__, None, None


# Every name a path of the fixture tree is made of, plus two that exist nowhere and the parent step.
PARTS = (
    "main.tex",
    "sections",
    "intro.tex",
    "gone.tex",
    ".git",
    "config",
    ".env",
    "limn-state",
    "audit.jsonl",
    "to-git",
    "to-state",
    "to-outside",
    "to-sections",
    "to-secret",
    "to-main",
    "loop-a",
    "loop-b",
    "secret.tex",
    "nowhere",
    "..",
)


# A folder name no file system resolves: Path.resolve raises ValueError for an embedded NUL on every platform, where a
# link loop raises on some Python versions and resolves to itself on others.
UNRESOLVABLE = Path("/limn-test\x00unresolvable")


class Tree(unittest.TestCase):
    """One manuscript tree with every kind of place the rule judges, and a folder beside it that is outside."""

    @classmethod
    def setUpClass(cls):
        """Build the tree once: files, dot folders, a state folder inside the root, links in every direction."""
        cls.tmp = tempfile.TemporaryDirectory()
        top = Path(cls.tmp.name).resolve()
        cls.root = top / "ms"
        cls.outside = top / "outside"
        cls.state_inside = cls.root / "limn-state"
        cls.state_beside = top / "state"
        for folder in (cls.root / "sections", cls.root / ".git", cls.state_inside, cls.outside, cls.state_beside):
            folder.mkdir(parents=True)
        for file in (
            cls.root / "main.tex",
            cls.root / "sections" / "intro.tex",
            cls.root / ".git" / "config",
            cls.root / ".env",
            cls.state_inside / "audit.jsonl",
            cls.outside / "secret.tex",
        ):
            file.write_text("x\n", encoding="utf-8")
        os.symlink(cls.root / ".git", cls.root / "to-git")
        os.symlink(cls.state_inside, cls.root / "to-state")
        os.symlink(cls.outside, cls.root / "to-outside")
        os.symlink(cls.root / "sections", cls.root / "to-sections")
        os.symlink(cls.outside / "secret.tex", cls.root / "to-secret")
        os.symlink(cls.root / "main.tex", cls.root / "to-main")
        os.symlink(cls.root / "loop-b", cls.root / "loop-a")
        os.symlink(cls.root / "loop-a", cls.root / "loop-b")
        cls.linked_root = top / "ms-link"
        os.symlink(cls.root, cls.linked_root)

    @classmethod
    def tearDownClass(cls):
        """Remove the tree."""
        cls.tmp.cleanup()

    def trees(self):
        """The (root, state) pairs judged: the state folder inside the root and beside it, the root named through a
        link, a state folder that is the root itself, a root and a state folder that are a link loop, and a root and
        a state folder that cannot be resolved (UNRESOLVABLE)."""
        return (
            (self.root, self.state_inside),
            (self.root, self.state_beside),
            (self.linked_root, self.state_inside),
            (self.root, self.root),
            (self.root / "loop-a", self.state_beside),
            (self.root, self.root / "loop-a"),
            (UNRESOLVABLE, self.state_beside),
            (self.root, UNRESOLVABLE),
        )


class BoundsAgreeWithTheRule(Tree):
    """Against bounds or without, a path gets the judgment the rule gave before bounds existed."""

    @settings(max_examples=300, deadline=None)
    @given(
        parts=st.lists(st.sampled_from(PARTS), min_size=0, max_size=4),
        base=st.sampled_from(("root", "outside", "relative")),
        tree=st.integers(min_value=0, max_value=7),
    )
    def test_a_path_is_judged_as_before(self, parts, base, tree):
        """Any path made of the tree's names - under the root, under the folder beside it, or relative - is in or out
        of the tree, and a file or a refusal, exactly as the reference says, with bounds taken once and without."""
        root, state = self.trees()[tree]
        start = {"root": root, "outside": self.outside, "relative": Path()}[base]
        path = start.joinpath(*parts)
        bounds = tree_bounds(root, state)
        absolute = path if path.is_absolute() else root / path
        want_part = reference_part(absolute, root, state)
        self.assertEqual(tree_part(absolute, root, state), want_part)
        self.assertEqual(None if bounds is None else part_within(absolute, bounds), want_part)
        named = str(path)
        want_file = reference_file(named, root, state)
        self.assertEqual(judged(file_in_tree(named, root, state)), want_file)
        self.assertEqual(judged(file_within(named, bounds)), want_file)

    def test_the_refused_places_are_refused(self):
        """The places the rule exists for, by name: none of them is in the tree or a file of it, and the plain files
        are - so the property above is not comparing two functions that refuse everything."""
        root, state = self.root, self.state_inside
        bounds = tree_bounds(root, state)
        refused = (
            root / ".git" / "config",
            root / ".env",
            root / "to-git" / "config",
            root / "limn-state" / "audit.jsonl",
            root / "to-state" / "audit.jsonl",
            root / "to-outside" / "secret.tex",
            root / "to-secret",
            self.outside / "secret.tex",
            root / "sections" / ".." / ".." / "outside" / "secret.tex",
        )
        for path in refused:
            with self.subTest(path=str(path.relative_to(self.root.parent))):
                self.assertIsNone(part_within(path, bounds))
                self.assertIsInstance(file_within(str(path), bounds), OutsideTree)
        for path, rel in (
            (root / "main.tex", "main.tex"),
            (root / "to-main", "main.tex"),
            (root / "to-sections" / "intro.tex", "sections/intro.tex"),
        ):
            with self.subTest(path=path.name):
                self.assertEqual(part_within(path, bounds), Path(rel))
                found = file_within(str(path), bounds)
                self.assertIsInstance(found, ManuscriptFile)
                self.assertEqual(found.path, root / rel)
        self.assertIsInstance(file_within(str(root / "gone.tex"), bounds), NotAFile)

    def test_a_root_named_through_a_link_shows_its_files_under_that_name(self):
        """A judged file is shown as the root the run names joined with its part, not as the resolved root: the path
        an answer carries is the one the run registered, while the handle reads the resolved one."""
        for named in (self.linked_root / "main.tex", self.root / "main.tex", Path("main.tex")):
            with self.subTest(named=str(named)):
                found = file_within(str(named), tree_bounds(self.linked_root, self.state_inside))
                self.assertEqual(judged(found), reference_file(str(named), self.linked_root, self.state_inside))
                self.assertEqual(found.path, self.linked_root / "main.tex")
                self.assertEqual(found._resolved, self.root / "main.tex")

    def test_unusable_names_are_bad_paths_whatever_the_bounds(self):
        """A name that is no usable path is BadPath before the tree is looked at, with bounds or with none."""
        bounds = tree_bounds(self.root, self.state_inside)
        for name in (None, 7, "", "a\x00b", "x" * (PATH_MAX_CHARS + 1), ["main.tex"]):
            with self.subTest(name=repr(name)[:20]):
                self.assertIsInstance(file_within(name, bounds), BadPath)
                self.assertIsInstance(file_within(name, None), BadPath)

    def test_a_tree_that_cannot_be_resolved_has_no_bounds_and_holds_nothing(self):
        """A root or a state folder that cannot be resolved gives no bounds, and then every path is outside the tree -
        also when the root alone would have placed it."""
        for root, state in ((UNRESOLVABLE, self.state_beside), (self.root, UNRESOLVABLE)):
            with self.subTest(root=root.name, state=state.name):
                self.assertIsNone(reference_part(self.root / "main.tex", root, state))
                self.assertIsNone(tree_bounds(root, state))
                self.assertIsNone(tree_part(self.root / "main.tex", root, state))
                self.assertIsInstance(file_within(str(self.root / "main.tex"), None), OutsideTree)


class BoundsAreOneMoment(unittest.TestCase):
    """Bounds describe the tree when they were taken; what is read is judged again when it is read."""

    def setUp(self):
        """A root with one file and a folder beside it holding a file that is not the manuscript's."""
        self.tmp = tempfile.TemporaryDirectory()
        top = Path(self.tmp.name).resolve()
        self.root, self.outside, self.state = top / "ms", top / "outside", top / "state"
        for folder in (self.root, self.outside, self.state):
            folder.mkdir()
        (self.root / "main.tex").write_text("manuscript\n", encoding="utf-8")
        (self.outside / "secret.tex").write_text("secret\n", encoding="utf-8")

    def tearDown(self):
        """Remove the folders."""
        self.tmp.cleanup()

    def test_a_file_replaced_by_a_link_after_the_judgment_is_not_read(self):
        """A file judged inside the tree and then replaced by a link to a file outside it gives no line of that
        file: the handle reads through no-follow descriptors, whatever bounds it was judged against."""
        found = file_within(str(self.root / "main.tex"), tree_bounds(self.root, self.state))
        self.assertEqual(found.snapshot()[0], ["manuscript"])
        (self.root / "main.tex").unlink()
        os.symlink(self.outside / "secret.tex", self.root / "main.tex")
        self.assertEqual(found.snapshot()[0], [])
        self.assertIsNone(found.metadata())

    def test_a_path_is_resolved_at_each_judgment_even_against_old_bounds(self):
        """Only the two folders of bounds are remembered: a file that becomes a link out of the tree is refused by
        the next judgment against the same bounds."""
        bounds = tree_bounds(self.root, self.state)
        self.assertIsInstance(file_within(str(self.root / "main.tex"), bounds), ManuscriptFile)
        (self.root / "main.tex").unlink()
        os.symlink(self.outside / "secret.tex", self.root / "main.tex")
        self.assertIsInstance(file_within(str(self.root / "main.tex"), bounds), OutsideTree)
        self.assertIsNone(part_within(self.root / "main.tex", bounds))


class BoundsComeFromTheirFactory(unittest.TestCase):
    """Bounds are made by tree_bounds alone, so the folders in them are always ones it resolved."""

    def test_direct_construction_is_refused(self):
        """Calling the class raises: bounds naming folders nobody resolved cannot be made by mistake."""
        with self.assertRaises(TypeError):
            TreeBounds()

    def test_only_the_platform_module_constructs_bounds(self):
        """No module but limn.platform.files calls TreeBounds or builds one around its constructor: a source guard,
        as for ManuscriptFile, since Python cannot seal the class."""
        root = Path(__file__).resolve().parents[2]
        for path in root.rglob("*.py"):
            if path.name.startswith("test_") or path == root / "platform" / "files.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                self.assertFalse(
                    isinstance(node.func, ast.Name) and node.func.id == "TreeBounds",
                    "%s:%d: use tree_bounds" % (path, node.lineno),
                )
                if isinstance(node.func, ast.Attribute) and node.func.attr in {"__new__", "__setattr__"}:
                    self.assertFalse(
                        any(isinstance(arg, ast.Name) and arg.id == "TreeBounds" for arg in node.args),
                        "%s:%d: do not bypass tree_bounds" % (path, node.lineno),
                    )


if __name__ == "__main__":
    unittest.main()
