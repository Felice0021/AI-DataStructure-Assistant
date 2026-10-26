"""Independent non-streaming Chat Completions adapter; durable purpose-specific consent required."""
from contextlib import nullcontext
import asyncio
from dataclasses import dataclass
import json
import time
from typing import Protocol

import httpx2
from backend.v2.services.retrieval_service import capacity


class GenerationError(Exception):
    def __init__(self,code,retryable=False):
        super().__init__(code);self.code,self.retryable=code,retryable


@dataclass(frozen=True)
class Completion:
    content: str
    finish_reason: str = 'stop'


class Generator(Protocol):
    model: str | None
    def generate(self,messages,*,before_attempt) -> Completion: ...


class RequestBudget:
    def __init__(self,limit):self.limit,self.calls=limit,0
    def reserve(self):
        if self.calls>=self.limit:raise GenerationError('generation_budget_exhausted')
        self.calls+=1


class DisabledProvider:
    model=None
    def generate(self,messages,*,before_attempt):raise GenerationError('generation_disabled')


class DeterministicProvider:
    """Quotes supplied evidence; validates plumbing, not answer quality or reasoning."""
    model='deterministic-evidence-quote-v1'
    def generate(self,messages,*,before_attempt):
        before_attempt()
        blocks=json.loads(messages[2]['content'])['blocks']
        if not blocks:return Completion(json.dumps({'status':'insufficient_evidence','answer':'','used_source_ids':[]}))
        block=blocks[0];citation=block['citation_id']
        # Quote a bounded complete source block. No computation or execution claims.
        mode='code' if '回答模式：code' in messages[0]['content'] else 'exercise' if '回答模式：exercise' in messages[0]['content'] else 'qa'
        prefix={'qa':'资料原文：','exercise':'题目分析：仅能根据所给资料说明。\n解题过程：引用原文，不补充未经证实的推导。\n最终答案：',
                'code':'代码作用与问题分析：仅引用资料。\n修改建议、复杂度和边界条件需以原文为依据：'}[mode]
        answer=prefix+'\n'+block['content']+' '+citation
        return Completion(json.dumps({'status':'answered','answer':answer,'used_source_ids':[citation]},ensure_ascii=False))


class QwenProvider:
    def __init__(self,settings,engine=None,transport=None,cloud_guard=None):
        self.settings,self.engine,self.transport=settings,engine,transport
        self.cloud_guard=cloud_guard
        self.model=settings.generation_model

    async def _http_async(self,messages):
        s=self.settings
        async with asyncio.timeout(s.generation_timeout_seconds):
            async with httpx2.AsyncClient(timeout=s.generation_timeout_seconds,trust_env=False,follow_redirects=False) as client:
                async with client.stream('POST',s.generation_endpoint,headers={
                    'Authorization':'Bearer '+s.generation_api_key.get_secret_value(),'Accept-Encoding':'identity'},json={
                    'model':self.model,'messages':messages,'temperature':s.generation_temperature,
                    'max_tokens':s.generation_max_output_tokens,'stream':False,'enable_thinking':False,
                    'response_format':{'type':'json_object'}}) as response:
                    status=response.status_code
                    if status!=200:
                        code='generation_rate_limited' if status==429 else 'generation_model_unavailable' if status==404 else 'generation_parameter_error' if status in {400,422} else 'generation_http_error'
                        raise GenerationError(code,status in {408,429,500,502,503,504})
                    if response.headers.get('content-encoding','identity') not in {'','identity'}:raise GenerationError('generation_response_encoding')
                    raw=bytearray()
                    async for chunk in response.aiter_raw(chunk_size=16384):
                        if len(raw)+len(chunk)>262144:raise GenerationError('generation_response_limit')
                        raw.extend(chunk)
        return json.loads(raw)

    def _http(self,messages):
        try:return asyncio.run(self._http_async(messages))
        except (TimeoutError,httpx2.TimeoutException):raise GenerationError('generation_timeout',True) from None
        except httpx2.RequestError:raise GenerationError('generation_unavailable',True) from None
        except (ValueError,UnicodeError,RecursionError):raise GenerationError('generation_invalid_response') from None

    def generate(self,messages,*,before_attempt):
        s=self.settings
        # Production transport requires a durable purpose-specific authorization guard.
        if self.transport is None and self.cloud_guard is None:raise GenerationError('generation_consent_not_configured')
        if self.transport is not None and not (s.environment=='development' and s.generation_allow_test_provider):raise GenerationError('test_transport_forbidden')
        if not (s.generation_cloud_enabled and s.generation_model_verified and s.generation_api_key):raise GenerationError('generation_not_configured')
        if len(json.dumps(messages,ensure_ascii=False).encode())>s.generation_max_input_bytes:raise GenerationError('generation_input_limit')
        for attempt in range(s.generation_retries+1):
            before_attempt()
            try:
                with capacity(self.engine,s.generation_concurrency,namespace=174929):
                    with self.cloud_guard() if self.transport is None else nullcontext() as ticket:
                        payload=(self.transport or self._http)(messages)
                        if ticket is not None:ticket.record(payload)
                if not isinstance(payload,dict) or payload.get('error') or payload.get('model') not in {None,self.model}:
                    raise GenerationError('generation_invalid_response')
                choices=payload.get('choices')
                if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):raise GenerationError('generation_invalid_response')
                choice=choices[0];message=choice.get('message')
                if (not isinstance(message,dict) or message.get('role')!='assistant' or message.get('tool_calls')
                    or message.get('function_call') or message.get('refusal') or not isinstance(message.get('content'),str)):
                    raise GenerationError('generation_invalid_response')
                usage=payload.get('usage',{})
                tokens=usage.get('completion_tokens') if isinstance(usage,dict) else None
                if tokens is not None and (type(tokens) is not int or not 0<=tokens<=s.generation_max_output_tokens):raise GenerationError('generation_output_limit')
                return Completion(message['content'],choice.get('finish_reason'))
            except GenerationError as error:
                if not error.retryable or attempt==s.generation_retries:raise
                time.sleep(s.generation_backoff_seconds*2**attempt)


def build_provider(settings,engine,cloud_guard=None):
    if settings.generation_provider=='disabled':return DisabledProvider()
    if settings.generation_provider=='deterministic':
        if not (settings.environment=='development' and settings.generation_allow_test_provider):raise GenerationError('test_provider_forbidden')
        return DeterministicProvider()
    return QwenProvider(settings,engine,cloud_guard=cloud_guard)
