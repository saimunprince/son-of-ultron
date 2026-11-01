"""Audit 2026-11-01 (self-improvement F7): the second-brain review was independent per provider only, and one model
runs on several providers (groq and cerebras both serve gpt-oss-120b). A provider serving the author's model is not
offered as the reviewer; a different model is."""

from syrax.review import model_family, reviewers


class Store:
    order = ["groq", "cerebras", "openrouter", "gemini"]
    models = {"groq": "openai/gpt-oss-120b", "cerebras": "gpt-oss-120b", "openrouter": "nvidia/nemotron-3-ultra:free",
              "gemini": "gemini-3.5-flash"}

    def enabled(self, p):
        return True

    def model(self, p):
        return self.models[p]


class Router:
    store = Store()


def test_the_same_model_on_another_provider_is_not_an_independent_reviewer():
    assert model_family("openai/gpt-oss-120b") == model_family("gpt-oss-120b:free") == "gpt-oss-120b"
    assert reviewers(Router(), ["groq"]) == ["openrouter", "gemini"]
    assert reviewers(Router(), ["gemini"]) == ["groq", "cerebras", "openrouter"]
