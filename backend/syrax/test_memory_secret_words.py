"""The secret filter matches whole words: ordinary facts that only contain a secret word go in, real secrets never do."""

import pytest

from syrax.memory import MemoryStore


def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


@pytest.mark.parametrize("text", [
    "Prince loves hotpot.",
    "Prince's sister is a secretary.",
    "Prince is learning tokenizers.",
    "Prince bought a tokenless e-reader.",
])
def test_a_word_that_only_contains_a_secret_word_is_remembered(tmp_path, text):
    m = store(tmp_path)
    assert m.remember(text).startswith("Remembered"), text
    assert [f["text"] for f in m.facts()] == [text]


@pytest.mark.parametrize("text", [
    "My password is hunter2.",
    "Prince's passwords are in the drawer.",
    "OTP 123456",
    "the otp is 4421",
    "api token: abc123def",
    "Prince's API key is xyz.",
    "apikey=xyz",
    "access_token=abc",
    "SECRET_KEY=abc",
    "his secrets: none",
    "githubToken is ghp_abc",
    "the dbPassword is x",
    "card pin code 1234",
    "key sk-abc123",
    "gsk_abcdef",
    "AIzaSyD-whatever",
])
def test_a_real_secret_is_still_refused(tmp_path, text):
    m = store(tmp_path)
    assert m.remember(text).startswith("Refused"), text
    assert m.facts() == []
