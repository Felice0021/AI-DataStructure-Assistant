import collections
import hashlib
import http.client
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import secrets
import tempfile
import time

ROOT = Path('/var/lib/ds-v2-parser/qwen-demo')
SOURCE = Path('/opt/ds-v2-qa/qwen-demo/knowledge_base/ds_chunks.jsonl')
EXPECTED = 'e338116ac715055d440a9cc86bc8ae2f6b2de1e19d59cece78a480c2b97a3e28'
ORIGIN = 'https://qwen.dsassistant.cn'
STATE = ROOT / 'course-import-state.json'

def save(path, obj):
    fd, name = tempfile.mkstemp(dir=ROOT, prefix='.course-state-')
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

class Client:
    def __init__(self): self.cookies = {}; self.csrf = None
    def req(self, method, path, data=None, upload=None):
        headers = {'Origin': ORIGIN, 'X-Forwarded-Proto': 'https'}
        if self.cookies: headers['Cookie'] = '; '.join(k+'='+v for k,v in self.cookies.items())
        if self.csrf: headers['X-CSRF-Token'] = self.csrf
        if upload:
            filename, content = upload
            boundary = secrets.token_hex(16)
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: text/plain\r\n\r\n'.encode() + content + f'\r\n--{boundary}--\r\n'.encode())
            headers['Content-Type'] = 'multipart/form-data; boundary='+boundary
        elif data is not None:
            data = json.dumps(data, ensure_ascii=False).encode(); headers['Content-Type'] = 'application/json'
        conn = http.client.HTTPConnection('127.0.0.1', 18001, timeout=120)
        try:
            conn.request(method, '/api/v2'+path, body=data, headers=headers)
            response = conn.getresponse(); raw = response.read()
            for k,v in response.getheaders():
                if k.lower() == 'set-cookie':
                    cookie = SimpleCookie(); cookie.load(v)
                    for key,m in cookie.items():
                        if m.value: self.cookies[key] = m.value
                        else: self.cookies.pop(key, None)
            body = json.loads(raw) if raw else {}
            return response.status, body
        finally: conn.close()
    def ok(self, method, path, data=None, upload=None, expected=200):
        status, body = self.req(method, path, data, upload)
        if status != expected: raise RuntimeError(f'{method} {path.split("?")[0]} HTTP {status} {body.get("error",{}).get("code", "unknown")}')
        return body
    def login(self, account):
        self.csrf = self.ok('GET', '/auth/csrf')['csrf_token']
        self.ok('POST', '/auth/login', account)
        self.csrf = self.ok('GET', '/auth/csrf')['csrf_token']

def main():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED: raise RuntimeError('SOURCE_HASH_MISMATCH')
    rows = [json.loads(x) for x in raw.decode('utf8').splitlines() if x.strip()]
    if len(rows) != 1010 or len({r['chunk_id'] for r in rows}) != 1010: raise RuntimeError('SOURCE_COUNT_OR_ID_MISMATCH')
    grouped = collections.OrderedDict()
    for row in rows: grouped.setdefault(row['chapter'], []).append(row)
    if len(grouped) != 10: raise RuntimeError('CHAPTER_COUNT_MISMATCH')
    creds = json.loads((ROOT/'credentials.json').read_text())
    client = Client(); client.login(creds['accounts'][0])
    state = json.loads(STATE.read_text()) if STATE.exists() else {'source_sha256': EXPECTED, 'source_count': len(rows), 'documents': {}}
    if state['source_sha256'] != EXPECTED: raise RuntimeError('STATE_SOURCE_MISMATCH')
    if 'kb' not in state:
        all_kb = client.ok('GET', '/knowledge-bases?limit=100')['items']
        matches = [kb for kb in all_kb if kb['name'] == 'V1 课程知识库 Qwen 演示']
        if len(matches) > 1: raise RuntimeError('AMBIGUOUS_KB')
        kb = matches[0] if matches else client.ok('POST', '/knowledge-bases', {'name':'V1 课程知识库 Qwen 演示','description':'V1 课程资料，独立真实模型索引'}, expected=201)['knowledge_base']
        state['kb'] = kb['id']; save(STATE, state)
    prefix = '/knowledge-bases/'+state['kb']
    for purpose in ('embedding','reranking','generation'): client.ok('POST', prefix+'/cloud-consents/'+purpose)
    mapping = []
    for number,(chapter, group) in enumerate(grouped.items(), 1):
        filename = f'v1-course-chapter-{number:02d}.txt'
        data = '\n\n'.join('# V1:'+r['chunk_id']+'\n'+json.dumps({k:r[k] for k in ('chunk_id','chapter','section','source_file','page','content_type')},ensure_ascii=False)+'\n'+r['text'] for r in group).encode()
        digest = hashlib.sha256(data).hexdigest()
        mapping += [{'v1_id':r['chunk_id'],'chapter_document':filename,'source_file':r['source_file'],'page':r['page']} for r in group]
        docs = client.ok('GET', prefix+'/documents?limit=100')['items']
        found = [d for d in docs if d['original_filename'] == filename]
        if len(found)>1 or (found and found[0]['sha256'] != digest): raise RuntimeError('DOCUMENT_COLLISION')
        doc = found[0] if found else client.ok('POST',prefix+'/documents',upload=(filename,data),expected=201)['document']
        state['documents'][filename] = {'id':doc['id'],'v1_count':len(group),'sha256':digest}
        save(STATE,state); save(ROOT/'course-source-mapping.json',mapping)
        path = prefix+'/documents/'+doc['id']
        deadline = time.monotonic()+300
        while time.monotonic()<deadline:
            doc=client.ok('GET',path)['document']
            if doc['status'] in ('parsed','ready','failed','index_failed'): break
            time.sleep(2)
        if doc['status'] in ('failed','index_failed'): raise RuntimeError('DOCUMENT_FAILED '+filename+' '+doc['status'])
        if doc['status']=='parsed': client.ok('POST',path+'/embedding',{'allow_cloud':True},expected=202)
        deadline = time.monotonic()+600
        while time.monotonic()<deadline:
            doc=client.ok('GET',path)['document']
            if doc['status'] in ('ready','failed','index_failed'): break
            time.sleep(3)
        if doc['status']!='ready': raise RuntimeError('INDEX_NOT_READY '+filename+' '+doc['status'])
        state['documents'][filename]['status']='ready'; save(STATE,state)
        print('READY',number,'source_records',len(group),flush=True)
    print('IMPORT_READY',state['kb'],'documents',len(state['documents']),'source_records',len(rows),flush=True)

if __name__ == '__main__':
    try: main()
    except Exception as error:
        print('IMPORT_STOPPED', type(error).__name__, str(error) if isinstance(error,RuntimeError) else '', flush=True)
        raise SystemExit(1) from None
