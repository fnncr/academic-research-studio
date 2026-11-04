"""Versioned local estimator. Estimates never reduce an unproved financial bound."""
import json
from app.manuscripts import digest
VERSION='sol-budget-fallback-v1'

def estimate(body,context,quote,regional=False):
    size=len(json.dumps(body,ensure_ascii=False).encode('utf-8'))
    return {'estimator_version':VERSION,'estimated_input_tokens':None,
        'bounded_input_tokens':quote.input_token_bound,'max_output_tokens':quote.output_token_cap,
        'reasoning_token_limit':None,'reasoning_in_output_cap':True,
        'estimated_cost':None,'reserved_cost':quote.max_units,'currency':'USD-micro',
        'pricing_profile':'regional' if regional else 'global','pricing_version':quote.pricing_version,
        'estimate_method':'full_context_fallback','confidence_or_bound_status':'conservative_bound',
        'fallback_reason':'no_local_full_payload_bound; external_counting_requires_separate_consent',
        'context_hash':digest(context),'payload_hash':digest(body),'payload_bytes':size,
        'reserve_reduction_units':0}
