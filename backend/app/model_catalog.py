"""Read-only compatibility. Documentation alone never authorizes dispatch."""
from copy import deepcopy
_SOL = {
    'provider':'openai', 'model':'gpt-6.1-sol', 'status':'blocked', 'ready':False,
    'executable':False, 'contract_adapter_available':True, 'reviewed_on':'2026-11-04',
    'documentation':'https://developers.openai.com/api/docs/models/gpt-6.1-sol',
    'documented_endpoints':['/v1/responses','/v1/chat/completions'],
    'context_window':1050000, 'max_output_tokens':128000,
    'documented_reasoning_efforts':['low','medium','high','xhigh','max'],
    'structured_outputs':True,
    'blockers':['account_access_unconfirmed','owner_consent_required','billing_adapter_not_approved','adapter_not_admitted'],
    'estimated_cost_units':None, 'maximum_reservation_units':None,
    'modes':[{'name':name,'proposed_effort':effort,'enabled':False} for name,effort in
             [('Standard Draft','medium'),('Deep Academic Writing','high'),('Complex Research Review','xhigh')]],
}
def unavailable_models():
    return [deepcopy(_SOL)]
