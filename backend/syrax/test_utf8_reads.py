"""Files SYRAX reads are UTF-8, whatever the OS code page says. Live
2026-10-03 (Windows, cp1252): the system map's "→" reached the self-model,
the SELF panel and the autonomous brief as "â†'"."""

import json

from syrax.journal import Journal
from syrax.selfmodel import SYSTEM_MAP, SelfModel


def test_system_map_arrows_survive_the_read(tmp_path):
    m = tmp_path / "map.json"
    m.write_bytes(json.dumps({"name": "x", "components": [{"component": "A", "failure_modes": ["a → b"], "code": [], "limitations": []}]}, ensure_ascii=False).encode("utf-8"))
    sm = SelfModel(Journal(tmp_path / "j.db"), system_map=m)
    assert sm.system_map() == json.loads(m.read_bytes().decode("utf-8"))
    assert sm.system_map()["components"][0]["failure_modes"] == ["a → b"]


def test_the_real_map_has_no_mojibake_after_reading(tmp_path):
    sm = SelfModel(Journal(tmp_path / "j.db"), system_map=SYSTEM_MAP)
    text = json.dumps(sm.structure(), ensure_ascii=False)
    assert "â" not in text and "Ã" not in text
