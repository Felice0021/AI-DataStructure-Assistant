import asyncio
from contextlib import nullcontext,asynccontextmanager
import json
import time
import pytest
import httpx2
from backend.v2.core.config import Settings
from backend.v2.services.generation_provider import QwenProvider,GenerationError,RequestBudget
from backend.v2.services.conversation_stream import StreamStopped


def settings(**kwargs):
    return Settings(_env_file=None,db_password='synthetic-unit-only',environment='development',generation_provider='qwen',
        generation_api_key='synthetic-not-a-key',generation_cloud_enabled=True,generation_model_verified=True,
        generation_allow_test_provider=True,generation_retries=0,**kwargs)


def event(part=None,finish=None,**kw):
    return json.dumps({'choices':[{'index':0,'delta':{'content':part},'finish_reason':finish}],**kw},ensure_ascii=False)


def events(answer='增量回答中文😀 [S1]'):
    raw=json.dumps({'status':'answered','answer':answer,'used_source_ids':['[S1]']},ensure_ascii=True)
    return [event(raw[:40]),event(raw[40:47]),event(raw[47:]),event('', 'stop'),json.dumps({'choices':[], 'usage':{'prompt_tokens':20,'completion_tokens':30,'total_tokens':50}}),'[DONE]']


@pytest.fixture(autouse=True)
def capacity(monkeypatch):monkeypatch.setattr('backend.v2.services.generation_stream.capacity',lambda *a,**kw:nullcontext())


def test_default_generation_limits_allow_bounded_long_course_explanations():
    s=settings()
    assert s.generation_max_output_tokens==3072
    assert s.generation_max_output_bytes==24000
    assert s.generation_timeout_seconds==60
    assert s.generation_timeout_seconds<s.conversation_stream_timeout_seconds


def test_provider_emits_actual_increments_before_completion_and_keeps_final_json():
    done=False;observed=[];closed=[]
    async def transport(_):
        nonlocal done
        try:
            for item in events():yield item
            done=True
        finally:closed.append(True)
    p=QwenProvider(settings(),stream_transport=transport)
    budget=RequestBudget(1)
    result=p.generate_stream([],before_attempt=budget.reserve,on_delta=lambda x:observed.append((x,done)),check_cancel=lambda:None)
    assert len(observed)>=2 and all(not end for _,end in observed)
    assert ''.join(x for x,_ in observed)=='增量回答中文😀 [S1]'
    assert json.loads(result.content)['used_source_ids']==['[S1]'] and budget.calls==1 and closed


def test_real_http_adapter_sets_stream_true_and_decodes_fragmented_utf8(monkeypatch):
    captured={};closed=[]
    class Response:
        status_code=200;headers={'content-type':'text/event-stream; charset=utf-8'}
        async def aiter_raw(self,**kw):
            assert not kw # do not wait for a fixed-size body buffer
            wire=''.join('data: '+x+'\r\n\r\n' for x in events('中文😀 栈 [S1]')).encode()
            for i in range(0,len(wire),3):yield wire[i:i+3]
    class Client:
        def __init__(self,**kw):assert kw['trust_env'] is False and kw['follow_redirects'] is False
        async def __aenter__(self):return self
        async def __aexit__(self,*a):closed.append(True)
        @asynccontextmanager
        async def stream(self,method,url,**kwargs):
            captured.update(kwargs);yield Response()
    monkeypatch.setattr('backend.v2.services.generation_stream.httpx2.AsyncClient',Client)
    class Ticket:
        def record(self,payload):captured['usage']=payload['usage']
    from contextlib import contextmanager
    @contextmanager
    def guard():yield Ticket()
    p=QwenProvider(settings(),cloud_guard=guard);parts=[]
    result=p.generate_stream([],before_attempt=lambda:None,on_delta=parts.append,check_cancel=lambda:None)
    assert captured['json']['stream'] is True and captured['json']['stream_options']=={'include_usage':True}
    assert captured['json']['max_tokens']==p.settings.generation_max_output_tokens
    assert captured['json']['response_format']=={'type':'json_object'}
    assert captured['usage']['completion_tokens']==30 and closed
    assert ''.join(parts)=='中文😀 栈 [S1]' and json.loads(result.content)['answer']==''.join(parts)


@pytest.mark.parametrize('items,code',[
    (events()[:-1],'generation_stream_incomplete'),
    (['[DONE]'],'generation_stream_incomplete'),
    ([event('{"status":"answered","answer":"partial','length')],'truncated_or_invalid_completion'),
    (['{"error":{"message":"private upstream error"}}'],'generation_invalid_response'),
    ([json.dumps({'choices':[{'index':1,'delta':{'content':'x'},'finish_reason':None}]})],'generation_invalid_response'),
    ([event('x',model='other-model')],'generation_invalid_response'),
    ([event('x',usage={'completion_tokens':99999})],'generation_output_limit'),
    ([event('x',usage={'completion_tokens':True})],'generation_invalid_response'),
    ([json.dumps({'choices':[{'index':0,'delta':{'tool_calls':['x']},'finish_reason':None}]})],'generation_invalid_response'),
    ([event('{"status":"answered","answer":"x","answer":"y"}')],'generation_invalid_response'),
])
def test_malformed_or_incomplete_provider_stream_never_becomes_completion(items,code):
    async def source(_):
        for item in items:yield item
    with pytest.raises(GenerationError) as e:QwenProvider(settings(),stream_transport=source).generate_stream([],before_attempt=lambda:None,on_delta=lambda _:None,check_cancel=lambda:None)
    assert e.value.code==code


@pytest.mark.parametrize('cancel',[False,True])
def test_timeout_and_cancel_close_a_blocked_upstream_reader(cancel):
    closed=[];start=time.monotonic()
    async def blocked(_):
        try:
            yield events()[0]
            await asyncio.Event().wait()
        finally:closed.append(True)
    def check():
        if cancel and time.monotonic()-start>0.05:raise StreamStopped('stream_cancelled')
    p=QwenProvider(settings(generation_timeout_seconds=0.2),stream_transport=blocked)
    with pytest.raises(StreamStopped if cancel else GenerationError) as e:
        p.generate_stream([],before_attempt=lambda:None,on_delta=lambda _:None,check_cancel=check)
    assert e.value.code==('stream_cancelled' if cancel else 'generation_timeout') and closed
    assert time.monotonic()-start<1


def test_no_retry_after_visible_increment_but_pre_content_retry_obeys_same_call_budget():
    calls=[]
    async def fail_after(_):
        calls.append(1)
        yield event('{"status":"answered","answer":"visible text')
        raise GenerationError('generation_timeout',True)
    s=settings();s.generation_retries=2;s.generation_backoff_seconds=0
    with pytest.raises(GenerationError):QwenProvider(s,stream_transport=fail_after).generate_stream([],before_attempt=RequestBudget(3).reserve,on_delta=lambda _:None,check_cancel=lambda:None)
    assert len(calls)==1
    async def early(_):
        calls.append(2)
        raise GenerationError('generation_rate_limited',True)
        yield
    budget=RequestBudget(1)
    with pytest.raises(GenerationError) as error:QwenProvider(s,stream_transport=early).generate_stream([],before_attempt=budget.reserve,on_delta=lambda _:None,check_cancel=lambda:None)
    assert error.value.code=='generation_budget_exhausted' and budget.calls==1 and calls==[1,2]


def test_stream_cannot_bypass_guard_or_use_test_transport_in_production():
    with pytest.raises(GenerationError,match='generation_consent_not_configured'):
        QwenProvider(settings()).generate_stream([],before_attempt=lambda:None,on_delta=lambda _:None,check_cancel=lambda:None)
    s=settings();s.environment='production'
    with pytest.raises(GenerationError,match='test_transport_forbidden'):
        QwenProvider(s,stream_transport=lambda _:None).generate_stream([],before_attempt=lambda:None,on_delta=lambda _:None,check_cancel=lambda:None)


def test_cancel_fences_later_retrieval_cloud_attempts_without_dropping_existing_budget_hook(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4
    from backend.v2.schemas.rag import AskRequest
    from backend.v2.services import rag_service
    class Control:
        stopped=False
        def check(self):
            if self.stopped:raise StreamStopped('stream_cancelled')
        def stage(self,*a,**kw):self.check()
    control=Control();reserved=[]
    def prepare(*a,before_cloud_call,**kw):
        before_cloud_call('embedding')
        control.stopped=True
        before_cloud_call('reranking')
        raise AssertionError('Cancelled work must not continue')
    monkeypatch.setattr(rag_service,'capacity',lambda *a,**kw:nullcontext())
    monkeypatch.setattr(rag_service,'prepare_context',prepare)
    with pytest.raises(StreamStopped):
        rag_service.ask(SimpleNamespace(kw={'bind':None}),SimpleNamespace(id=uuid4()),
            AskRequest(query='栈',knowledge_base_ids=[uuid4()]),settings(),verify_session=lambda _:None,
            before_cloud_call=reserved.append,stream=control)
    assert reserved==['embedding']
