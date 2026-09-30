"""Transport ambiguity never becomes a feature's apparently valid request."""

import json
from urllib.parse import quote

import pytest
from hypothesis import given, strategies as st

from limn.web.errors import InputRejected
from limn.web.request_input import json_object, query_values


@given(st.text(), st.integers(), st.integers())
def test_duplicate_json_keys_are_rejected_at_every_depth(key, first, second):
    """Decoded duplicates cannot change meaning by nesting or selecting equal values."""
    member = json.dumps(key)
    body = '{"outer":{' + f"{member}:{first},{member}:{second}" + "}}"
    assert isinstance(json_object(body.encode()), InputRejected)


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1))
def test_duplicate_query_keys_are_rejected_after_decoding(key):
    """Percent spelling and empty values cannot hide a repeated parameter."""
    encoded = quote(key, safe="")
    assert isinstance(query_values(f"{encoded}=&{encoded}=1"), InputRejected)


@pytest.mark.parametrize(
    "raw",
    [b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b"[]", b'{"a":1e999}', b'{"a":"\\ud800"}', b'{"\\udfff":0}'],
)
def test_non_json_objects_are_rejected(raw):
    """Python decoder extensions and nonobjects never enter feature parsers."""
    assert isinstance(json_object(raw), InputRejected)


@pytest.mark.parametrize("raw", ["doc=%", "doc=%xz", "doc=%ff", "doc=a&%64oc=b"])
def test_malformed_or_ambiguous_query_is_rejected(raw):
    """Malformed escapes, invalid UTF-8 and encoded duplicate keys are refused."""
    assert isinstance(query_values(raw), InputRejected)


def test_normal_values_and_empty_defaults_remain_compatible():
    """Valid Unicode, unique unknown keys and ignored single empty values survive."""
    assert query_values("doc=&unknown=%ED%95%9C&name=a+b") == {"unknown": ["한"], "name": ["a b"]}
    assert json_object(b"  ") == {}
    assert json_object(b'{"a":{"b":1},"c":{"b":2}}') == {"a": {"b": 1}, "c": {"b": 2}}


def test_surrogate_pairs_decode_to_valid_unicode():
    """JSON escape pairs remain accepted when they denote one Unicode scalar."""
    assert json_object(b'{"text":"\\ud83d\\ude00"}') == {"text": "😀"}


@given(st.text(), st.characters(min_codepoint=128), st.text())
def test_raw_non_ascii_query_requires_percent_encoding(before, non_ascii, after):
    """Direct Unicode or surrogate codepoints cannot bypass the URI byte-language boundary."""
    assert isinstance(query_values(before + non_ascii + after), InputRejected)
