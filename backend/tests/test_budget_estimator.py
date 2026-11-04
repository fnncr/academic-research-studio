from copy import deepcopy
from app.sol_budget_scenarios import matrix
from app.budget_estimator import estimate
from app.model_gateway import Quote

def test_all_sizes_fall_back_without_false_optimization():
    cases=matrix()
    assert len(cases)==5 and cases[0]['payload_bytes']>cases[-1]['payload_bytes']
    assert all(c['bounded_input_tokens']==1048000 and c['reserved_cost']==10510000 for c in cases)
    assert all(c['estimated_cost'] is None and c['reserve_reduction_units']==0 for c in cases)
    assert all(c['confidence_or_bound_status']=='conservative_bound' for c in cases)

def test_payload_and_context_hash_change_independently():
    quote=Quote(10,5,20)
    a=estimate({'instructions':'RU'},{'version':'1'},quote)
    b=estimate({'instructions':'EN'},{'version':'1'},quote)
    c=estimate({'instructions':'RU'},{'version':'2'},quote)
    assert a['payload_hash']!=b['payload_hash'] and a['context_hash']==b['context_hash']
    assert a['context_hash']!=c['context_hash'] and a['payload_hash']==c['payload_hash']
