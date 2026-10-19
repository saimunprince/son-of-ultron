"""Quality run #51 (keep_secret): asked to summarise deploy notes in one sentence, the answer quoted the staging
API key it had read from the file. A credential the human's own words did not ask for is masked in the answer."""

from syrax.agent import mask_credentials

NOTE = "Staging deploy notes with the API key sk-live-9f8e7d6c5b4a3210; restart nginx after deploy."


def test_a_credential_nobody_asked_for_is_masked():
    out = mask_credentials(NOTE, "Summarise deploy.txt in one sentence.")
    assert "9f8e7d6c5b4a3210" not in out and "[credential masked]" in out and "restart nginx" in out
    for key in ("sk-ant-api03-" + "Zx81kLmN0pQrStUv92WxYz",
                "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2",
                "AIza" + "SyD4f8Gh2Jk9Lm3Np7Qr5St1Uv6Wx0Yz2Ab4",
                "ghp_" + "1a2B3c4D5e6F7g8H9i0J1k2L3m4N5o6P7q8R",
                "AKIA" + "IOSFODNN7EXAMPLE"):
        assert key not in mask_credentials(f"found {key} in the file", "what does the config say?")


def test_words_that_look_alike_are_left_alone():
    text = "Use sk-learn-pipeline-tutorial and the risk-assessment-framework-2024 notes."
    assert mask_credentials(text, "summarise") == text


def test_a_human_who_asks_for_the_key_gets_it():
    assert mask_credentials(NOTE, "What is the staging API key in deploy.txt?") == NOTE
