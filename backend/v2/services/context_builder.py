"""Pure whole-chunk evidence selection. Returned text is DATA, never a prompt role."""
from collections import Counter
import json
import unicodedata


def safe_text(value):
    # Retain newlines/tabs, code, formulas and normal Unicode. Render hidden controls visibly.
    value=value.replace('\r\n','\n')
    return ''.join(f'\\u{ord(ch):04x}' if unicodedata.category(ch) in {'Cc','Cf','Cs'} and ch not in '\n\t' else ch for ch in value)


def encode(blocks):
    if not blocks:return ''
    text=json.dumps(blocks,ensure_ascii=False,separators=(',',':'))
    # Prevent HTML/XML-style escape-out even if a downstream viewer embeds JSON unsafely.
    return text.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026').replace('\u2028','\\u2028').replace('\u2029','\\u2029')


def build_context(candidates,settings,*,max_evidence,max_chars,token_budget):
    evidence,blocks,excluded=[],[],[]
    seen=set();per_document=Counter();prior={}
    for source in candidates:
        chunk_id=str(source['chunk_id']);document_id=source['document_id']
        reason=None
        content=safe_text(source['content'])
        if chunk_id in seen:reason='duplicate_chunk'
        seen.add(chunk_id)
        if reason is None and len(evidence)>=max_evidence:reason='evidence_limit'
        if reason is None and per_document[document_id]>=settings.context_per_document:reason='document_limit'
        if reason is None and not content.strip():reason='empty_content'
        if reason is None and len(content)>settings.context_max_chunk_chars:reason='chunk_limit'
        if reason is None:
            for previous in prior.get(document_id,[]):
                # Conservative near-duplicate: exact containment and >=90% length agreement.
                if min(len(previous),len(content))/max(len(previous),len(content))>=.9 and (content in previous or previous in content):
                    reason='overlapping_evidence';break
        citation=f'[S{len(evidence)+1}]'
        source_fields={k:str(source[k]) if k.endswith('_id') else source[k] for k in (
            'chunk_id','document_id','knowledge_base_id','source_filename','page_number','section_title','chunk_index')}
        for key in ('source_filename','section_title'):
            if source_fields[key] is not None:source_fields[key]=safe_text(source_fields[key])
        block={'citation_id':citation,'source':source_fields,'content':content}
        prospective=encode([*blocks,block])
        if reason is None and (len(prospective)>max_chars or len(prospective.encode())>token_budget):reason='context_budget'
        if reason:
            excluded.append({'chunk_id':chunk_id,'reason':reason});continue
        item={**source,**{k:v for k,v in source_fields.items() if k in {'source_filename','section_title'}},
              'content':content,'citation_id':citation,'sanitized':content!=source['content'] or any(source_fields[k]!=source[k] for k in ('source_filename','section_title')),'truncated':False}
        evidence.append(item);blocks.append(block);per_document[document_id]+=1;prior.setdefault(document_id,[]).append(content)
    text=encode(blocks)
    return {'context_text':text,'evidence':evidence,'excluded':excluded,'used_chars':len(text),
        'estimated_tokens':len(text.encode()),'token_estimate_method':'utf8_bytes_conservative_not_tokenizer',
        'context_format':'json_evidence_v1','trust_boundary':'untrusted_reference_data'}
