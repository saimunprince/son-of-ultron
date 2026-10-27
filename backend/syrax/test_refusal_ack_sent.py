"""A held send (intent.HELD) answered "Not sent again: the first message may already have gone out" says what was not
done. REFUSAL_ACK missed "not sent", so the check asked again and, since a surviving note ends the task PARTIAL
(claim_unproven), test_intent_ledger's correct answer ended PARTIAL in the 2026-10-27 integration gate."""

from syrax.agent import REFUSAL_ACK


def test_not_sent_and_not_repeated_acknowledge_the_refusal():
    assert REFUSAL_ACK.search("Not sent again: the first message may already have gone out; the second one went.")
    assert REFUSAL_ACK.search("The message was not repeated, since the first may have gone out.")


def test_an_answer_that_hides_the_refusal_still_misses():
    assert not REFUSAL_ACK.search("The folder is empty, so the cleanup is complete.")
    assert not REFUSAL_ACK.search("Message sent to Prince.")
