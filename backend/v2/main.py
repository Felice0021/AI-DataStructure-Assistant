from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from backend.v2.core.config import Settings, get_settings
from backend.v2.core.logging import configure_logging
from backend.v2.db.session import build_engine, build_session_factory
from backend.v2.routers.retrieval import router as retrieval_router
from backend.v2.routers.embedding import router as embedding_router
from backend.v2.routers.ingestion import router as ingestion_router
from backend.v2.routers.documents import router as document_router
from backend.v2.routers.health import router
from backend.v2.routers.auth import router as auth_router
from backend.v2.core.errors import AuthError
from backend.v2.routers.knowledge_bases import router as knowledge_base_router, admin_router

PRIVATE_API_PREFIXES = ("/api/v2/retrieval", "/api/v2/auth", "/api/v2/knowledge-bases", "/api/v2/admin/knowledge-bases")


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(settings)
        app.state.session_factory = build_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Data Structure Assistant V2", version="2.0.0", lifespan=lifespan,
        docs_url="/api/v2/docs", openapi_url="/api/v2/openapi.json", redoc_url=None,
    )
    app.include_router(router)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    app.include_router(auth_router)
    app.include_router(knowledge_base_router)
    app.include_router(admin_router)
    app.include_router(document_router)
    app.include_router(ingestion_router)
    app.include_router(embedding_router)
    app.include_router(retrieval_router)

    @app.middleware("http")
    async def auth_cache_control(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(PRIVATE_API_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, error: AuthError):
        return JSONResponse(status_code=error.status, content={"error": {"code": error.code, "message": error.message}}, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # FastAPI's default response includes input values, potentially passwords.
        errors = error.errors()
        code = "weak_password" if any(e["type"] == "weak_password" for e in errors) else "invalid_request"
        if code == "invalid_request" and any(e["loc"][-1] == "email" for e in errors):
            code = "invalid_email"
        return JSONResponse(status_code=422, content={"error": {"code": code, "message": "Invalid request"}})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        logging.getLogger(__name__).warning("Database request failed (%s)", type(error).__name__)
        return JSONResponse(status_code=503, content={"error": {"code": "service_unavailable", "message": "Service temporarily unavailable"}})

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception):
        logging.getLogger(__name__).error("Unhandled error (%s)", type(error).__name__)
        if request.url.path.startswith(PRIVATE_API_PREFIXES):
            return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Internal server error"}}, headers={"Cache-Control": "no-store"})
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.v2.main:create_app", factory=True, host="127.0.0.1", port=8001, proxy_headers=False, access_log=False)
