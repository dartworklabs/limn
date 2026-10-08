"""HTTP build permissions preserve the documented role matrix and reject effects before execution.

Real files, Git history, document locks and build workers exercise the authorization boundary.
TeX-marked cases additionally require a published PDF from the real compiler and sandbox.
"""

import copy
import shutil
import subprocess
import time

from helpers import needs_tex, ps, set_config
from helpers_access import ALICE, BOB, CAROL, TS_HOST, AccessBase, token_create, token_revoke


class BuildRoleMatrix(AccessBase):
    """Every role reaches only its permitted rebuild and comparison effects over HTTP."""

    def setUp(self):
        """Use a real two-commit manuscript, persisted roles and a revocable agent token."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        set_config(dpi=36, timeout=30)
        self.main.write_text(
            "\\documentclass{article}\n\\begin{document}\nOld words.\n\\end{document}\n", encoding="utf-8"
        )
        for args in (
            ("init", "--quiet"),
            ("config", "user.email", "alice@example.com"),
            ("config", "user.name", "Alice"),
            ("add", "main.tex"),
            ("commit", "--quiet", "-m", "Initial manuscript"),
        ):
            self.git(*args)
        self.main.write_text(self.main.read_text().replace("Old words.", "New words."), encoding="utf-8")
        self.git("commit", "--quiet", "-am", "Revise manuscript")
        self.commit = self.git("rev-parse", "HEAD").strip()
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice", "role": "owner"},
                {"login": "bob@example.com", "name": "Bob", "role": "editor"},
                {"login": "carol@example.com", "name": "Carol", "role": "viewer"},
            ]
        )
        self.token_entry, self.token = token_create(ps.APP.C.state, "build-tests")

    def git(self, *args):
        """Run checked Git commands in the isolated manuscript and return their output."""
        return subprocess.run(
            ["git", *args], cwd=self.src, capture_output=True, text=True, check=True, timeout=10
        ).stdout

    def as_role(self, role):
        """Authenticate human roles through Tailnet headers and the agent through its token."""
        if role == "agent":
            return {"token": self.token, "headers": {"Host": TS_HOST}}
        return {"headers": dict({"owner": ALICE, "editor": BOB, "viewer": CAROL}[role], Host=TS_HOST)}

    def effect_snapshot(self):
        """Capture manuscript and state bytes, paths and publication state before a denied request."""
        return (
            {p.relative_to(self.src).as_posix(): p.read_bytes() for p in self.src.rglob("*") if p.is_file()},
            {
                p.relative_to(ps.APP.C.state).as_posix(): p.read_bytes() if p.is_file() else None
                for p in ps.APP.C.state.rglob("*")
            },
            copy.deepcopy(ps.APP.docs[0].bstate),
        )

    def assert_denied_without_effect(self, kwargs, status, reason, rebuild_only=False):
        """A denied build leaves all source/state bytes, directory entries and build status unchanged."""
        requests = [("/api/rebuild?force=1", None), ("/api/rebuild?async=1&force=1", None)]
        if not rebuild_only:
            requests.append(("/api/revision-build", {"commit": self.commit}))
        for path, body in requests:
            with self.subTest(path=path, reason=reason):
                before = self.effect_snapshot()
                code, answer = self.call("POST", path, body, **kwargs)
                self.assertEqual((code, answer.get("reason")), (status, reason), answer)
                self.assertEqual(self.effect_snapshot(), before)

    def test_rebuild_role_matrix_checks_permission_before_document_busy(self):
        """Owner/editor/agent reach the busy build gate; viewer is refused before either rebuild can act."""
        doc = ps.APP.docs[0]
        with doc.lock:
            for role in ("owner", "editor", "agent"):
                for path in ("/api/rebuild", "/api/rebuild?async=1"):
                    with self.subTest(role=role, path=path):
                        before = copy.deepcopy(doc.bstate)
                        code, answer = self.call("POST", path, **self.as_role(role))
                        self.assertEqual(code, 409, answer)
                        self.assertTrue(answer["busy"])
                        self.assertEqual(doc.bstate, before)
            self.assert_denied_without_effect(self.as_role("viewer"), 403, "viewer_only", rebuild_only=True)

    def test_unidentified_and_revoked_build_requests_have_no_effect(self):
        """No identity or a revoked token permits neither rebuild nor a comparison job."""
        set_config(agent_loopback=False)
        self.assert_denied_without_effect({}, 401, "loopback_agent_off")
        self.assert_denied_without_effect({"token": "invalid-token"}, 401, "bad_token")
        token_revoke(ps.APP.C.state, self.token_entry["id"])
        self.assert_denied_without_effect(self.as_role("agent"), 401, "bad_token")

    def test_allowlist_refuses_both_build_operations_without_effect(self):
        """A valid human identity outside the allowlist cannot start either build operation."""
        set_config(allow=frozenset({"alice@example.com"}))
        self.assert_denied_without_effect(self.as_role("editor"), 403, "not_allowed")

    def test_unknown_role_and_unreadable_roles_cannot_rebuild(self):
        """Unknown roles and corrupt role storage fail closed before synchronous or asynchronous rebuilds."""
        self.set_people([{"login": "bob@example.com", "role": "unknown"}])
        self.assert_denied_without_effect(self.as_role("editor"), 403, "viewer_only", rebuild_only=True)
        ps.APP.C.people_file.write_bytes(b"broken JSON")
        self.assert_denied_without_effect(self.as_role("owner"), 403, "viewer_only", rebuild_only=True)

    def wait_comparison(self):
        """Await a real worker's terminal HTTP status; timeout indicates a stuck job, not a retry."""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            code, answer = self.call("GET", "/api/revision-build?commit=" + self.commit)
            self.assertEqual(code, 200, answer)
            if answer["state"] != "running":
                return answer
            time.sleep(0.02)
        self.fail("comparison worker did not finish")

    def test_every_role_can_start_a_real_comparison_worker(self):
        """Viewer/agent/editor/owner start comparisons; their jobs preserve the current manuscript and build."""
        for index, role in enumerate(("owner", "editor", "viewer", "agent"), start=1):
            with self.subTest(role=role):
                self.main.write_text(
                    self.main.read_text().replace("New words.", "New words. More words."), encoding="utf-8"
                )
                self.git("commit", "--quiet", "-am", "Add comparison words")
                self.commit = self.git("rev-parse", "HEAD").strip()
                source = self.main.read_bytes()
                before = copy.deepcopy(ps.APP.docs[0].bstate)
                code, answer = self.call("POST", "/api/revision-build", {"commit": self.commit}, **self.as_role(role))
                self.assertEqual((code, answer.get("state")), (202, "running"), answer)
                finished = self.wait_comparison()
                self.assertIn(finished["state"], ("ready", "error"), finished)
                if finished["state"] == "error":
                    self.assertEqual(finished["reason"], "tool_unavailable", finished)
                statuses = list(ps.APP.C.state.rglob("status.json"))
                self.assertEqual(len(statuses), index, statuses)
                self.assertEqual(self.main.read_bytes(), source)
                self.assertEqual(ps.APP.docs[0].bstate, before)

    @needs_tex("latexmk", "pdflatex", "pdftoppm", "pdfinfo")
    def test_allowed_rebuild_roles_publish_real_pdf(self):
        """Owner/editor/agent forced rebuilds publish real PDFs and advance the build sequence."""
        for role in ("owner", "editor", "agent"):
            with self.subTest(role=role):
                previous = ps.APP.docs[0].bstate["seq"]
                code, answer = self.call("POST", "/api/rebuild?force=1", **self.as_role(role))
                self.assertEqual(code, 200, answer)
                self.assertTrue(answer["ok"], answer)
                code, pdf = self.call("GET", "/pdf", **self.as_role(role))
                self.assertEqual(code, 200)
                self.assertTrue(pdf.startswith("%PDF-"))
                self.assertGreater(ps.APP.docs[0].bstate["seq"], previous)

    @needs_tex("bwrap", "latexdiff", "latexmk", "pdflatex")
    def test_viewer_comparison_publishes_real_sandbox_pdf(self):
        """A viewer's permitted comparison completes in the real sandbox and serves its PDF."""
        code, answer = self.call("POST", "/api/revision-build", {"commit": self.commit}, **self.as_role("viewer"))
        self.assertEqual(code, 202, answer)
        finished = self.wait_comparison()
        self.assertEqual(finished["state"], "ready", finished)
        code, pdf = self.call("GET", "/api/revision-pdf?commit=" + self.commit, **self.as_role("viewer"))
        self.assertEqual(code, 200)
        self.assertTrue(pdf.startswith("%PDF-"))
