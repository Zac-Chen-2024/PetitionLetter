from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.routers.projects import router as projects_router
from app.routers.writing import router as writing_router, router_v3 as writing_v3_router
from app.routers.provenance import router as provenance_router
from app.routers.data import router as data_router
from app.routers.analysis import router as analysis_router
from app.routers.arguments import router as arguments_router
from app.routers.extraction import router as extraction_router
from app.routers.documents import router as documents_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("[Startup] EB-1A Petition API starting...")
    print("[Startup] Ready to serve requests")
    yield
    print("[Shutdown] EB-1A Petition API shutting down...")


app = FastAPI(
    title="EB-1A Petition API",
    description="EB-1A / NIW Immigration Petition Letter Authoring System",
    version="2.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers (new frontend only)
app.include_router(projects_router)
app.include_router(writing_router)
app.include_router(writing_v3_router)
app.include_router(provenance_router)
app.include_router(data_router)
app.include_router(analysis_router)
app.include_router(arguments_router)
app.include_router(extraction_router)
app.include_router(documents_router)


# Global exception handler for unified error responses
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": str(exc),
            "detail": None,
        }
    )


@app.get("/")
def root():
    return {
        "name": "EB-1A Petition API",
        "version": "2.0.0",
        "routers": [
            "projects", "documents", "analysis", "extraction",
            "arguments", "writing-v2", "writing-v3", "provenance", "data"
        ]
    }


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
