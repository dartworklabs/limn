"""The viewer's JavaScript read as tokens: exact function extraction, dead or doubled functions, statements swallowed by
comments, and the closed-set tables the viewer compares states against.

The parts under src/limn/viewer/js share one classic-script scope (docs/handbook/viewer.md §뷰어 규칙을 바꿀 때), so a
function nothing calls, a function declared twice, or a statement pasted after a `//` comment all parse and silently do
the wrong thing. tests/support/helpers_js.py tokenizes the parts (strings, template literals, regexes, comments), which is what
makes these checks exact. The closed sets (core.js: PIN_STATE, BUILD_STATE, ...) carry values that come from the API,
so each is compared with the server's own Literal, tuple or producer (docs/handbook/viewer.md §닫힌 값 표).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_source.py
"""

import ast
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import get_args

from limn.builds import artifacts as build, figure_map
from limn.collaboration import events
from limn.pins import model
from limn.pins.editing import values as edit
from limn.pins.listing.projection import pin_state
from limn.pins.location import mapping, position
from limn.revisions import scope
from limn.runtime import documents
from limn.security import access
from limn.sync import rules as pull
from limn.viewer import assemble

import helpers_js
from helpers import PKG, VIEWER, VIEWER_CLOSED_SETS, extract_js_fn, run_node

PARTS = assemble.viewer_manifest(VIEWER)["__APP_JS__"]
CORPUS = Path(__file__).resolve().parents[4] / "tests" / "data" / "pin_records.jsonl"

# Top-level functions no other code of the page names. Each needs a reason; anything else unreferenced is dead code or
# a call lost to a paste accident.
ENTRY_POINTS = {
    "claimLabel": "the claim badge's text alone; nothing in the page calls it, FrontendClaimEta and FrontendClaimUI pin it",
}

# A '//' comment whose text holds code: a minified assignment from a call (`a.b=f(`) or a call closed with ';' at its
# end (`f(x);`). Prose in comments spaces '=' and '(' (`T (a release ...);`), so a hit is code that never runs.
CODE_IN_COMMENT = re.compile(r"[\w$\])]=[\w$.]+\(|[\w$\]]\((?:[^()]|\([^()]*\))*\)\s*;\s*$")


def part_sources() -> dict[str, str]:
    """Every JS part of the page, by manifest path, in page order."""
    return {name: (VIEWER / name).read_text(encoding="utf-8") for name in PARTS}


def head_scripts() -> list[str]:
    """index.html's inline scripts other than the main one (the language and theme bootstraps in <head>)."""
    return helpers_js.inline_scripts((VIEWER / "index.html").read_text(encoding="utf-8"))[:-1]


def swallowed(src: str) -> list[tuple[int, str]]:
    """(line, comment) for every `//` comment of script src whose text holds a statement (CODE_IN_COMMENT)."""
    return [
        (src.count("\n", 0, t.start) + 1, t.text)
        for t in helpers_js.tokenize(src)
        if t.kind == "line-comment" and CODE_IN_COMMENT.search(t.text[2:])
    ]


def node_or_skip(case: unittest.TestCase) -> str:
    """node's path; skips without node unless LIMN_TEST_REQUIRE_NODE=1 (CI), where a missing node fails."""
    node = shutil.which("node")
    if node:
        return node
    if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
        case.fail("node is required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
    case.skipTest("node is not installed")


class Tokenizer(unittest.TestCase):
    """helpers_js.tokenize() splits a script exactly: nothing a literal or comment holds is read as code."""

    def kinds(self, src: str) -> list[tuple[str, str]]:
        """The (kind, text) of src's code and comment tokens, spaces dropped."""
        return [(t.kind, t.text) for t in helpers_js.tokenize(src) if t.kind != "space"]

    def test_tokens_join_back_to_the_source(self):
        """Every part's tokens, joined, are the part byte for byte - no text is dropped or read twice."""
        for name, src in part_sources().items():
            self.assertEqual("".join(t.text for t in helpers_js.tokenize(src)), src, name)

    def test_braces_quotes_and_slashes_inside_literals_and_comments_are_not_code(self):
        """A brace in a string, a '//' in a string or regex, a quote in a comment, a '/' inside a regex class and a
        template's own '${...}' each stay inside their token."""
        src = "a='{//';b=/[/}]\\//g;c=`x${ {k:'}'}.k }y`;/* ' { */d=e/f/g;// }"
        self.assertEqual(
            self.kinds(src),
            [
                ("ident", "a"), ("punct", "="), ("string", "'{//'"), ("punct", ";"),
                ("ident", "b"), ("punct", "="), ("regex", "/[/}]\\//g"), ("punct", ";"),
                ("ident", "c"), ("punct", "="), ("template", "`x${"), ("punct", "{"), ("ident", "k"), ("punct", ":"),
                ("string", "'}'"), ("punct", "}"), ("punct", "."), ("ident", "k"), ("template", "}y`"), ("punct", ";"),
                ("comment", "/* ' { */"),
                ("ident", "d"), ("punct", "="), ("ident", "e"), ("punct", "/"), ("ident", "f"), ("punct", "/"),
                ("ident", "g"), ("punct", ";"), ("line-comment", "// }"),
            ],
        )  # fmt: skip

    def test_a_slash_after_a_keyword_or_operator_starts_a_regex(self):
        """After `return`, `typeof`, '(' or '=' a '/' opens a regex; after a value or ')' it divides."""
        self.assertIn(("regex", "/x/"), self.kinds("return /x/.test(s)"))
        self.assertIn(("regex", "/}/"), self.kinds("f(/}/)"))
        self.assertNotIn("regex", [k for k, _ in self.kinds("(a)/2/b")])

    def test_an_unterminated_literal_is_an_error(self):
        """A string, template, regex or comment left open raises instead of swallowing the rest of the script."""
        for src in ("a='x", "a=`x${b}", "a=/x", "/* x"):
            with self.subTest(src), self.assertRaises(helpers_js.TokenizeError):
                helpers_js.tokenize(src)

    def test_every_part_is_whole_statements(self):
        """Each part closes every bracket it opens: a part cut in the middle of a function or literal would make the
        next part's code mean something else."""
        for name, src in part_sources().items():
            depth = 0
            for t in helpers_js.code(helpers_js.tokenize(src)):
                opens = t.text in ("(", "[", "{") if t.kind == "punct" else t.text.endswith("${")
                closes = t.text in (")", "]", "}") if t.kind == "punct" else t.text.startswith("}")
                depth += (t.kind in ("punct", "template")) * (int(opens) - int(closes))
                self.assertGreaterEqual(depth, 0, (name, t))
            self.assertEqual(depth, 0, name)


class FunctionExtraction(unittest.TestCase):
    """extract_js_fn() returns a top-level declaration exactly as served, whatever its literals hold."""

    def test_only_top_level_declarations_are_found(self):
        """A nested function and a named function expression are not top-level declarations; `async function` keeps
        its `async`, and a declaration after a call without ';' still counts."""
        src = "function a(){function inner(){}}\nconst e=function b(){};\nf()\nasync function c(){await 1}"
        found = helpers_js.top_level_functions(src)
        self.assertEqual([f.name for f in found], ["a", "c"])
        self.assertEqual(src[found[1].start : found[1].end], "async function c(){await 1}")

    def test_a_missing_or_doubled_declaration_raises(self):
        """A name no script declares at the top level is a LookupError (a nested one does not count); a name declared
        twice is a ValueError - the browser would silently keep the later one."""
        page = "<script>function a(){function b(){}}</script><script>function a(){}</script>"
        with self.assertRaises(LookupError):
            helpers_js.function_source(page, "b")
        with self.assertRaises(ValueError):
            helpers_js.function_source(page, "a")

    def test_a_brace_in_a_string_does_not_cut_the_function_short(self):
        """card() builds markup with '{' and '}' inside strings, regexes and template substitutions; the extracted text
        still ends at the function's own closing brace (the last character) and holds the whole body."""
        body = extract_js_fn("card")
        self.assertTrue(body.endswith("}"))
        self.assertIn("function card(p){", body)
        self.assertIn("${head}${body}</div>`;\n}", body)

    def test_the_tables_a_function_reads_come_with_it(self):
        """A pulled function that reads a closed set gets it as a `var` before its text, so it runs in a bare harness;
        one that reads none gets nothing."""
        self.assertTrue(extract_js_fn("pinState").startswith("var PIN_STATE=Object.freeze("))
        self.assertTrue(extract_js_fn("josa").startswith("function josa("))

    def test_every_top_level_function_extracts_to_valid_javascript(self):
        """Each of the page's top-level functions, pulled with its tables, compiles on its own under node - so no
        extraction is cut short or runs into the next statement."""
        node = node_or_skip(self)
        names = [f.name for src in part_sources().values() for f in helpers_js.top_level_functions(src)]
        script = "const vm=require('vm'),bad=[];for(const [n,s] of %s){try{new vm.Script(s);}catch(e){bad.push(n+': '+e.message);}}console.log(JSON.stringify(bad));"
        pairs = json.dumps([[n, extract_js_fn(n)] for n in names], ensure_ascii=False)
        r = subprocess.run([node, "-"], input=script % pairs, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [])
        self.assertGreater(len(names), 300)


class DeadAndDoubledFunctions(unittest.TestCase):
    """Every top-level function of the page is declared once and named by some other code, or is a listed entry point."""

    def declarations(self) -> list[tuple[str, helpers_js.FunctionDecl]]:
        """(part, declaration) for every top-level function of every JS part."""
        return [(name, f) for name, src in part_sources().items() for f in helpers_js.top_level_functions(src)]

    def unreferenced(self, sources: dict[str, str]) -> list[str]:
        """The top-level functions of sources no code names outside its own body (head scripts count as code)."""
        uses = {name: helpers_js.name_uses(src) for name, src in sources.items()}
        heads = set().union(*(helpers_js.references(s) for s in head_scripts()))
        out = []
        for part, src in sources.items():
            for f in helpers_js.top_level_functions(src):
                outside = (t for name, ts in uses.items() for t in ts if name != part or not f.start <= t.start < f.end)
                if f.name not in heads and not any(t.text == f.name for t in outside):
                    out.append(f.name)
        return out

    def test_no_function_is_declared_twice(self):
        """Two parts declaring the same name would silently keep the later one."""
        names = [f.name for _, f in self.declarations()]
        self.assertEqual(sorted({n for n in names if names.count(n) > 1}), [])

    def test_every_function_is_called_or_is_an_entry_point(self):
        """A function nothing names is dead - or its only call was swallowed by a comment, as mentionBadSettled's was
        (1486de0). The listed entry points are exactly the unreferenced ones, so the list cannot go stale either."""
        self.assertEqual(sorted(self.unreferenced(part_sources())), sorted(ENTRY_POINTS))

    def test_a_call_lost_to_a_comment_is_caught(self):
        """The mentions.js accident planted again: with the call turned into comment text, mentionBadSettled is
        reported as unreferenced."""
        sources = part_sources()
        src = sources["js/mentions.js"]
        call = re.search(r"\n\s*(r\.bad=mentionBadSettled\([^;]*\);)", src)
        self.assertIsNotNone(call)
        sources["js/mentions.js"] = src.replace(call.group(0), " // the same hints " + call.group(1), 1)
        self.assertIn("mentionBadSettled", self.unreferenced(sources))


class CommentsHoldNoCode(unittest.TestCase):
    """A `//` comment never ends in a statement: one pasted after a trailing comment parses and never runs."""

    def test_no_line_comment_swallows_a_statement(self):
        """Every `//` comment token of the JS parts, the served service worker and the head scripts is free of code.
        Found by tokens, so '//' inside a string ('https://') or regex is no comment, and a comment right after code
        with no space before it is still one."""
        scripts = dict(part_sources())
        scripts["sw.js"] = (VIEWER / "sw.js").read_text(encoding="utf-8")
        scripts.update(("index.html head %d" % i, s) for i, s in enumerate(head_scripts()))
        hits = ["%s:%d: %s" % (name, n, c) for name, src in scripts.items() for n, c in swallowed(src)]
        self.assertEqual(hits, [])

    def test_the_check_catches_the_mentions_accident_and_passes_urls(self):
        """The 1486de0 shape is a hit, also glued to code; a URL in a string and prose with spaced calls are not."""
        self.assertEqual(len(swallowed("f(); // the same hints r.bad=mentionBadSettled(ta,q);\n")), 1)
        self.assertEqual(len(swallowed("f();//x g(a);\n")), 1)
        self.assertEqual(swallowed("u='https://a.b/c(d);';\n// see T (a release note);\n"), [])


def build_states() -> set[str]:
    """Every value GET /api/build's `state` can hold: limn.builds.artifacts's closed set of build states, which includes the idle
    state the server starts each document with."""
    return set(build.BUILD_STATES)


def written_states(path: Path) -> set[str]:
    """The string values module path writes to a "state" key - a dict entry, a `state=` keyword or `x["state"] = ...`,
    both branches of a conditional value included."""

    def values(node: ast.expr) -> set[str]:
        """The strings an assigned value can be: a constant, or either branch of a conditional."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.IfExp):
            return values(node.body) | values(node.orelse)
        return set()

    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "state":
                    out |= values(v)
        elif (
            isinstance(node, ast.keyword)
            and node.arg == "state"
            or isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == "state"
                for t in node.targets
            )
        ):
            out |= values(node.value)
    return out


def sync_states() -> set[str]:
    """Every value GET /api/meta's `sync.state` can hold: the watch's pull outcomes (pull.SyncState), the statuses the
    pure producers in limn.sync.rules give, and the one the watch writes itself when it starts builds (limn/gitsync.py)."""
    produced = [pull.initial_status(), pull.disabled(), pull.deferred(""), pull.unexpected("")]
    produced += [pull.settled("h", [pull.Built("h", False)]), pull.settled("h", [pull.Built("g", True)])]
    return set(get_args(pull.SyncState)) | {s["state"] for s in produced} | written_states(PKG / "sync" / "run.py")


def pull_states() -> set[str]:
    """Every value a build's `pull.state` can hold: pull.pull_record() of each pull outcome type."""
    outcomes = [
        pull.Pulled("a", "b"),
        pull.UpToDate("a"),
        pull.PullSkipped("dirty", "a"),
        pull.PullFailed("fetch_failed", "a"),
    ]
    return {pull.pull_record(o)["state"] for o in outcomes}


# Each closed set that carries API values, with the server's values it must equal exactly.
SERVER_SETS = {
    "PIN_STATE": lambda: set(get_args(model.StateName)),
    "BUILD_STATE": build_states,
    "PULL_STATE": pull_states,
    "SYNC_STATE": sync_states,
    "REVISION_STATE": lambda: written_states(PKG / "revisions/jobs.py"),
    "SCOPE_MODE": lambda: set(get_args(scope.ScopeMode)),
    "SCOPE_SOURCE": lambda: set(get_args(scope.ScopeSource)),
    "THREAD_EV": lambda: set(get_args(model.ThreadEv)),
    "RANGE_REL": lambda: set(get_args(position.RangeRel)) | {"equal"},  # selection_rel adds 'equal' to RangeRel
    "KIND_REQ": lambda: set(get_args(model.KindReq)),
    "ROLE": lambda: set(access.ROLES),
    "EVENT_TYPE": lambda: set(get_args(events.EventType)),
    "VIA": lambda: set(get_args(mapping.Via)),
    "DOC_KIND": lambda: set(get_args(documents.DocKind)),
    "EL_SYNC": lambda: set(get_args(figure_map.ElSync)),
    "LOCAL_LOGIN": lambda: {access.LOCAL_LOGIN},
    "ASSIGNEE_AGENT": lambda: {edit.ASSIGNEE_AGENT},
}
# The viewer's own closed sets: no server counterpart.
VIEWER_SETS = {
    "LAYOUT_MODE",
    "LAYOUT_BAND",
    "BAND_STEP",
    "CARD_DOT",
    "DIFF_FORMAT",
    "OVERLAY_SIDE",
    "VIEW_MODE",
    "UI_LANG",
    "NOTIFY_STATE",
    "STATUS_KIND",
}


def set_values(value: helpers_js.ClosedSet) -> list[str]:
    """A closed set's values: the scalar's one, or the table's in order."""
    return [value] if isinstance(value, str) else list(value.values())


def unknown_members(sources: dict[str, str]) -> list[str]:
    """'part: TABLE.MEMBER' for every member of a closed-set table that sources name but the table lacks."""
    tables = {n: v for n, v in VIEWER_CLOSED_SETS.items() if isinstance(v, dict)}
    out = []
    for part, src in sources.items():
        toks = helpers_js.code(helpers_js.tokenize(src))
        for j in range(len(toks) - 2):
            t, dot, member = toks[j : j + 3]
            named = t.text in tables and dot.text == "." and (j == 0 or toks[j - 1].text not in (".", "?."))
            if named and member.text not in tables[t.text]:
                out.append("%s: %s.%s" % (part, t.text, member.text))
    return out


def raw_state_reads(sources: dict[str, str]) -> list[str]:
    """Every place sources read a pin's state around pinState(): a `.done` / `.review` property read outside pinState's
    own body, and a pinState(...) call compared with a string literal. SEC and SEC_SEEN (the list sections, keyed by
    state name) and T (the tooltip texts) have such properties too and are not pins."""
    out = []
    for part, src in sources.items():
        own = next((f for f in helpers_js.top_level_functions(src) if f.name == "pinState"), None)
        toks = helpers_js.code(helpers_js.tokenize(src))
        for j, t in enumerate(toks[1:], 1):
            inside = own is not None and own.start <= t.start < own.end
            flag = t.text in ("done", "review") and toks[j - 1].text in (".", "?.") and not inside
            if flag and toks[j - 2].text not in ("SEC", "SEC_SEEN", "T"):
                out.append("%s: %s.%s" % (part, toks[j - 2].text, t.text))
            if t.text == "pinState" and toks[j - 1].text not in (".", "function"):
                close = helpers_js.matching_bracket(toks, j + 1)
                after = toks[close + 1 : close + 3]
                if len(after) == 2 and after[0].text in ("===", "!==", "==", "!=") and after[1].kind == "string":
                    out.append("%s: pinState(...)%s%s" % (part, after[0].text, after[1].text))
    return out


class ClosedSets(unittest.TestCase):
    """The frozen tables in core.js hold every value the viewer compares a state, status or mode against."""

    def test_core_declares_exactly_the_known_sets(self):
        """A new table is classed here as the server's (and compared) or the viewer's own; none goes unchecked."""
        self.assertEqual(set(VIEWER_CLOSED_SETS), set(SERVER_SETS) | VIEWER_SETS)

    def test_api_tables_equal_the_server_values(self):
        """Each table of API values has exactly the server's strings: a value the server never sends would be dead,
        one it sends that the table lacks could never be compared by name."""
        for name, server in SERVER_SETS.items():
            with self.subTest(name):
                self.assertEqual(set(set_values(VIEWER_CLOSED_SETS[name])), server())

    def test_each_table_is_a_set(self):
        """No two members of a table share a value, so a comparison by member names one case."""
        for name, value in VIEWER_CLOSED_SETS.items():
            values = set_values(value)
            self.assertEqual(len(values), len(set(values)), name)

    def test_every_member_used_exists(self):
        """`PIN_STATE.REVEIW` would be undefined and compare unequal to everything without an error; every
        TABLE.MEMBER the parts name is a member of that table, and a planted misspelling is caught."""
        self.assertEqual(unknown_members(part_sources()), [])
        planted = dict(part_sources())
        planted["js/list.js"] += "const X=PIN_STATE.REVEIW;\n"
        self.assertEqual(unknown_members(planted), ["js/list.js: PIN_STATE.REVEIW"])

    def test_markup_values_are_members(self):
        """The changes view's tabs, the view switch and the composer's kind buttons send their data-* value into code
        that compares it with DIFF_FORMAT, VIEW_MODE and KIND_REQ."""
        page = (VIEWER / "index.html").read_text(encoding="utf-8")
        for attr, name in (("data-format", "DIFF_FORMAT"), ("data-mode", "VIEW_MODE"), ("data-kind", "KIND_REQ")):
            with self.subTest(attr):
                found = set(re.findall(r'%s="([^"]*)"' % attr, page))
                self.assertTrue(found)
                self.assertLessEqual(found, set(set_values(VIEWER_CLOSED_SETS[name])))

    def test_a_pin_state_is_read_only_through_pin_state(self):
        """The viewer never reads a pin's raw done/review flags or compares pinState() with a string: pinState() is the
        one reading, PIN_STATE the one spelling. Both kinds of slip, planted, are caught."""
        self.assertEqual(raw_state_reads(part_sources()), [])
        planted = dict(part_sources())
        planted["js/list.js"] += "const a=PINS.filter(p=>!p.done),b=pinState(PINS[0])==='review';\n"
        self.assertEqual(raw_state_reads(planted), ["js/list.js: p.done", "js/list.js: pinState(...)==='review'"])

    def test_band_mode_maps_every_band_and_only_the_bands_to_a_layout_mode(self):
        """BAND_MODE (core.js) gives LAYOUT for the band in use: its keys are exactly LAYOUT_BAND's members and its values
        LAYOUT_MODE's, so a band added to one table without the other fails here, not on a device."""
        node_or_skip(self)
        src = (VIEWER / "js" / "core.js").read_text(encoding="utf-8")
        line = re.search(r"^const BAND_MODE=.*;$", src, re.M).group(0)
        js = (
            helpers_js.closed_set_prelude(VIEWER_CLOSED_SETS, line)
            + line
            + (
                "\nconsole.log(JSON.stringify([Object.keys(BAND_MODE).sort(),[...new Set(Object.values(BAND_MODE))].sort(),"
                "Object.isFrozen(BAND_MODE)]));"
            )
        )
        keys, modes, frozen = json.loads(run_node(js))
        self.assertEqual(keys, sorted(VIEWER_CLOSED_SETS["LAYOUT_BAND"].values()))
        self.assertEqual(modes, sorted(VIEWER_CLOSED_SETS["LAYOUT_MODE"].values()))
        self.assertTrue(frozen)

    def test_pin_state_agrees_with_the_server_for_every_record_shape(self):
        """pinState() reads the API's `state` when it is there, and otherwise derives the same state the server does
        (pins.view.pin_state) from the stored flags - for every record shape in tests/data/pin_records.jsonl."""
        node_or_skip(self)
        records = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines()]
        viewed = [dict(r, state=pin_state(r)) for r in records]
        js = (
            extract_js_fn("pinState")
            + "\nconst R=%s,V=%s;console.log(JSON.stringify([R.map(pinState),V.map(pinState)]));"
        )
        raw, api = json.loads(run_node(js % (json.dumps(records), json.dumps(viewed))))
        self.assertEqual(raw, [pin_state(r) for r in records])
        self.assertEqual(api, [pin_state(r) for r in records])
        self.assertEqual(set(raw), set(get_args(model.StateName)))


if __name__ == "__main__":
    unittest.main()
