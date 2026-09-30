"""Release tripwire: P1b's figure pins need the P1c viewer, so a release cut from main before P1c must fail loudly.

P1c deletes this file together with the `Release blocker` line at the top of CHANGELOG.md `## Unreleased`.
"""

import limn


def test_the_version_is_not_bumped_before_the_p1c_viewer_lands() -> None:
    """Condition: P1b (server side of figure pins) is on main and the P1c viewer is not. Expectation: the package
    version is still 0.3.8; a release bump fails here, so nobody ships a server whose figure documents report
    view_only false to a viewer that still treats them as LaTeX."""
    assert limn.__version__ == "0.3.8", (
        "P1b figure pins need the P1c viewer; merge P1c (which deletes this test) before releasing."
    )
