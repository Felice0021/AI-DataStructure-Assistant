import asyncio
import json
from backend.v2.services.provider_error import safe_error_code


class Response:
    def __init__(self,content):self.content=content
    async def aiter_raw(self,chunk_size):yield self.content


def test_provider_error_logging_is_allowlisted_and_bounded():
    assert asyncio.run(safe_error_code(Response(json.dumps({'error':{'code':'AccessDenied'}}).encode())))=='AccessDenied'
    assert asyncio.run(safe_error_code(Response(json.dumps({'code':'sk-do-not-log'}).encode())))=='other'
    assert asyncio.run(safe_error_code(Response(json.dumps({'message':'quota exceeded'}).encode())))=='quota_or_balance'
    assert asyncio.run(safe_error_code(Response(b'x'*20000)))=='other'
    assert asyncio.run(safe_error_code(Response(b'not json')))=='other'
