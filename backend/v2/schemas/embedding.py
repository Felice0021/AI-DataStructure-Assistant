from backend.v2.schemas.ingestion import JobResponse
from pydantic import BaseModel, ConfigDict


class IndexRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    allow_cloud: bool=False


class IndexJobResponse(JobResponse):
    space_id: str
    index_revision: int
    expected_chunks: int
    api_calls: int
    max_api_calls: int


class IndexJobEnvelope(BaseModel):
    job: IndexJobResponse
