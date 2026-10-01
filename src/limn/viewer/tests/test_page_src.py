"""The viewer asks for page images at URLs that name their build (docs/handbook/api.md §화면·PDF·정적 파일).

Run: uv run pytest -q src/limn/viewer/tests/test_page_src.py
"""

import json
import os
import shutil
import unittest

from helpers import extract_js_fn, run_node


class PageSrc(unittest.TestCase):
    """pageSrc under node with the document query helper stood in."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def test_a_page_url_names_the_build_on_screen_and_falls_back_without_one(self):
        """With META.pages_build the URL is /pages/<build>/<page> (with ?doc= from dq); without one it is the old
        /pages/<page>?v=<built_at>."""
        js = "\n".join(
            [
                "const dq=u=>u+(u.includes('?')?'&':'?')+'doc=b'; let META;",
                extract_js_fn("pageSrc"),
                "META={pages_build:'pages-20261001120000',built_at:'2026-10-01T12:00:00+09:00'};"
                "const a=pageSrc({name:'page-01.png'});"
                "META={pages_build:'',built_at:'2026-10-01T12:00:00+09:00'};"
                "const b=pageSrc({name:'page-01.png'});"
                "console.log(JSON.stringify([a,b]));",
            ]
        )
        self.assertEqual(
            json.loads(run_node(js)),
            [
                "/pages/pages-20261001120000/page-01.png?doc=b",
                "/pages/page-01.png?v=2026-10-01T12%3A00%3A00%2B09%3A00&doc=b",
            ],
        )


if __name__ == "__main__":
    unittest.main()
