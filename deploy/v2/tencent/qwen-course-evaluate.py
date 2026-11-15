"""Run real course QA against the isolated HTTPS service; save answers privately."""
import importlib.util
import json
from pathlib import Path
import re
import time

ROOT=Path('/var/lib/ds-v2-parser/qwen-demo')
spec=importlib.util.spec_from_file_location('course_import',ROOT/'course-import.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def main():
    state=json.loads((ROOT/'course-import-state.json').read_text())
    accounts=json.loads((ROOT/'credentials.json').read_text())['accounts']
    client=module.Client();client.login(accounts[0]);kb=state['kb']
    records=[]
    searches=[]
    for mode in ('bm25','dense','hybrid'):
        start=time.monotonic()
        status,body=client.req('POST','/retrieval/search',{'query':'栈与队列有什么区别？','knowledge_base_ids':[kb],'mode':mode,'top_k':5,'allow_cloud':mode!='bm25'})
        searches.append({'mode':mode,'http':status,'count':len(body.get('results',[])),'elapsed_ms':round((time.monotonic()-start)*1000),'code':body.get('error',{}).get('code')})
    queries=[('concept','数据结构的逻辑结构和存储结构有什么区别？','qa'),('stack','栈的基本操作以及后进先出的特点是什么？','qa'),('queue','循环队列如何判断队满？','qa'),('tree','二叉树的前序和中序遍历有何区别？','qa'),('avl','AVL树的平衡条件是什么？','qa'),('graph','广度优先遍历与深度优先遍历有什么区别？','qa'),('graph_algorithm','Dijkstra算法的适用条件是什么？','qa'),('sort','快速排序的基本思想和时间复杂度是什么？','qa'),('sort_stability','哪些排序算法是稳定的？','qa'),('exercise','依次入栈A、B、C后连续出栈，出栈顺序是什么？','exercise'),('code','用伪代码说明二叉树前序遍历的实现思路。','code'),('cross','如何结合队列和二叉树实现层序遍历？','qa'),('refusal','unmatchedzzzzz','qa')]
    for name,query,answer_mode in queries:
        payload={'query':query,'knowledge_base_ids':[kb],'retrieval_mode':'bm25' if name=='refusal' else 'hybrid','answer_mode':answer_mode,'rerank':'off' if name=='refusal' else 'required','allow_cloud':name!='refusal','allow_cloud_rerank':name!='refusal','allow_cloud_generation':True}
        start=time.monotonic()
        status,body=client.req('POST','/rag/ask',payload)
        answer=body.get('answer') or ''
        cited=set(re.findall(r'\[S\d+\]',answer)); sources=body.get('sources',[])
        ids={s.get('citation_id') for s in sources}
        record={'name':name,'question':query,'http':status,'status':body.get('status'),'reason':body.get('reason'),
                'error_code':body.get('error',{}).get('code'),'elapsed_ms':round((time.monotonic()-start)*1000),
                'model':body.get('generation_model'),'rerank_applied':body.get('rerank_applied'),
                'citations_valid':bool(cited) and cited.issubset(ids) and all(s.get('knowledge_base_id')==kb for s in sources),
                'internal_metadata_present':any(x in answer for x in ('chunk_id','source_file','# V1:')),
                'answer':answer,'sources':sources}
        records.append(record);module.save(ROOT/'course-evaluation.json',{'knowledge_base_id':kb,'searches':searches,'questions':records})
        print('CASE',name,'HTTP',status,'STATUS',record['status'],'CITATIONS',record['citations_valid'],'META',record['internal_metadata_present'],'MS',record['elapsed_ms'],flush=True)
    other=module.Client();other.login(accounts[1]);status,_=other.req('GET','/knowledge-bases/'+kb)
    print('SEARCHES',json.dumps(searches,ensure_ascii=False),'CROSS_USER_HTTP',status,flush=True)

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('EVALUATION_STOPPED',type(e).__name__,str(e) if isinstance(e,RuntimeError) else '',flush=True)
        raise SystemExit(1) from None
