from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Query, Request

from backend.v2.routers.documents import CurrentUser, Database
from backend.v2.schemas.ingestion import ChunkList, ChunkResponse, IngestionRequest, JobEnvelope, JobResponse
from backend.v2.services import ingestion_service as service

router = APIRouter(prefix="/api/v2/knowledge-bases/{kb_id}/documents/{doc_id}", tags=["ingestion"])


@router.get("/ingestion", response_model=JobEnvelope)
def get_ingestion(kb_id: UUID, doc_id: UUID, user: CurrentUser, session: Database):
    return JobEnvelope(job=JobResponse.model_validate(service.get_job(session, user, kb_id, doc_id)))


@router.post("/ingestion", status_code=202, response_model=JobEnvelope)
def process_document(kb_id: UUID, doc_id: UUID, request: Request, user: CurrentUser, session: Database,
                     data: IngestionRequest = IngestionRequest()):
    job = service.request_processing(session, user, kb_id, doc_id, request.app.state.settings, data.reprocess)
    return JobEnvelope(job=JobResponse.model_validate(job))


@router.get("/chunks", response_model=ChunkList)
def list_chunks(kb_id: UUID, doc_id: UUID, user: CurrentUser, session: Database,
                limit: Annotated[int, Query(ge=1, le=100)] = 50,
                offset: Annotated[int, Query(ge=0)] = 0):
    chunks, total = service.list_chunks(session, user, kb_id, doc_id, limit, offset)
    return ChunkList(items=[ChunkResponse.model_validate(c) for c in chunks], total=total, limit=limit, offset=offset)
