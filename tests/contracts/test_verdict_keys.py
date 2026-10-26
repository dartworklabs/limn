"""The two readers of a verdict key agree: the word file's (limn.documents.verdicts.KEY_RE) and the stored pin's
(limn.pins.verdict.VERDICT_KEY_RE).

The documents capability decides which keys a word file may declare; the pins capability decides which stored value
it reads back as a pin's verdict. Neither imports the other, so the one rule (1-16 of [\\w-]) is written in both,
and this check across the two holds them together: a key a file may declare is always read back from a pin, and a
value read back from a pin is always one a file may declare.

Run: uv run pytest -q tests/contracts/test_verdict_keys.py
"""

import unittest

from hypothesis import given, strategies as st

from limn.documents.verdicts import KEY_RE
from limn.pins.verdict import VERDICT_KEY_RE, is_verdict_key


class KeyRulesAgree(unittest.TestCase):
    """KEY_RE and VERDICT_KEY_RE accept the same strings."""

    @given(st.text(max_size=20) | st.from_regex(r"[\w-]{1,18}", fullmatch=True))
    def test_a_string_is_a_key_for_both_or_for_neither(self, v):
        """Generated strings - arbitrary ones and near-keys - get the same answer from both rules."""
        self.assertEqual(KEY_RE.fullmatch(v) is not None, VERDICT_KEY_RE.fullmatch(v) is not None)
        self.assertEqual(is_verdict_key(v), KEY_RE.fullmatch(v) is not None)
