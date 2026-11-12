"""Seed only the isolated synthetic demo over loopback HTTP; never print credentials."""
import http.client
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import secrets
import time

ORIGIN='https://qwen.dsassistant.cn'
ROOT=Path('/var/lib/ds-v2-parser/qwen-demo')


class Client:
    def __init__(self):self.cookies={};self.csrf=None
    def request(self,method,path,body=None,*,expected=200,upload=None):
        headers={'Origin':ORIGIN,'X-Forwarded-Proto':'https'}
        if self.cookies:headers['Cookie']='; '.join(k+'='+v for k,v in self.cookies.items())
        if self.csrf:headers['X-CSRF-Token']=self.csrf
        if upload is not None:
            boundary=secrets.token_hex(16)
            body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode()
                +upload+f'\r\n--{boundary}--\r\n'.encode())
            headers['Content-Type']='multipart/form-data; boundary='+boundary
        elif body is not None:
            body=json.dumps(body).encode();headers['Content-Type']='application/json'
        connection=http.client.HTTPConnection('127.0.0.1',18001,timeout=40)
        try:
            connection.request(method,'/api/v2'+path,body=body,headers=headers)
            response=connection.getresponse();raw=response.read()
            for key,value in response.getheaders():
                if key.lower()=='set-cookie':
                    parsed=SimpleCookie();parsed.load(value)
                    for name,morsel in parsed.items():
                        if morsel.value:self.cookies[name]=morsel.value
                        else:self.cookies.pop(name,None)
            data=json.loads(raw) if raw else {}
            if response.status!=expected:raise RuntimeError('HTTP_%s_%s'%(response.status,data.get('error',{}).get('code','unknown')))
            return data
        finally:connection.close()
    def refresh_csrf(self):self.csrf=self.request('GET','/auth/csrf')['csrf_token']


def main():
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    credentials=ROOT/'credentials.json'
    accounts=[{'email':'synthetic-'+secrets.token_hex(8)+'@example.org','password':secrets.token_urlsafe(32)+'Aa1!'} for _ in range(2)]
    fd=os.open(credentials,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as out:json.dump({'accounts':accounts,'status':'initializing'},out);out.flush();os.fsync(out.fileno())
    clients=[]
    for account in accounts:
        client=Client();client.refresh_csrf();client.request('POST','/auth/register',account,expected=201)
        client.request('POST','/auth/login',account);client.refresh_csrf();clients.append(client)
    client=clients[0]
    kb=client.request('POST','/knowledge-bases',{'name':'Synthetic Qwen Demo','description':'原创合成测试资料'},expected=201)['knowledge_base']
    prefix='/knowledge-bases/'+kb['id']
    for purpose in ('embedding','reranking','generation'):client.request('POST',prefix+'/cloud-consents/'+purpose)
    text=('# 原创合成示例\nAVL树是一种二叉搜索树，每个节点的左右子树高度差绝对值不超过1。\n'
          '栈是后进先出，队列是先进先出。图的广度优先遍历通常用队列。\n'
          '插入排序逐一把元素插入已排序前缀，最坏时间复杂度为平方级。\n').encode()
    doc=client.request('POST',prefix+'/documents',expected=201,upload=text)['document']
    path=prefix+'/documents/'+doc['id']
    for _ in range(90):
        current=client.request('GET',path)['document']
        if current['status']=='parsed':break
        if current['status']=='failed':raise RuntimeError('PARSING_FAILED')
        time.sleep(1)
    else:raise RuntimeError('PARSING_TIMEOUT')
    client.request('POST',path+'/embedding',{'allow_cloud':True},expected=202)
    for _ in range(120):
        current=client.request('GET',path)['document']
        if current['status']=='ready':break
        if current['status']=='index_failed':raise RuntimeError('INDEXING_FAILED')
        time.sleep(1)
    else:raise RuntimeError('INDEXING_TIMEOUT')
    result=client.request('POST','/rag/ask',{'query':'AVL树的平衡条件是什么？','knowledge_base_ids':[kb['id']],
        'retrieval_mode':'hybrid','rerank':'required','allow_cloud':True,'allow_cloud_rerank':True,'allow_cloud_generation':True})
    if result.get('status')!='answered' or '[S1]' not in (result.get('answer') or '') or not any(s['citation_id']=='[S1]' for s in result.get('sources',[])):
        raise RuntimeError('RAG_VALIDATION_FAILED')
    with credentials.open('w') as out:
        json.dump({'accounts':accounts,'knowledge_base_id':kb['id'],'document_id':doc['id'],'status':'ready'},out)
        out.flush();os.fsync(out.fileno())
    print('SYNTHETIC_READY',kb['id'],doc['id'],'MODEL',result.get('generation_model'))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('SEED_FAILED',str(error) if isinstance(error,RuntimeError) else type(error).__name__)
        raise SystemExit(1) from None
