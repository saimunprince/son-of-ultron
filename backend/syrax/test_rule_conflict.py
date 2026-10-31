"""EVOLUTION_PLAN direction 196 (value-conflict analysis): a request that goes against a rule the owner set was carried
out like any other. A prohibiting rule whose words the request mostly shares is named to the brain before it acts, and
the brain is told to say so and ask; a request that only touches one word of a rule is not flagged."""

from syrax.brains import BrainRouter
from syrax.memory import rule_conflicts
from syrax.test_bridge import ORIGIN, TestClient, boot, drain_until_idle, reply, script, server  # noqa: F401

def systems_seen(monkeypatch, answer):
    seen = []

    async def fake(self, messages, **kw):
        seen.append(" ".join(str(getattr(m, "content", "")) for m in kw.get("system_msgs") or []))
        return reply(answer)

    monkeypatch.setattr(BrainRouter, "ask_tool", fake)
    return seen


RULES = [{"type": "rule", "text": "Never delete my photos"},
         {"type": "rule", "text": "Always answer in one line"},
         {"type": "fact", "text": "Never delete anything in Downloads"},  # a fact, not a rule
         {"type": "rule", "text": "Don't push to main without asking me"}]


def test_prohibiting_rules_the_request_mostly_shares_are_found():
    assert rule_conflicts("delete the old photos from Pictures", RULES) == ["Never delete my photos"]
    assert rule_conflicts("push my branch to main", RULES) == ["Don't push to main without asking me"]
    assert rule_conflicts("delete the temp file", RULES) == []  # one word of a two-word rule
    assert rule_conflicts("show my photos", RULES) == []
    assert rule_conflicts("answer in one line: what is 2+2", RULES) == []  # "always" rules are not prohibitions


def test_the_brain_is_told_before_it_acts(script, monkeypatch):
    from syrax import memory

    monkeypatch.setattr(memory.MemoryStore, "facts", lambda self, *a, **k: RULES)
    seen = systems_seen(monkeypatch, "That breaks your rule. Go ahead?")
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "delete the old photos from Pictures"})
        drain_until_idle(ws)
    assert 'RULE CHECK: the human set the rule "Never delete my photos"' in seen[0] and "ask_human" in seen[0]


def test_no_rule_no_note(script, monkeypatch):
    from syrax import memory

    monkeypatch.setattr(memory.MemoryStore, "facts", lambda self, *a, **k: RULES)
    seen = systems_seen(monkeypatch, "4")
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "what is 2+2"})
        drain_until_idle(ws)
    assert seen and "RULE CHECK" not in seen[0]
