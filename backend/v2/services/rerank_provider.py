"""Bounded independent V2 reranking. No V1 imports, credentials or global corpus."""
from contextlib import nullcontext
import asyncio
import json
import math
import time
from typing import Protocol

import httpx2
from backend.v2.services.lexical_search import tokenize
from backend.v2.services.retrieval_service import capacity


class RerankError(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class Reranker(Protocol):
    model: str
    def rerank(self, query: str, documents: list[str]) -> list[dict]: ...


def validate_scores(rows, count):
    if not isinstance(rows,list) or len(rows)!=count:
        raise RerankError('rerank_invalid_count')
    scores={}
    for row in rows:
        if not isinstance(row,dict):raise RerankError('rerank_invalid_response')
        index, score=row.get('index'),row.get('relevance_score')
        if type(index) is not int or not 0<=index<count or index in scores:
            raise RerankError('rerank_invalid_index')
        try:
            valid=type(score) in (int,float) and math.isfinite(score) and 0<=score<=1
        except OverflowError:valid=False
        if not valid:raise RerankError('rerank_invalid_score')
        scores[index]=float(score)
    return scores


def validate_inputs(query,documents,settings):
    if not 1<=len(documents)<=min(settings.rerank_batch_size,settings.rerank_max_candidates):
        raise RerankError('rerank_input_limit')
    if len(query.encode())>min(4000,settings.rerank_max_item_bytes):raise RerankError('rerank_input_limit')
    values=[query,*documents]
    if any(not isinstance(v,str) or not v.strip() or len(v.encode())>settings.rerank_max_item_bytes for v in values):
        raise RerankError('rerank_input_limit')
    # Provider token accounting repeats the query for every document.
    if sum(len(v.encode()) for v in documents)+len(query.encode())*len(documents)>settings.rerank_max_total_bytes:
        raise RerankError('rerank_input_limit')


class DisabledProvider:
    model=None
    def rerank(self,query,documents):raise RerankError('rerank_disabled')


class DeterministicProvider:
    model='deterministic-overlap-v1'
    def __init__(self,settings):self.settings=settings
    def rerank(self,query,documents):
        validate_inputs(query,documents,self.settings)
        terms=set(tokenize(query))
        return [{'index':i,'relevance_score':len(terms&set(tokenize(value)))/max(1,len(terms))} for i,value in enumerate(documents)]


class QwenProvider:
    def __init__(self,settings,engine=None,transport=None,cloud_guard=None):
        self.settings,self.engine,self.transport=settings,engine,transport or self._http
        self.cloud_guard,self.remote=cloud_guard,transport is None
        self.model=settings.rerank_model

    async def _http_async(self,query,documents):
        s=self.settings
        async with asyncio.timeout(s.rerank_timeout_seconds):
            async with httpx2.AsyncClient(timeout=s.rerank_timeout_seconds,trust_env=False,follow_redirects=False) as client:
                async with client.stream('POST',s.rerank_endpoint,headers={
                    'Authorization':'Bearer '+s.rerank_api_key.get_secret_value(),'Accept-Encoding':'identity'},json={
                    'model':self.model,'input':{'query':query,'documents':documents},
                    'parameters':{'top_n':len(documents)}}) as response:
                    code=response.status_code
                    if code!=200:
                        label='rerank_rate_limited' if code==429 else 'rerank_model_unavailable' if code==404 else 'rerank_parameter_error' if code in {400,422} else 'rerank_http_error'
                        raise RerankError(label,code in {408,429,500,502,503,504})
                    if response.headers.get('content-encoding','identity') not in {'','identity'}:raise RerankError('rerank_response_encoding')
                    raw=bytearray()
                    async for chunk in response.aiter_raw(chunk_size=16384):
                        if len(raw)+len(chunk)>262144:raise RerankError('rerank_response_limit')
                        raw.extend(chunk)
        return json.loads(raw)

    def _http(self,query,documents):
        try:return asyncio.run(self._http_async(query,documents))
        except (TimeoutError,httpx2.TimeoutException):raise RerankError('rerank_timeout',True) from None
        except httpx2.RequestError:raise RerankError('rerank_unavailable',True) from None
        except (ValueError,UnicodeError):raise RerankError('rerank_invalid_response') from None

    def rerank(self,query,documents):
        s=self.settings
        if not (s.rerank_cloud_enabled and s.rerank_model_verified and s.rerank_api_key and s.rerank_api_key.get_secret_value()):
            raise RerankError('rerank_not_configured')
        validate_inputs(query,documents,s)
        for attempt in range(s.rerank_retries+1):
            try:
                # AUTOCOMMIT session advisory slot: no transaction or row lock across HTTP.
                with capacity(self.engine,s.rerank_concurrency,namespace=174926):
                    if self.remote and self.cloud_guard is None:raise RerankError('cloud_authorization_required')
                    with self.cloud_guard() if self.remote else nullcontext() as ticket:
                        payload=self.transport(query,documents)
                        if ticket is not None:ticket.record(payload)
                if not isinstance(payload,dict) or payload.get('status_code',200)!=200 or payload.get('code') or payload.get('error') or payload.get('model') not in {None,self.model}:
                    raise RerankError('rerank_invalid_response')
                output=payload.get('output')
                if not isinstance(output,dict):raise RerankError('rerank_invalid_response')
                rows=output.get('results');validate_scores(rows,len(documents));return rows
            except RerankError as error:
                if not error.retryable or attempt==s.rerank_retries:raise
                time.sleep(s.rerank_backoff_seconds*2**attempt)


def build_provider(settings,engine,cloud_guard=None):
    if settings.rerank_provider=='disabled':return DisabledProvider()
    if settings.rerank_provider=='deterministic':
        if not (settings.environment=='development' and settings.rerank_allow_test_provider):raise RerankError('test_provider_forbidden')
        return DeterministicProvider(settings)
    if not (settings.rerank_cloud_enabled and settings.rerank_model_verified and settings.rerank_api_key):
        raise RerankError('rerank_not_configured')
    return QwenProvider(settings,engine,cloud_guard=cloud_guard)
