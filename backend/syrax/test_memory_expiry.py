import time
from syrax.memory import MemoryStore

def test_memory_expiry_for_observations(tmp_path, monkeypatch):
    m = MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")
    
    # Create old observation and old fact inside monkeypatched time
    with monkeypatch.context() as mp:
        mp.setattr(time, "time", lambda: time.time() - 31 * 86400)
        # also patch journal or wherever time comes from if needed, but python's time.time() is used or journal's? 
        # Wait, let's check how journal gets time or how test prompt specifies:
        # "make rows old inside with monkeypatch.context() as mp: with mp.setattr(syrax.journal, '_now', lambda: time.time() - 31 * 86400), and there remember an old observation ('remember(text, 'observation')') and an old fact; after the with block remember a new observation."
        pass

    with monkeypatch.context() as mp:
        import syrax.journal
        mp.setattr(syrax.journal, "_now", lambda: time.time() - 31 * 86400)
        m.remember("The azure skies are exceptionally clear today.", "observation")
        m.remember("Absolute security protocol alpha nine is established.", "fact")

    # Now remember a new observation after the with block
    m.remember("The skies are currently clear over Metropolis.", "observation")

    block = m.prompt_block()
    assert "The azure skies are exceptionally clear today" not in block
    assert "Absolute security protocol alpha nine is established" in block
    assert "The skies are currently clear over Metropolis" in block
