"""Safe local startup/status; never writes or prints credentials."""
import argparse,json,os,subprocess,sys
from backend.v2.core.config import Settings,REPOSITORY_ROOT


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['status','api','parser','embedding']);p.add_argument('--test-providers',action='store_true');a=p.parse_args()
    env=os.environ.copy()
    if a.test_providers:
        env.update({'DS_V2_ENVIRONMENT':'development','DS_V2_ALLOW_INSECURE_LOOPBACK':'true',
            'DS_V2_ALLOWED_ORIGINS':json.dumps(['http://127.0.0.1:5173','http://127.0.0.1:8001'])})
        for name in ('EMBEDDING','RERANK','GENERATION'):
            env['DS_V2_'+name+'_PROVIDER']='deterministic';env['DS_V2_'+name+'_ALLOW_TEST_PROVIDER']='true';env['DS_V2_'+name+'_CLOUD_ENABLED']='false'
    if a.action=='status':
        s=Settings();print(json.dumps({'python':sys.version.split()[0],'generation_model':s.generation_model,
            'cloud_enabled':{k:getattr(s,k+'_cloud_enabled') for k in ('embedding','rerank','generation')},
            'key_configured':{k:bool(getattr(s,k+'_api_key')) for k in ('embedding','rerank','generation')},'parser_backend':s.parser_backend}))
        return
    module={'api':'backend.v2.main','parser':'backend.v2.worker','embedding':'backend.v2.embedding_worker'}[a.action]
    subprocess.run([sys.executable,'-m',module],cwd=REPOSITORY_ROOT,env=env,check=True)


if __name__=='__main__':main()
