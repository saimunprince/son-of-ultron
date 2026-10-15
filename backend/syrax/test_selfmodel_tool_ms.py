import time
import pytest
import syrax
from syrax.journal import Journal
from syrax.selfmodel import SelfModel

def test_selfmodel_tool_ms(tmp_path, monkeypatch):
    j = Journal(tmp_path / 'j.db')
    clock = [time.time() - 600]
    monkeypatch.setattr(syrax.journal, '_now', lambda: clock[0])
    
    t = j.start_task_sync('work', kind='conversation')
    
    # 3 know calls (tool.started with {'id': f'c{i}', 'name': 'know', 'args': {}}, add 0.1, 0.3 and 0.5 s to clock, tool.completed)
    for i in range(3):
        j.record_sync('tool.started', {'id': f'c{i}', 'name': 'know', 'args': {}}, task_id=t)
        delta = [0.1, 0.3, 0.5][i]
        clock[0] += delta
        j.record_sync('tool.completed', {'id': f'c{i}', 'name': 'know', 'ok': True}, task_id=t)
        
    # one desktop call that fails after 2.0 s
    j.record_sync('tool.started', {'id': 'd1', 'name': 'desktop', 'args': {}}, task_id=t)
    clock[0] += 2.0
    j.record_sync('tool.failed', {'id': 'd1', 'name': 'desktop', 'ok': False}, task_id=t)
    
    # one python_execute call whose tool.failed has 'refused': True
    j.record_sync('tool.started', {'id': 'p1', 'name': 'python_execute', 'args': {}}, task_id=t)
    j.record_sync('tool.failed', {'id': 'p1', 'name': 'python_execute', 'refused': True}, task_id=t)
    
    # one research call that never finishes
    j.record_sync('tool.started', {'id': 'r1', 'name': 'research', 'args': {}}, task_id=t)
    
    m = SelfModel(j)
    perf = m.performance()
    assert perf['tool_ms'] == {'know': {'count': 3, 'p50': 300, 'p90': 500}, 'desktop': {'count': 1, 'p50': 2000, 'p90': 2000}}
