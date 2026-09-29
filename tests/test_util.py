import pytest

from autojob.util import has_term, html_to_text, iso_sort_key, to_iso


@pytest.mark.parametrize(
    "text,term,expected",
    [
        ("Experience with RAG pipelines", "rag", True),
        ("object storage and leverage", "rag", False),
        ("digital products", "git", False),
        ("Git and GitHub", "git", True),
        ("distributed systems required", "ms required", False),
        ("MS required for this role", "ms required", True),
        ("co-op term", "co-op", True),
        ("internal tools", "intern", False),
        ("C++ and Vue.js", "c++", True),
        ("C++ and Vue.js", "vue.js", True),
        ("5+ years of experience", "5+ years", True),
        ("machine\n learning", "machine learning", True),
    ],
)
def test_has_term(text, term, expected):
    assert has_term(text, term) is expected


def test_html_to_text_handles_escaped_html():
    assert html_to_text("&lt;p&gt;Hello &amp;amp; bye&lt;/p&gt;") == "Hello & bye"


def test_to_iso_normalises_epoch_ms_and_offsets():
    assert to_iso(1767225600000) == "2026-01-01T00:00:00+00:00"
    assert to_iso("2026-09-01T10:00:00-04:00") == "2026-09-01T14:00:00+00:00"
    assert to_iso("Posted 3 Days Ago") == "Posted 3 Days Ago"
    assert to_iso(None) is None


def test_iso_sort_key_puts_free_text_last():
    vals = ["Posted Today", "2026-01-01T00:00:00+00:00", None, "2026-05-01T00:00:00+00:00"]
    assert sorted(vals, key=iso_sort_key, reverse=True)[:2] == ["2026-05-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"]
