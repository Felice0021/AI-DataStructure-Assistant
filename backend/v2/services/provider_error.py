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
        code=(error.get('code') if isinstance(error,dict) else None) or payload.get('code')
        if isinstance(code,str) and code in ALLOWED:return code
        # Emit only fixed labels; never emit arbitrary provider strings.
        lowered=bytes(raw).decode('utf-8','ignore').lower()
        for label,terms in [('quota_or_balance',('quota','balance','arrear','credit','free tier')),
                            ('region_or_workspace',('region','workspace')),
                            ('authentication',('api key','apikey','api_key','authentication','unauthorized')),
                            ('permission',('permission','accessdenied','access denied','forbidden','ip address')),
                            ('model',('model',))]:
            if any(term in lowered for term in terms):return label
        return 'other'
    except (AttributeError,ValueError,UnicodeError,TypeError):return 'other'
