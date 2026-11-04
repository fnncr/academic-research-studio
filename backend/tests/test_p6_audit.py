"""Independent audit: financial bounds and explicit limits of structural checks."""
from copy import deepcopy
from random import Random
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from app.model_adapters.openai_chat import OpenAIChat, usage_charge
from app.model_context import validate_proposal, ModelProblem
from app.model_gateway import MockGateway
from app.model_worker import run_once
from test_projects import storage
from test_evidence import workspace
from test_model_jobs import setup, enqueue, budget
from test_openai_gateway import approved, external, api_reply


def test_charge_bound_properties_and_rounding(setup):
    q, p, s, *_ = setup
    rng = Random(20261104)
    for cap in (256, 2000, 8000):
        task = external(s).model_copy(update={'max_output_tokens': cap})
        quote = OpenAIChat().quote(q.preview(p, task)['input']['context'], task)
        for inp, out in [(0, 0), (quote.input_token_bound, cap)] + [
            (rng.randrange(quote.input_token_bound + 1), rng.randrange(cap + 1)) for _ in range(200)
        ]:
            cached = rng.randrange(inp + 1)
            usage = {'prompt_tokens': inp, 'completion_tokens': out, 'total_tokens': inp + out,
                     'prompt_tokens_details': {'cached_tokens': cached}, 'completion_tokens_details': None}
            cost, _, _ = usage_charge(usage, quote)
            numerator = (inp - cached) * 4 + cached + out * 16
            assert 0 <= cost <= quote.max_units
            assert numerator <= cost * 10 < numerator + 10  # exact ceiling, no float money
            uncached = dict(usage, prompt_tokens_details=None)
            assert usage_charge(uncached, quote)[0] >= cost


def test_documented_input_window_can_settle_above_one_million(setup, approved):
    q, p, s, *_ = setup
    s = external(s)
    packet = q.preview(p, s)['input']['context']
    payload = api_reply(MockGateway().generate(packet, s, uuid4()).result)
    payload['usage'].update(prompt_tokens=1_000_001, total_tokens=1_000_051)
    enqueue(q, p, s)
    result = run_once(q, OpenAIChat(httpx.MockTransport(lambda _: httpx.Response(200, json=payload))))
    assert result['state'] == 'succeeded'
    assert budget(q, p)[1] == 0
    assert q.read(p, result['id'])['usage']['input_tokens'] == 1_000_001


@pytest.mark.parametrize('prose', [
    'DOI 10.5555/invented-audit-record якобы доказывает универсальный эффект.',
    'Этот источник доказывает чужой вывод, которого в сохранённом фрагменте нет.',
    'Correlation proves causation in every population.',
    'Перевод: отсутствие эффекта означает доказанное улучшение.',
])
def test_structural_validation_does_not_certify_free_prose(setup, prose):
    """Characterization of a known limit, NOT approval of these scientific claims."""
    q, p, s, *_ = setup
    packet = q.preview(p, s)['input']['context']
    raw = MockGateway().generate(packet, s, uuid4()).result
    raw['paragraphs'].append(prose)
    with Session(q.engine) as db:
        _, report = validate_proposal(db, p, s, packet, raw)
    assert report['structural'] == 'structurally_valid'
    assert report['semantic'] == 'uncertain' and report['scientific_verification'] == 'unverified'
    # Exact quote checks do catch invented wording labelled as a quotation.
    forged = deepcopy(raw)
    citation = forged['citations'][0]
    forged['paragraphs'][citation['paragraph']] = 'Поддельная цитата'
    citation.update(start=0, end=len('Поддельная цитата'), quote='Поддельная цитата', kind='quotation')
    with Session(q.engine) as db, pytest.raises(ModelProblem, match='quotation_mismatch'):
        validate_proposal(db, p, s, packet, forged)
