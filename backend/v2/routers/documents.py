from typing import Annotated
from urllib.parse import quote
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.v2.core.errors import AuthError
from backend.v2.dependencies.auth import require_active_user
from backend.v2.dependencies.database import get_session
from backend.v2.models import User
from backend.v2.schemas.auth import ErrorResponse
from backend.v2.schemas.document import DocumentEnvelope, DocumentList, DocumentResponse
from backend.v2.services import document_service as service
from backend.v2.services.file_validation import validate_filename

router = APIRouter(prefix="/api/v2/knowledge-bases/{kb_id}/documents", tags=["documents"],
                    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 408, 409, 413, 422, 429, 503)})
CurrentUser = Annotated[User, Depends(require_active_user)]
Database = Annotated[Session, Depends(get_session)]


def envelope(record):
    return DocumentEnvelope(document=DocumentResponse.model_validate(record))


@router.post("", status_code=201, response_model=DocumentEnvelope, openapi_extra={
    "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "additionalProperties": False, "required": ["file"],
        "properties": {"file": {"type": "string", "format": "binary"}},
    }}}},
})
async def upload_document(kb_id: UUID, request: Request, user: CurrentUser, session: Database):
    settings = request.app.state.settings
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        raise AuthError(422, "invalid_request", "One multipart file is required")
    limit = await run_in_threadpool(service.prepare_upload, session, user, kb_id, settings)
    consumed = 0

    async def bounded_receive():
        nonlocal consumed
        message = await request.receive()
        consumed += len(message.get("body", b""))
        if consumed > settings.upload_max_bytes + 64 * 1024:
            raise AuthError(413, "file_too_large", "Upload request exceeds limit")
        return message

    # Manual parsing after auth/CSRF/parent authorization; no eager FastAPI File parsing.
    bounded = Request(request.scope, receive=bounded_receive)
    form = None
    try:
        with anyio.fail_after(settings.upload_timeout_seconds):
            form = await bounded.form(max_files=1, max_fields=0, max_part_size=1024)
        if len(form.multi_items()) != 1 or not isinstance(form.get("file"), UploadFile):
            raise AuthError(422, "invalid_request", "One multipart file is required")
        file = form["file"]
        validate_filename(file.filename)
        return envelope(await run_in_threadpool(service.upload, session, user, kb_id, file, settings, limit))
    except HTTPException:
        raise AuthError(422, "invalid_request", "Invalid multipart upload") from None
    except TimeoutError:
        raise AuthError(408, "upload_timeout", "Upload timed out") from None
    except OSError:
        from backend.v2.services.file_storage import storage_unavailable
        raise storage_unavailable() from None
    finally:
        if form is not None:
            await form.close()
        # Releases locks even when multipart parsing/validation fails.
        await run_in_threadpool(session.rollback)


@router.get("", response_model=DocumentList)
def list_documents(kb_id: UUID, user: CurrentUser, session: Database,
                   limit: Annotated[int, Query(ge=1, le=100)] = 50,
                   offset: Annotated[int, Query(ge=0)] = 0):
    items, total = service.list_documents(session, user, kb_id, limit=limit, offset=offset)
    return DocumentList(items=[DocumentResponse.model_validate(r) for r in items], total=total, limit=limit, offset=offset)


@router.get("/{doc_id}", response_model=DocumentEnvelope)
def get_document(kb_id: UUID, doc_id: UUID, user: CurrentUser, session: Database):
    return envelope(service.get_document(session, user, kb_id, doc_id))


@router.get("/{doc_id}/download", response_class=StreamingResponse, responses={200: {"content": {"application/octet-stream": {}}}})
def download_document(kb_id: UUID, doc_id: UUID, request: Request, user: CurrentUser, session: Database):
    (name, _mime, size), stream = service.open_download(session, user, kb_id, doc_id, request.app.state.settings)

    def chunks():
        try:
            while chunk := stream.read(64 * 1024):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename=download; filename*=UTF-8''" + quote(name, safe=""),
        "Content-Length": str(size), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }, background=BackgroundTask(stream.close))


@router.delete("/{doc_id}", status_code=204)
def delete_document(kb_id: UUID, doc_id: UUID, request: Request, user: CurrentUser, session: Database):
    service.delete(session, user, kb_id, doc_id, request.app.state.settings)
    return Response(status_code=204)
