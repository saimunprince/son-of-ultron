"""Quality run #88 (self_patch_with_test): the task ended on "To create it, I need to provide the full content of the
new file in the diff. I will do this in the next step." PROMISE did not know work promised for a later step, so
the promise became the final answer. Such an answer is now asked for once (FINAL_ASK), like the other promises;
instructions to the human ("In the next step, click Save") are not promises."""

from syrax.agent import PROMISE


def test_work_promised_for_a_later_step_is_a_promise():
    for text in ("The patch failed because the file does not exist. I will do this in the next step.",
                 "I'll fix that next.", "I will retry it now with the full file.", "In the next step, I will create the file."):
        assert PROMISE.search(text), text


def test_instructions_and_courtesy_are_not():
    for text in ("In the next step, click Save.", "I will be happy to help with anything else.", "Next, run npm install.",
                 "The file was created. Run it with python main.py.", "It does this next to the window."):
        assert not PROMISE.search(text), text
