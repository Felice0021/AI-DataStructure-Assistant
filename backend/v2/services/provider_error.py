"""Extract a small, fixed set of provider error labels without logging responses."""
import json

ALLOWED={'InvalidApiKey','InvalidApiKeyError','AccessDenied','AccessDeniedException','Forbidden',
         'Arrearage','QuotaExceeded','AllocationQuota.FreeTierOnly','ModelNotExist','ModelNotFound',
         'InvalidParameter','Throttling','ServiceUnavailable'}


async def safe_error_code(response):
    raw=bytearray()
    try:
        async for chunk in response.aiter_raw(chunk_size=4096):
            raw.extend(chunk)
            if len(raw)>16384:return 'other'
        payload=json.loads(raw)
        if not isinstance(payload,dict):return 'other'
        error=payload.get('error')
        code=error.get('code') if isinstance(error,dict) else payload.get('code')
        return code if isinstance(code,str) and code in ALLOWED else 'other'
    except (AttributeError,ValueError,UnicodeError,TypeError):return 'other'
