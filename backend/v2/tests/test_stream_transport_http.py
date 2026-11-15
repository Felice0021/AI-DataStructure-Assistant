"""Actual TCP/SSE with a controlled local model server, not a paid Qwen quality test."""
import json
import os
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
import httpx2
import uvicorn
from sqlalchemy import text
from backend.v2.main import create_app
from backend.v2.tests.test_conversation_stream import streaming,frames
from backend.v2.tests.test_ingestion import setup
from backend.v2.tests.test_retrieval import env
from backend.v2.tests.test_auth import csrf_headers
from backend.v2.services.generation_stream import http_events as real_http_events
from backend.v2.tests.test_generation_stream import event

pytestmark=[pytest.mark.integration,pytest.mark.skipif(os.getenv('DS_V2_RUN_DB_TESTS')!='1',reason='Isolated PostgreSQL')]


@pytest.fixture
def network(streaming,monkeypatch):
    e=streaming;release=threading.Event();closed=threading.Event();finished=threading.Event();calls=[]
    class Model(BaseHTTPRequestHandler):
        def log_message(self,*args):pass # no headers, credentials, prompts or generated text in logs
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert data['stream'] is True and data['response_format']=={'type':'json_object'}
            assert data['stream_options']=={'include_usage':True};calls.append(True)
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            self.connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            prefix='{"status":"answered","answer":"中文增量：Dijkstra 是最短路径算法。'
            first=('data: '+event(prefix)+'\r\n\r\n').encode()
            try:
                for start in range(0,len(first),3):self.wfile.write(first[start:start+3]);self.wfile.flush()
                until=time.monotonic()+10
                while not release.is_set():
                    if time.monotonic()>until:return
                    ready,_,_=select.select([self.connection],[],[],0.02)
                    if ready and self.connection.recv(1,socket.MSG_PEEK)==b'':closed.set();return
                tail=event(' [S1]","used_source_ids":["[S1]"]}')
                wire=''.join('data: '+x+'\n\n' for x in [tail,event('', 'stop'),json.dumps({'choices':[],'usage':{'prompt_tokens':40,'completion_tokens':20,'total_tokens':60}}),'[DONE]'])
                self.wfile.write(wire.encode());self.wfile.flush();finished.set()
            except OSError:closed.set()
    model=ThreadingHTTPServer(('127.0.0.1',0),Model);model.daemon_threads=True
    model_thread=threading.Thread(target=model.serve_forever,daemon=True);model_thread.start()
    # Test-only in-memory endpoint mutation. Settings still rejects non-official HTTP
    # endpoints at construction; no production URL/credential config is changed.
    e['settings'].generation_endpoint=f'http://127.0.0.1:{model.server_port}/mock-qwen'
    grant='/api/v2/knowledge-bases/'+e['kb']['id']+'/cloud-consents/generation'
    assert e['client'].post(grant,headers=csrf_headers(e['client'])).status_code==200
    monkeypatch.setattr('backend.v2.services.generation_stream.http_events',real_http_events)
    listen=socket.socket();listen.bind(('127.0.0.1',0));port=listen.getsockname()[1]
    base=f'http://127.0.0.1:{port}';e['settings'].allowed_origins.append(base)
    app=create_app(e['settings']);server=uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[listen]),daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started:
        assert thread.is_alive() and time.monotonic()<deadline
        time.sleep(0.01)
    client=httpx2.Client(base_url=base,cookies=dict(e['client'].cookies),headers={'Origin':base},timeout=10,trust_env=False)
    csrf=client.get('/api/v2/auth/csrf').json()['csrf_token']
    e.update(network=client,headers={'X-CSRF-Token':csrf},model_release=release,model_closed=closed,model_finished=finished,network_calls=calls)
    try:yield e
    finally:
        release.set();client.close();server.should_exit=True;thread.join(timeout=5)
        model.shutdown();model.server_close();model_thread.join(timeout=2);listen.close()
        assert not thread.is_alive()


def read_event(lines):
    data=[]
    for line in lines:
        if not line:
            if data:return json.loads('\n'.join(data))
        elif line.startswith('data: '):data.append(line[6:])
    raise AssertionError('Premature EOF')


def test_first_text_arrives_before_upstream_finishes_and_only_validated_pair_is_saved(network):
    e=network;c=e['network'];start=time.monotonic()
    with c.stream('POST',e['url']+'/ask-stream',json=e['data'],headers=e['headers']) as response:
        assert response.status_code==200
        lines=response.iter_lines();seen=[]
        while True:
            item=read_event(lines);seen.append(item)
            if item['type']=='draft':break
        draft_at=time.monotonic()-start
        assert not e['model_finished'].is_set() and not e['model_release'].is_set()
        assert '中文增量' in seen[-1]['payload']['text']
        with e['engine'].connect() as db:assert db.scalar(text('SELECT count(*) FROM messages'))==0
        e['model_release'].set()
        while item['type'] not in {'result','error'}:item=read_event(lines);seen.append(item)
        assert item['type']=='result',item
        assert item['payload']['result']['sources'][0]['citation_id']=='[S1]'
        assert draft_at<time.monotonic()-start
    assert e['model_finished'].is_set() and e['network_calls']==[True]
    with e['engine'].connect() as db:assert db.scalar(text('SELECT count(*) FROM messages'))==2
    assert c.get(e['url']+'/messages').json()['total']==2


def test_real_client_disconnect_closes_model_connection_and_retry_is_idempotent(network):
    e=network;c=e['network']
    with c.stream('POST',e['url']+'/ask-stream',json=e['data'],headers=e['headers']) as response:
        lines=response.iter_lines()
        while read_event(lines)['type']!='draft':pass
        # Close without ever releasing the model's completion barrier.
    assert e['model_closed'].wait(3), 'upstream HTTP connection remained open after disconnect'
    with e['engine'].connect() as db:assert db.scalar(text('SELECT count(*) FROM messages'))==0
    e['model_release'].set()
    final=frames(c.post(e['url']+'/ask-stream',json=e['data'],headers=e['headers']))
    assert final[-1]['type']=='result'
    replay=frames(c.post(e['url']+'/ask-stream',json=e['data'],headers=e['headers']))
    assert replay[-1]['payload']==final[-1]['payload'] and e['network_calls']==[True,True]
    assert c.get(e['url']+'/messages').json()['total']==2
