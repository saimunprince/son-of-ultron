"""Audit 2026-11-01 (integrations I-06): voice was English only: STT forced language "en", the voice hint asked for
English sentences, and Bengali text was read by an English voice. Speech is detected (unless SYRAX_STT_LANGUAGE says
otherwise; an English-only local model stays English), the hint follows the human's language, and Bengali script is
spoken with a Bengali voice."""

from syrax import server, voice


def test_the_stt_language_is_detected_unless_set_or_english_only():
    assert voice.stt_language("small.en") == "en"
    assert voice.stt_language("small") is None


def test_bengali_text_gets_a_bengali_voice_and_the_hint_follows_the_human():
    assert voice.voice_for("এখন সময় ১১টা।") == voice.TTS_VOICE_BN
    assert voice.voice_for("It is eleven.") != voice.TTS_VOICE_BN
    assert "English" not in server.VOICE_HINT and "language the human" in server.VOICE_HINT
