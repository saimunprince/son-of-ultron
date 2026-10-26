"""Live 2026-10-25 (Prince): "send message to bro bhi" became "hello", typed into the window that had the focus, and
"Message sent"; "play some random music" became a YouTube search page and "Music summoned." The tool guide every
brain gets now says that a message carries the human's words (ask for them, never invent them) and that playing goes
through youtube_play and is said only after desktop media status reads Playing. Whether a brain obeys is measured
live; this pins that the words reach it."""

from syrax.agent import TOOLS_GUIDE
from syrax.test_bridge import core_mod, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_world_claims import run

WORDS = "A message you send for the human carries the human's words"
PLAY = "say something plays only after `desktop` media status reads Playing"


def test_the_guide_says_whose_words_a_message_carries_and_how_playing_is_proven():
    assert WORDS in TOOLS_GUIDE and "ask for the text (ask_human) before typing anything, never invent it" in TOOLS_GUIDE
    assert "use `youtube_play` when you have it" in TOOLS_GUIDE and PLAY in TOOLS_GUIDE


def test_every_task_s_brain_gets_it(script):
    script.queue = [reply("Who should I write to bro bhi, and what should the message say?")]
    run("send message to bro bhi")
    system = core_mod.get_core().agent.system_prompt  # set fresh for every task (agent.run), sent with every call
    assert WORDS in system and PLAY in system
