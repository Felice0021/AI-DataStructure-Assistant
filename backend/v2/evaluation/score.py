"""Only explicitly human-approved labels enter quality metrics. No cloud calls."""
import argparse,json,math
from pathlib import Path


def evaluate(cases,runs):
    approved=[c for c in cases if c.get('annotation_status')=='human_approved' and c.get('reviewer') and c.get('reviewed_at') and type(c.get('evidence_sufficient')) is bool]
    by_id={r['id']:r for r in runs};metrics={};n=0
    for case in approved:
        if case['id'] not in by_id:continue
        run=by_id[case['id']]
        if run.get('provider_kind')=='deterministic':continue
        relevance=case.get('relevance',{})
        positives={k for k,v in relevance.items() if v>0};ranked=list(dict.fromkeys(run.get('retrieved_chunk_ids',[])))
        values={}
        if positives:
            values['recall_at_5']=len(set(ranked[:5])&positives)/len(positives)
            values['mrr_at_10']=next((1/(i+1) for i,k in enumerate(ranked[:10]) if k in positives),0)
            dcg=sum((2**relevance.get(k,0)-1)/math.log2(i+2) for i,k in enumerate(ranked[:5]))
            ideal=sum((2**v-1)/math.log2(i+2) for i,v in enumerate(sorted(relevance.values(),reverse=True)[:5]))
            values['ndcg_at_5']=dcg/ideal if ideal else 0
        if 'refused' in run:values['refusal_accuracy']=float(run['refused']==(not case['evidence_sufficient']))
        if 'citation_validity' in run:values['citation_validity']=run['citation_validity']
        # Faithfulness is a human score, never inferred from valid citation IDs.
        if run.get('faithfulness_reviewed_by') and 'citation_faithfulness' in run:values['citation_faithfulness']=run['citation_faithfulness']
        for k,v in values.items():metrics.setdefault(k,[]).append(v)
        n+=1
    return {'approved_cases':len(approved),'evaluated_cases':n,'pending_cases':len(cases)-len(approved),
        'quality_metrics':{k:sum(v)/len(v) for k,v in metrics.items()},
        'engineering_only':{'runs':len(runs),'latency_ms':[r.get('latency_ms') for r in runs if 'latency_ms' in r],
            'api_calls':sum(r.get('api_calls',0) for r in runs),'cost_cny':sum(r.get('cost_cny',0) for r in runs)},
        'warning':'No approved ground truth: quality metrics intentionally empty' if not approved else 'Only human-approved labels included'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--cases',type=Path,default=Path(__file__).with_name('cases.jsonl'));p.add_argument('--runs',type=Path)
    a=p.parse_args();cases=[json.loads(l) for l in a.cases.read_text().splitlines() if l.strip()]
    runs=[json.loads(l) for l in a.runs.read_text().splitlines() if l.strip()] if a.runs else []
    print(json.dumps(evaluate(cases,runs),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
