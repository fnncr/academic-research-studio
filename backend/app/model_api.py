"""Owner-only P6 transport; no provider secrets or internal worker fences."""
import asyncio
import json
import hmac
import os
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

from app.model_contracts import Contract, TaskSpec, Consent, AcceptanceSpec, HumanReviewSubmission, Short, Units
from app.model_context import ModelProblem
from app.model_jobs import ModelJobs
from app.projects import problem


class Enqueue(Contract):
    task: TaskSpec
    consent: Consent


class Decision(Contract):
    request_id: UUID
    # Explicit review of billing evidence, not a claim that a timeout was free.
    evidence_ref: Short
    acknowledged: Literal[True]

    @field_validator('evidence_ref')
    @classmethod
    def meaningful_reference(cls, value):
        if not value.strip(): raise ValueError('Evidence reference required')
        return value

    @field_validator('acknowledged', mode='before')
    @classmethod
    def explicit(cls, value):
        if value is not True: raise ValueError('Explicit review required')
        return value


class BudgetDecision(Decision):
    limit_units: Units


class Reconcile(Decision):
    charged_units: Units
    reason: Literal['provider_receipt', 'owner_full_reserve']


def owner(request: Request):
    token = os.environ.get('MODEL_OWNER_TOKEN', '')
    if len(token) < 32:
        raise problem(503, 'model_api_disabled', 'Настройте ключ владельца модельного API.')
    supplied = request.headers.get('authorization', '')
    if not hmac.compare_digest(supplied.encode(), ('Bearer '+token).encode()):
        raise problem(401, 'owner_required', 'Требуется авторизация владельца.')
    return 'owner'  # Personal deployment: one owner owns ALL projects.


router = APIRouter(prefix='/api/projects/{project_id}/model-jobs', tags=['model-jobs'],
                   dependencies=[Depends(owner)])


async def payload(request, schema):
    if request.headers.get('content-type','').split(';')[0] != 'application/json' or request.headers.get('content-encoding','identity') != 'identity':
        raise problem(415, 'unsupported_format', 'Ожидается несжатый JSON.')
    raw = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(raw)+len(chunk) > 256*1024: raise problem(413,'payload_too_large','Превышен лимит запроса.')
                raw.extend(chunk)
        return schema.model_validate_json(raw)
    except (ValueError, ValidationError):
        raise problem(422,'invalid_model_request','Проверьте поля модельного запроса.') from None
    except (TimeoutError, ClientDisconnect):
        raise problem(408,'upload_interrupted','Передача прервана.') from None


async def call(request, method, *args, status=200, **kwargs):
    engine = getattr(request.app.state,'project_engine',None)
    if engine is None: raise problem(503,'storage_unavailable','Хранилище недоступно.')
    try:
        value = await run_in_threadpool(getattr(ModelJobs(engine),method),*args,**kwargs)
        response = JSONResponse(jsonable_encoder(value),status_code=status)
        if len(response.body)>1024*1024: raise problem(413,'result_too_large','Результат превышает лимит.')
        return response
    except ModelProblem as exc:
        code = str(exc)
        status = 404 if code == 'not_found' else 422 if code in {'invalid_charge','invalid_resolution','invalid_usage','context_too_large'} else 409
        raise problem(status,code,'Операция не выполнена. Проверьте состояние, версии и бюджет.') from None
    except SQLAlchemyError:
        raise problem(503,'storage_unavailable','Хранилище временно недоступно; повторите тот же запрос.') from None


def public(job, result=False):
    return {k:v for k,v in job.items() if k not in {'lease_token','dispatch_id','result'}} | ({'result':job['result']} if result else {})



@router.get('/capabilities')
async def capabilities(project_id: UUID, request: Request):
    await call(request, 'budget', project_id)
    return {'provider': 'mock', 'model': 'mock-grounded-v1', 'external_enabled': False,
            'retention': 'local database only', 'currency': 'USD',
            'token_bound': 'UTF-8 bytes plus framing allowance',
            'paid_retries': False, 'requires_api_key': False}


@router.post('/preview')
async def preview(project_id: UUID, request: Request):
    return await call(request,'preview',project_id,await payload(request,TaskSpec))


@router.get('/budget')
async def budget(project_id: UUID, request: Request):
    return await call(request,'budget',project_id)


@router.put('/budget')
async def configure(project_id: UUID, request: Request):
    await call(request,'administer_budget',project_id,await payload(request,BudgetDecision),'owner')
    return await budget(project_id,request)


@router.post('/budget/unblock')
async def unblock(project_id: UUID, request: Request):
    await call(request,'administer_budget',project_id,await payload(request,Decision),'owner',unblock=True)
    return await budget(project_id,request)


@router.post('')
async def enqueue(project_id: UUID, request: Request):
    body = await payload(request,Enqueue)
    response = await call(request,'enqueue',project_id,body.task,body.consent,actor='owner',with_creation=True,status=202)
    job = json.loads(response.body)
    created = job.pop('created')
    return JSONResponse(public(job), status_code=202 if created else 200)


@router.get('')
async def listing(project_id: UUID, request: Request, limit: int = Query(20,ge=1,le=50)):
    response = await call(request,'list_jobs',project_id,limit)
    return [public(j) for j in json.loads(response.body)]


@router.get('/by-request/{request_id}')
async def by_request(project_id: UUID, request_id: UUID, request: Request):
    response = await call(request,'by_request',project_id,request_id)
    return public(json.loads(response.body))


@router.get('/{job_id}')
@router.get('/{job_id}/result')
async def read(project_id: UUID, job_id: UUID, request: Request):
    response = await call(request,'read',project_id,job_id)
    return public(json.loads(response.body),request.url.path.endswith('/result'))


@router.post('/{job_id}/cancel')
async def cancel(project_id: UUID, job_id: UUID, request: Request):
    response = await call(request,'cancel',project_id,job_id,actor='owner',decision=await payload(request,Decision))
    return public(json.loads(response.body))


@router.post('/{job_id}/accept')
async def accept(project_id: UUID, job_id: UUID, request: Request):
    return await call(request,'accept',project_id,job_id,await payload(request,AcceptanceSpec),actor='owner')


@router.post('/{job_id}/reconcile')
async def reconcile(project_id: UUID, job_id: UUID, request: Request):
    body = await payload(request,Reconcile)
    response = await call(request,'reconcile',project_id,job_id,body.charged_units,body.reason,actor='owner',decision=body)
    return public(json.loads(response.body))


@router.post('/{job_id}/human-review')
async def human_review(project_id: UUID, job_id: UUID, request: Request):
    response = await call(request,'human_review',project_id,job_id,
        await payload(request,HumanReviewSubmission),actor='owner')
    return public(json.loads(response.body),result=True)
