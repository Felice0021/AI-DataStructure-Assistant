"""Explicit Qwen generation checks; random database and temporary files only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import UUID,uuid4
from unittest.mock import patch
from sqlalchemy import select

from backend.v2.core.config import Settings,REPOSITORY_ROOT
from backend.v2.db.session import build_session_factory
from backend.v2.models import CloudAudit,DocumentChunk
from backend.v2.services.verified_trees import calculate
from backend.v2.services.tree_rule_evidence import rule_supported
from backend.v2.services.generation_provider import QwenProvider
from backend.v2.tests.support import isolated_database
from backend.v2.tests.test_auth import local_settings,client_for,register,post,csrf_headers
from backend.v2.tests.test_ingestion import upload
from backend.v2.tests.test_discourse_continuity import FOUR
from backend.v2.tests.test_course_rotation_rules import LR
from backend.v2.tests.test_verified_partition import RULE as LOMUTO_RULE
from backend.v2.tools.import_course import prepare
from backend.v2.worker import run_once as parse_once
from backend.v2.embedding_worker import run_once as index_once

CONTROL=('AVL树是平衡二叉搜索树，每个结点左右高度差至多一。普通二叉搜索树只要求左小右大，不强制平衡。'
         'AVL通过旋转恢复高度平衡，旋转保持中序有序及键集合。\n'+LR+'\n'
         '红黑树也是自平衡二叉搜索树，用颜色约束和黑高限制高度；红结点不能有红孩子。'
         'AVL严格控制左右高度差，红黑树通过颜色和黑高维持较宽松的平衡。\n'+LOMUTO_RULE)
PARTITION='用数组 [3,1,2] 演示一次 Lomuto 分区，规定最后一个元素为基准，下标从 0 开始。'


def documents(kind,path,expected):
    if kind=='control':return [('self-authored-rules.txt',CONTROL.encode())],{'kind':'self_authored_control'}
    prepare(path)  # Reuse the original read-only source validation; never call --apply.
    raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected:raise ValueError('course_source_hash_mismatch')
    rows=[json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    chosen=[r for r in rows if re.search(r'AVL|LR|快速排序|Lomuto',r['text'],re.I)]
    if not chosen:raise ValueError('course_subset_empty')
    groups={}
    for row in chosen:groups.setdefault(row['chapter'],[]).append(row)
    result=[]
    for index,group in enumerate(groups.values(),1):
        data='\n\n'.join('# V1:'+r['chunk_id']+'\n'+json.dumps({k:r[k] for k in ('chunk_id','chapter','section','source_file','page','content_type')},ensure_ascii=False)+'\n'+r['text'] for r in group)
        result.append((f'v1-course-chapter-{index:02d}.txt',data.encode()))
    return result,{'kind':'existing_v1_course_subset','source_sha256':digest,'source_records':len(rows),
                   'selected_v1_ids':[r['chunk_id'] for r in chosen],
                   'named_lomuto_records':sum('lomuto' in r['text'].casefold() for r in chosen),
                   'red_black_records':sum('红黑树' in r['text'] for r in chosen)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-qwen',action='store_true')
    parser.add_argument('--v2-env-file',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--source',choices=['course','control'],required=True)
    parser.add_argument('--course-jsonl',type=Path)
    parser.add_argument('--expected-source-sha256')
    parser.add_argument('--scenario',action='append',choices=['four-round','ordinary-refusal','lomuto'])
    args=parser.parse_args()
    if not args.real_qwen:parser.error('Explicit --real-qwen required')
    if args.source=='course' and (not args.course_jsonl or not args.expected_source_sha256):
        parser.error('Course requires source path and independently verified SHA256')
    root=args.output_dir.resolve()
    if root==REPOSITORY_ROOT or REPOSITORY_ROOT in root.parents:parser.error('Private output must be outside checkout')
    root.mkdir(mode=0o700,parents=True,exist_ok=True);root.chmod(0o700)
    target=root/('refusal-'+args.source+'-'+uuid4().hex+'.json')
    report={'result':'NOT_RUN','cases':[],'human_quality':'NOT_SCORED','structure_owner':'server reference algorithm',
            'embedding':'isolated deterministic test space, not production Qwen vectors'}
    def save():
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as output:json.dump(report,output,ensure_ascii=False,indent=2)
    try:
        files,provenance=documents(args.source,args.course_jsonl,args.expected_source_sha256)
        report['provenance']=provenance
        source=Settings(_env_file=args.v2_env_file)
        if not source.generation_api_key:raise ValueError('missing_v2_generation_key')
        report['model']=source.generation_model
        with isolated_database() as (engine,base),tempfile.TemporaryDirectory(prefix='v2-refusal-') as tmp:
            config=local_settings(base,file_storage_root=Path(tmp).resolve()/'files',embedding_provider='deterministic',
                embedding_allow_test_provider=True,embedding_cloud_enabled=False,rerank_provider='disabled',rerank_cloud_enabled=False,
                generation_provider='qwen',generation_cloud_enabled=True,generation_model_verified=True,
                generation_api_key=source.generation_api_key,generation_model=source.generation_model,
                generation_endpoint=source.generation_endpoint,generation_timeout_seconds=source.generation_timeout_seconds,
                generation_retries=0,generation_validation_retries=1,generation_max_calls=2)
            factory=build_session_factory(engine);drafts=[];rule_checks=[];original=QwenProvider._http
            def observed(provider,messages):
                question=json.loads(messages[1]['content'])
                calc,_=calculate(question.get('resolved_question',question['text']))
                if calc:
                    blocks=json.loads(messages[2]['content'])['blocks']
                    rule_checks.append({b['citation_id']:rule_supported(calc,b['content']).kind for b in blocks})
                result=original(provider,messages);drafts.append(result['choices'][0]['message']['content']);return result
            with patch.object(QwenProvider,'_http',observed),client_for(config) as client:
                credentials,_=register(client);assert post(client,'login',credentials).status_code==200
                kb=client.post('/api/v2/knowledge-bases',json={'name':'isolated-refusal-'+uuid4().hex},headers=csrf_headers(client)).json()['knowledge_base']['id']
                assert client.post('/api/v2/knowledge-bases/'+kb+'/cloud-consents/generation',headers=csrf_headers(client)).status_code==200
                for filename,data in files:
                    upload({'client':client,'base':'/api/v2/knowledge-bases/'+kb+'/documents'},name=filename,data=data)
                    assert parse_once(factory,config) and index_once(factory,config)
                scenarios=[('four-round',FOUR),('ordinary-refusal',[FOUR[0],'unmatchedzzzzz',FOUR[1]]),('lomuto',[PARTITION])]
                for name,questions in scenarios:
                    if args.scenario and name not in args.scenario:continue
                    conv=client.post('/api/v2/conversations',json={'title':name},headers=csrf_headers(client)).json()['conversation']['id']
                    for index,query in enumerate(questions):
                        drafts.clear();rule_checks.clear();start=time.monotonic();request_id=str(uuid4())
                        payload={'query':query,'knowledge_base_ids':[kb],'request_id':request_id,
                                 'retrieval_mode':'bm25','rerank':'off','allow_cloud_generation':True}
                        response=client.post('/api/v2/conversations/'+conv+'/ask',json=payload,headers=csrf_headers(client));body=response.json()
                        items=client.get('/api/v2/conversations/'+conv+'/messages').json()['items']
                        saved=next((m for m in reversed(items) if m['role']=='assistant' and m['metadata_json'].get('request_id')==request_id),None)
                        resolved=saved['metadata_json']['context']['resolved_query'] if saved else None
                        expect_refusal=query=='unmatchedzzzzz' or args.source=='course' and (name=='lomuto' or name=='four-round' and index==3)
                        valid=response.status_code==200 and body.get('status')==('insufficient_evidence' if expect_refusal else 'answered')
                        if expect_refusal:
                            valid=valid and body.get('sources')==[] and body.get('reason') not in {'conversation_context_required','conversation_context_ambiguous','partition_conditions_required'}
                        else:
                            valid=valid and bool(body.get('sources'))
                            with factory() as db:
                                for entry in body.get('sources',[]):
                                    chunk=db.get(DocumentChunk,UUID(entry['chunk_id']))
                                    valid=valid and entry['knowledge_base_id']==kb and entry['citation_id'] in body['answer'] and chunk.content_hash==entry['content_hash']
                        if name=='four-round' and index==2:
                            calc,_=calculate(resolved or '')
                            with factory() as db:
                                supports={s['citation_id']:rule_supported(calc,db.get(DocumentChunk,UUID(s['chunk_id'])).content) for s in body.get('sources',[])} if calc else {}
                            valid=valid and calc is not None and body.get('answer')==calc.render(' '.join(supports),supports=supports)
                            valid=valid and calc.keys==(30,10,20) and calc.final['key']==20
                        if name=='four-round' and index==3:valid=valid and bool(resolved and resolved.startswith('比较 AVL 树 与 红黑树：'))
                        if name=='ordinary-refusal' and index==2:valid=valid and resolved=='AVL 树为什么需要旋转？'
                        if name=='lomuto' and args.source=='course':valid=valid and body.get('reason')=='partition_rule_evidence_required'
                        if name=='lomuto' and args.source=='control':valid=valid and '基准最终下标：1。' in body.get('answer','')
                        report['cases'].append({'scenario':name,'round':index+1,'question':query,'http_status':response.status_code,
                            'response':body,'resolved_query':resolved,'elapsed_ms':round((time.monotonic()-start)*1000),
                            'raw_drafts':list(drafts),'submitted_rule_kinds':list(rule_checks),'engineering_pass':bool(valid)})
                        save();print('CASE',name,index+1,'HTTP',response.status_code,'STATUS',body.get('status'),'REASON',body.get('reason'),'PASS',bool(valid),flush=True)
                        if response.status_code in {401,403,429,503}:raise ValueError('model_or_permission_blocked')
                with factory() as db:report['cloud_usage']=[r.details for r in db.scalars(select(CloudAudit).where(CloudAudit.purpose=='generation',CloudAudit.event=='succeeded'))]
                report['result']='PASS' if all(r['engineering_pass'] for r in report['cases']) else 'FAIL'
                save();print('TRANSCRIPT',target);return 0 if report['result']=='PASS' else 1
    except Exception as error:
        report['result']='BLOCKED';report['error_code']=getattr(error,'code',type(error).__name__);save()
        print('BLOCKED',report['error_code']);print('TRANSCRIPT',target);return 2


if __name__=='__main__':raise SystemExit(main())
