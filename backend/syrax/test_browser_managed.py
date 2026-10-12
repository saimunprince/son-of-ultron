"""SYRAX's own browser stays managed across self-restarts: the CDP URL SYRAX
sets for itself is inherited by every process it starts and must not read as
the human's configuration (live 2026-10-12: after a self-restart no browser was
launched and every browser call failed)."""

from syrax import browser


def test_only_the_humans_settings_count_as_configured():
    own = browser.CDP_URL
    assert not browser.user_configured({})
    assert not browser.user_configured({"BU_CDP_URL": own}) and not browser.user_configured({"BU_CDP_URL": own + "/"})
    assert browser.user_configured({"BU_CDP_URL": "http://127.0.0.1:9555"})
    assert browser.user_configured({"BU_CDP_URL": own, "BROWSER_USE_API_KEY": "k"})
    assert browser.user_configured({"BU_BROWSER_ID": "x"})
