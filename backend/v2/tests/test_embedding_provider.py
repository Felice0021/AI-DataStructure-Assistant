import math
from urllib.error import HTTPError
import pytest
from backend.v2.core.config import Settings
from backend.v2.services.embedding_provider import DashScopeProvider, EmbeddingError, normalize, ordered_vectors, space_for


def config(**kwargs):
    return Settings(_env_file=None,db_password='unit-test-only-not-real-password',embedding_provider='dashscope',embedding_cloud_enabled=True,
                    embedding_api_key='test-only-not-real-api-key',embedding_model_revision='fixture-v1',embedding_backoff_seconds=0.1,**kwargs)


def axis(index=0):return [1.0 if i==index else 0.0 for i in range(1024)]


@pytest.mark.parametrize('field',['index','text_index'])
def test_response_reorders(field):
    payload={'output':{'embeddings':[{field:1,'embedding':axis(1)},{field:0,'embedding':axis()}]}}
    assert ordered_vectors(payload,2)==[axis(),axis(1)]


@pytest.mark.parametrize('rows,count',[
    ([{'index':0,'embedding':axis()}],2),
    ([{'index':0,'embedding':axis()},{'index':0,'embedding':axis()}],2),
    ([{'index':-1,'embedding':axis()}],1),
    ([{'embedding':axis()}],1),
    ([{'index':True,'embedding':axis()}],1),
    ([{'index':0,'text_index':1,'embedding':axis()}],1),
])
def test_bad_count_or_order(rows,count):
    with pytest.raises(EmbeddingError):ordered_vectors({'data':rows},count)


@pytest.mark.parametrize('vector',[[0.]*1024,[1.]*1023,[float('nan')]*1024,[float('inf')]*1024,[True]*1024,['1']*1024,[10**1000]*1024])
def test_invalid_vectors(vector):
    with pytest.raises(EmbeddingError):normalize(vector)


def test_norm_is_unit():assert math.isclose(math.hypot(*normalize([2.]*1024)),1)


@pytest.mark.parametrize('code,retryable',[(429,True),(503,True),(401,False),(400,False)])
def test_http_error_classification(code,retryable,monkeypatch):
    from contextlib import asynccontextmanager
    class Response:
        status_code=code
    class Broken:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        @asynccontextmanager
        async def stream(self,*args,**kwargs):yield Response()
    monkeypatch.setattr('backend.v2.services.embedding_provider.httpx2.AsyncClient',Broken)
    with pytest.raises(EmbeddingError) as error:DashScopeProvider(config())._http(['synthetic'],'document')
    assert error.value.retryable==retryable and 'private' not in str(error.value)


def test_timeout_and_retry_budget():
    attempts=[]
    def failing(*args):raise EmbeddingError('embedding_timeout',True)
    with pytest.raises(EmbeddingError):DashScopeProvider(config(),transport=failing).embed(['synthetic'],text_type='document',before_attempt=lambda:attempts.append(1))
    assert len(attempts)==3


def test_permanent_failure_does_not_retry():
    attempts=[]
    def failing(*args):raise EmbeddingError('invalid_embedding_response')
    with pytest.raises(EmbeddingError):DashScopeProvider(config(),transport=failing).embed(['synthetic'],text_type='document',before_attempt=lambda:attempts.append(1))
    assert len(attempts)==1


def test_disabled_cloud_never_calls_transport():
    settings=config().model_copy(update={'embedding_cloud_enabled':False})
    def forbidden(*args):raise AssertionError('Transport must never be called')
    with pytest.raises(EmbeddingError):DashScopeProvider(settings,transport=forbidden).embed(['synthetic'],text_type='query',before_attempt=lambda:None)


def test_limits_and_model_spaces():
    calls=[]
    provider=DashScopeProvider(config(embedding_max_input_chars=2),transport=lambda *_:calls.append(1))
    with pytest.raises(EmbeddingError):provider.embed(['too long'],text_type='document',before_attempt=lambda:None)
    assert not calls
    settings=config()
    assert space_for(settings).id!=space_for(settings.model_copy(update={'embedding_model_revision':'v2'})).id
    with pytest.raises(ValueError):config(embedding_dimension=768)
    with pytest.raises(ValueError):Settings(_env_file=None,db_password='unit-test-only-password',embedding_provider='deterministic')


def test_absolute_http_timeout(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    class Slow:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        @asynccontextmanager
        async def stream(self,*args,**kwargs):
            await asyncio.sleep(1)
            yield None
    monkeypatch.setattr('backend.v2.services.embedding_provider.httpx2.AsyncClient',Slow)
    with pytest.raises(EmbeddingError) as error:DashScopeProvider(config(embedding_timeout_seconds=0.1))._http(['synthetic'],'document')
    assert error.value.code=='embedding_timeout' and error.value.retryable
