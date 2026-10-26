import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.v2.dependencies.database import get_session
from backend.v2.schemas.health import DatabaseHealthResponse, HealthResponse

router = APIRouter(prefix="/api/v2/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/db", response_model=DatabaseHealthResponse,
    responses={503: {"model": DatabaseHealthResponse, "description": "Database unavailable"}},
)
def database_health(
    response: Response, session: Annotated[Session, Depends(get_session)],
) -> DatabaseHealthResponse:
    try:
        session.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError as error:
        # Avoid logging driver messages, SQL parameters, DSNs or tracebacks.
        logger.warning("Database health check failed (%s)", type(error).__name__)
        response.status_code = 503
        return DatabaseHealthResponse(status="unavailable", database="unavailable")
    return DatabaseHealthResponse(status="ok", database="ok")
