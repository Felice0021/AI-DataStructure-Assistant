from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path

from backend.routers.health import router as health_router
from backend.routers.ask import router as ask_router
from backend.config import get_settings
from backend.services.rag_service import RAGService
from backend.logging_config import get_logger

logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 60)
    logger.info(f"数据结构课程智能助教 v{settings.version}")
    logger.info(f"项目根目录: {Path(__file__).parent.parent}")
    logger.info("正在初始化RAG服务...")

    # 初始化RAG
    await RAGService.initialize()

    if RAGService.is_ready():
        logger.info(f"RAG初始化成功，共 {RAGService.get_chunk_count()} 个片段")
    else:
        logger.warning("RAG初始化失败，问答功能将不可用")

    logger.info("服务启动完成")
    logger.info("=" * 60)

    yield

    logger.info("后端服务关闭")


app = FastAPI(
    title="数据结构课程智能助教",
    version=settings.version,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(ask_router)


@app.get("/")
async def root():
    return {
        "message": "数据结构课程智能助教 API",
        "version": settings.version,
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )