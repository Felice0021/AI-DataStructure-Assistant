"""Real OpenAI-compatible Qwen SSE adapter; shares the existing Guard/call budget."""
import asyncio
from contextlib import nullcontext
import time
import httpx2
from backend.v2.services.generation_provider import Completion,GenerationError
from backend.v2.services.retrieval_service import capacity
from backend.v2.services.stream_decode import SSEDecoder,AnswerPrefix,StreamDecodeError,strict_json


async def http_events(provider,messages,check_cancel):
    s=provider.settings
    async with httpx2.AsyncClient(timeout=s.generation_timeout_seconds,trust_env=False,follow_redirects=False) as client:
        async with client.stream('POST',s.generation_endpoint,headers={
            'Authorization':'Bearer '+s.generation_api_key.get_secret_value(),'Accept':'text/event-stream','Accept-Encoding':'identity'},json={
            'model':provider.model,'messages':messages,'temperature':s.generation_temperature,
            'max_tokens':s.generation_max_output_tokens,'stream':True,'stream_options':{'include_usage':True},
            'enable_thinking':False,'response_format':{'type':'json_object'}}) as response:
            status=response.status_code
            if status!=200:
                code='generation_rate_limited' if status==429 else 'generation_model_unavailable' if status==404 else 'generation_parameter_error' if status in {400,422} else 'generation_http_error'
                raise GenerationError(code,status in {408,429,500,502,503,504})
            if (response.headers.get('content-encoding','identity') not in {'','identity'}
                or response.headers.get('content-type','').split(';')[0].strip()!='text/event-stream'):
                raise GenerationError('generation_response_encoding')
            decoder=SSEDecoder()
            async for raw in response.aiter_raw(): # no 16KiB aggregation: forward actual arrivals
                check_cancel()
                for event in decoder.feed(raw):yield event
            for event in decoder.feed(b'',final=True):yield event


async def collect(provider,messages,on_delta,check_cancel,ticket):
    s=provider.settings;prefix=AnswerPrefix(s.generation_max_output_bytes)
    stopped=False;done=False;count=0
    source=provider.stream_transport(messages) if provider.stream_transport is not None else http_events(provider,messages,check_cancel)
    try:
        async for raw in source:
            check_cancel();count+=1
            if count>8192:raise GenerationError('generation_response_limit')
            if done:raise GenerationError('generation_invalid_response')
            if raw=='[DONE]':done=True;break
            payload=strict_json(raw)
            if not isinstance(payload,dict) or payload.get('error') or payload.get('model') not in {None,provider.model}:raise GenerationError('generation_invalid_response')
            usage=payload.get('usage')
            if usage is not None:
                if not isinstance(usage,dict):raise GenerationError('generation_invalid_response')
                for key in ('completion_tokens','prompt_tokens','total_tokens'):
                    if key in usage and (type(usage[key]) is not int or not 0<=usage[key]<=10000000):raise GenerationError('generation_invalid_response')
                if usage.get('completion_tokens',0)>s.generation_max_output_tokens:raise GenerationError('generation_output_limit')
                if ticket is not None:ticket.record(payload)
            choices=payload.get('choices')
            if choices==[] and usage is not None and stopped:continue
            if not isinstance(choices,list) or len(choices)!=1 or stopped:raise GenerationError('generation_invalid_response')
            choice=choices[0]
            if not isinstance(choice,dict) or type(choice.get('index')) is not int or choice['index']!=0:raise GenerationError('generation_invalid_response')
            delta=choice.get('delta');finish=choice.get('finish_reason')
            if not isinstance(delta,dict) or delta.get('role') not in {None,'assistant'} or any(delta.get(k) for k in ('tool_calls','function_call','refusal')):raise GenerationError('generation_invalid_response')
            part=delta.get('content')
            if part is not None:
                if not isinstance(part,str):raise GenerationError('generation_invalid_response')
                text=prefix.feed(part)
                if text:on_delta(text)
            if finish is not None:
                if finish!='stop':raise GenerationError('truncated_or_invalid_completion')
                stopped=True
        if not stopped or not done:raise GenerationError('generation_stream_incomplete')
        # Final JSON, exact fields and citations are still checked by the original RAG validator.
        strict_json(prefix.raw)
        return Completion(prefix.raw)
    finally:
        await source.aclose()


async def cancellable(provider,messages,on_delta,check_cancel,ticket):
    async def watch_cancel():
        while True:
            check_cancel();await asyncio.sleep(0.05)
    job=asyncio.create_task(collect(provider,messages,on_delta,check_cancel,ticket))
    watcher=asyncio.create_task(watch_cancel())
    try:
        async with asyncio.timeout(provider.settings.generation_timeout_seconds):
            finished,_=await asyncio.wait({job,watcher},return_when=asyncio.FIRST_COMPLETED)
            if watcher in finished:await watcher
            return await job
    finally:
        job.cancel();watcher.cancel()
        await asyncio.gather(job,watcher,return_exceptions=True)


def generate(provider,messages,*,before_attempt,on_delta,check_cancel):
    s=provider.settings
    if provider.stream_transport is None and provider.cloud_guard is None:raise GenerationError('generation_consent_not_configured')
    if provider.stream_transport is not None and not (s.environment=='development' and s.generation_allow_test_provider):raise GenerationError('test_transport_forbidden')
    if not (s.generation_cloud_enabled and s.generation_model_verified and s.generation_api_key):raise GenerationError('generation_not_configured')
    import json
    if len(json.dumps(messages,ensure_ascii=False).encode())>s.generation_max_input_bytes:raise GenerationError('generation_input_limit')
    for attempt in range(s.generation_retries+1):
        check_cancel();before_attempt();received=False
        def delta(text):
            nonlocal received
            received=True;on_delta(text)
        try:
            with capacity(provider.engine,s.generation_concurrency,namespace=174929):
                with provider.cloud_guard() if provider.stream_transport is None else nullcontext() as ticket:
                    return asyncio.run(cancellable(provider,messages,delta,check_cancel,ticket))
        except (TimeoutError,httpx2.TimeoutException):error=GenerationError('generation_timeout',True)
        except httpx2.RequestError:error=GenerationError('generation_unavailable',True)
        except (ValueError,UnicodeError,RecursionError,StreamDecodeError):error=GenerationError('generation_invalid_response')
        except GenerationError as caught:error=caught
        # Never join a restarted generation onto an already exposed draft.
        if received or not error.retryable or attempt==s.generation_retries:raise error from None
        until=time.monotonic()+s.generation_backoff_seconds*2**attempt
        while time.monotonic()<until:check_cancel();time.sleep(min(0.05,max(0,until-time.monotonic())))
