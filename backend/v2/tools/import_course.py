"""Read-only JSONL preview or admin-authorized derived-TXT import. Never embeds."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from uuid import UUID
from starlette.datastructures import UploadFile,Headers
from sqlalchemy import select
from backend.v2.core.config import Settings
from backend.v2.core.errors import AuthError
from backend.v2.db.session import build_engine,build_session_factory
from backend.v2.models import User,Document
from backend.v2.services import knowledge_base_service as knowledge,document_service,ingestion_service


def prepare(path):
    path=Path(path)
    if path.stat().st_size>8*1024*1024:raise ValueError('Course input too large')
    rows=[];seen=set()
    for line in path.read_text(encoding='utf8').splitlines():
        if not line.strip():continue
        row=json.loads(line)
        if not {'chunk_id','text','chapter','section','source_file','page','content_type'}<=row.keys():raise ValueError('Invalid source schema')
        identifier=row['chunk_id']
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identifier) or identifier in seen:raise ValueError('Invalid/duplicate source id')
        if not isinstance(row['text'],str) or not row['text'].strip():raise ValueError('Empty source')
        seen.add(identifier);rows.append(row)
    if not rows or len(rows)>10000:raise ValueError('Invalid source count')
    # Every source record remains verbatim inside a real UTF-8 text export, not a fake PDF.
    data='\n\n'.join('# V1:'+row['chunk_id']+'\n'+json.dumps({k:row[k] for k in ('chunk_id','chapter','section','source_file','page','content_type')},ensure_ascii=False)+'\n'+row['text'] for row in rows).encode()
    digest=hashlib.sha256(data).hexdigest()
    return data,{'source_records':len(rows),'bytes':len(data),'sha256':digest,'filename':'v1-course-'+digest[:16]+'.txt',
        'mapping':[{'legacy_chunk_id':r['chunk_id'],'section_title':'V1:'+r['chunk_id'],'original_source_file':r['source_file'],
            'original_page':r['page'],'content_hash':hashlib.sha256(r['text'].encode()).hexdigest()} for r in rows]}


def apply(session,user,kb_id,path,settings):
    knowledge.require_public_manager(user)
    kb=knowledge.get_writable(session,user,kb_id)
    if kb.visibility!='public':raise AuthError(403,'public_required','Public knowledge base required')
    data,manifest=prepare(path)
    existing=session.scalar(select(Document).where(Document.knowledge_base_id==kb_id,Document.sha256==manifest['sha256'],
        Document.original_filename==manifest['filename'],Document.deleted_at.is_(None)))
    if existing:
        if existing.status=='failed':ingestion_service.request_processing(session,user,kb_id,existing.id,settings)
        return existing,False,manifest
    file=UploadFile(BytesIO(data),filename=manifest['filename'],headers=Headers({'content-type':'text/plain'}))
    record=document_service.upload(session,user,kb_id,file,settings,settings.upload_max_bytes)
    return record,True,manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path',type=Path);parser.add_argument('--apply',action='store_true')
    parser.add_argument('--admin-email');parser.add_argument('--kb-id',type=UUID)
    parser.add_argument('--mapping-output',type=Path)
    args=parser.parse_args();data,manifest=prepare(args.path)
    if args.apply:
        if not args.admin_email or not args.kb_id:parser.error('--apply requires --admin-email and --kb-id')
        settings=Settings();engine=build_engine(settings)
        try:
            with build_session_factory(engine)() as session:
                user=session.scalar(select(User).where(User.email==args.admin_email))
                if user is None:raise ValueError('Administrator not found')
                record,created,manifest=apply(session,user,args.kb_id,args.path,settings)
                print(json.dumps({'document_id':str(record.id),'created':created,'status':record.status}))
        finally:engine.dispose()
    else:print(json.dumps({k:manifest[k] for k in ('source_records','bytes','sha256','filename')}))
    if args.mapping_output:
        # Exclusive output: cannot overwrite an existing review/mapping file.
        with args.mapping_output.open('x',encoding='utf8') as handle:json.dump(manifest['mapping'],handle,ensure_ascii=False,indent=2)


if __name__=='__main__':main()
