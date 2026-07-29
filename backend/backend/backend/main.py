from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers.health import router as health_router
from backend.routers.ask import router as ask_router
from backend.config import get_settings

settings = get_settings()

app = FastAPI(title="数据结构课程智能助教", version="1.0.0")

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
    return {"message": "智能助教API", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )