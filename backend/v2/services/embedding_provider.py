"""V2-only providers. Nothing imports V1 RAG or reads the root .env."""
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import hashlib
import json
import math
import asyncio
import httpx2
import time
from typing import Protocol

from sqlalchemy import text


class EmbeddingError(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


@dataclass(frozen=True)
class Space:
    id: str
    provider: str
    model: str
    revision: str
    dimension: int = 1024


def space_for(settings):
    provider = settings.embedding_provider
    model = 'deterministic-sha256-v1' if provider == 'deterministic' else settings.embedding_model
    revision = (settings.embedding_model_revision if settings.embedding_model_revision != 'unverified' else '1') if provider == 'deterministic' else settings.embedding_model_revision
    key = json.dumps([provider,model,revision,settings.embedding_dimension,settings.embedding_endpoint if provider=='dashscope' else '', 'unit-normalized-v1'],separators=(',',':'))
    return Space(hashlib.sha256(key.encode()).hexdigest(),provider,model,revision,settings.embedding_dimension)


def enabled(settings):
    return settings.embedding_provider == 'deterministic' or (settings.embedding_provider == 'dashscope' and settings.embedding_cloud_enabled
        and settings.embedding_api_key is not None and bool(settings.embedding_api_key.get_secret_value()) and settings.embedding_model_revision != 'unverified')


def normalize(vector, dimension=1024):
    if not isinstance(vector,(list,tuple)) or len(vector)!=dimension:
        raise EmbeddingError('invalid_vector_dimension')
    try:
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in vector):raise ValueError()
    except (ValueError,OverflowError,TypeError):raise EmbeddingError('invalid_vector_values') from None
    norm=math.hypot(*vector)
    if not math.isfinite(norm) or norm < 1e-12:
        raise EmbeddingError('invalid_vector_norm')
    return [v/norm for v in vector]


def ordered_vectors(payload,count,dimension=1024):
    if not isinstance(payload,dict):raise EmbeddingError('invalid_embedding_response')
    rows=payload.get('output',{}).get('embeddings') if isinstance(payload.get('output',{}),dict) else None
    if rows is None:rows=payload.get('data')
    if not isinstance(rows,list) or len(rows)!=count:raise EmbeddingError('invalid_embedding_count')
    result=[None]*count
    for row in rows:
        if not isinstance(row,dict):raise EmbeddingError('invalid_embedding_response')
        index=row.get('text_index',row.get('index'))
        if 'index' in row and 'text_index' in row and row['index']!=row['text_index']:raise EmbeddingError('invalid_embedding_order')
        if type(index) is not int or not 0<=index<count or result[index] is not None:raise EmbeddingError('invalid_embedding_order')
        result[index]=normalize(row.get('embedding'),dimension)
    return result


class Provider(Protocol):
    space: Space
    def embed(self,texts,*,text_type,before_attempt): ...


def validate_inputs(texts,settings,text_type):
    if text_type not in {'document','query'} or not 1<=len(texts)<=settings.embedding_batch_size:
        raise EmbeddingError('embedding_input_limit')
    for value in texts:
        if not isinstance(value,str) or not value.strip() or len(value)>settings.embedding_max_input_chars or len(value.encode())>settings.embedding_max_input_bytes:
            raise EmbeddingError('embedding_input_limit')


class DeterministicProvider:
    """Explicit development fixture, not a semantic model or cloud fallback."""
    def __init__(self,settings):self.settings,self.space=settings,space_for(settings)
    def embed(self,texts,*,text_type,before_attempt):
        validate_inputs(texts,self.settings,text_type)
        before_attempt()
        result=[]
        for value in texts:
            raw=hashlib.shake_256(value.encode()).digest(2048)
            result.append(normalize([int.from_bytes(raw[i:i+2],'little')-32768 for i in range(0,2048,2)]))
        return result


class DashScopeProvider:
    def __init__(self,settings,limiter=None,transport=None):
        self.settings,self.space,self.limiter=settings,space_for(settings),limiter
        self.transport=transport or self._http

    async def _http_async(self,texts,text_type):
        # Absolute wall deadline, not only a per-socket inactivity timeout.
        async with asyncio.timeout(self.settings.embedding_timeout_seconds):
            async with httpx2.AsyncClient(timeout=self.settings.embedding_timeout_seconds,trust_env=False,follow_redirects=False) as client:
                async with client.stream('POST',self.settings.embedding_endpoint,json={
                    'model':self.space.model,'input':{'texts':texts},
                    'parameters':{'dimension':self.space.dimension,'text_type':text_type}},headers={
                        'Authorization':'Bearer '+self.settings.embedding_api_key.get_secret_value(),
                        'Accept-Encoding':'identity'}) as response:
                    code=response.status_code
                    if code!=200:
                        raise EmbeddingError('embedding_rate_limited' if code==429 else 'embedding_http_error',code in {408,429,500,502,503,504})
                    if response.headers.get('content-encoding','identity') not in {'','identity'}:
                        raise EmbeddingError('embedding_response_encoding')
                    data=bytearray()
                    async for chunk in response.aiter_raw(chunk_size=65536):
                        if len(data)+len(chunk)>4*1024*1024:raise EmbeddingError('embedding_response_limit')
                        data.extend(chunk)
        return json.loads(data)

    def _http(self,texts,text_type):
        try:payload=asyncio.run(self._http_async(texts,text_type))
        except (TimeoutError,httpx2.TimeoutException):raise EmbeddingError('embedding_timeout',True) from None
        except httpx2.RequestError:raise EmbeddingError('embedding_unavailable',True) from None
        except (ValueError,UnicodeError):raise EmbeddingError('invalid_embedding_response') from None
        if not isinstance(payload,dict):raise EmbeddingError('invalid_embedding_response')
        status=payload.get('status_code',200)
        if status!=200 or payload.get('code') or payload.get('error'):
            raise EmbeddingError('embedding_api_error',status in {408,429,500,502,503,504})
        if payload.get('model') not in {None,self.space.model}:raise EmbeddingError('embedding_model_mismatch')
        return payload

    def embed(self,texts,*,text_type,before_attempt):
        if not enabled(self.settings) or not self.settings.embedding_cloud_enabled:raise EmbeddingError('embedding_not_configured')
        validate_inputs(texts,self.settings,text_type)
        for attempt in range(self.settings.embedding_request_retries+1):
            before_attempt()  # Durable reservation before every possible billable attempt.
            try:
                with self.limiter() if self.limiter else nullcontext():
                    payload=self.transport(texts,text_type)
                return ordered_vectors(payload,len(texts),self.space.dimension)
            except EmbeddingError as error:
                if not error.retryable or attempt==self.settings.embedding_request_retries:raise
                time.sleep(self.settings.embedding_backoff_seconds*2**attempt)


def build_provider(settings,engine=None):
    if not enabled(settings):raise EmbeddingError('embedding_not_configured')
    if settings.embedding_provider=='deterministic':
        if settings.environment!='development' or not settings.embedding_allow_test_provider:raise EmbeddingError('test_provider_forbidden')
        return DeterministicProvider(settings)
    @contextmanager
    def limiter():
        # Session advisory lock with AUTOCOMMIT: no transaction/row lock spans the network call.
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
            slot=None
            try:
                for candidate in range(settings.embedding_concurrency):
                    if connection.scalar(text('SELECT pg_try_advisory_lock(174924,:slot)'),{'slot':candidate}):
                        slot=candidate;break
                if slot is None:raise EmbeddingError('embedding_busy',True)
                yield
            finally:
                if slot is not None:connection.execute(text('SELECT pg_advisory_unlock(174924,:slot)'),{'slot':slot})
    return DashScopeProvider(settings,limiter)
