"""One-command offline acceptance; all subprocesses are fail-fast and unpaid."""
import os,subprocess,sys
from backend.v2.core.config import REPOSITORY_ROOT


def main():
    env=os.environ.copy();env['DS_V2_RUN_DB_TESTS']='1'
    commands=[['-m','pip','check'],['-m','alembic','-c','backend/v2/alembic.ini','upgrade','head'],
        ['-m','alembic','-c','backend/v2/alembic.ini','check'],['-m','pytest','backend/v2/tests','-q']]
    for name in ('http_smoke','knowledge_base_http_smoke','documents_http_smoke','ingestion_http_smoke','embedding_http_smoke','retrieval_http_smoke','context_http_smoke','rag_http_smoke'):
        commands.append(['-m','backend.v2.tests.'+name])
    for command in commands:
        print('Acceptance:', ' '.join(command),flush=True)
        subprocess.run([sys.executable,*command],cwd=REPOSITORY_ROOT,env=env,check=True)
    print('OFFLINE_ACCEPTANCE_PASS (no paid API calls)')


if __name__=='__main__':main()
