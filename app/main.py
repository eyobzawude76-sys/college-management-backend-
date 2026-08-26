from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
# Uploads folder akka static files-tti tajaajiluu
if not os.path.exists("uploads"):
    os.makedirs("uploads")
from app.features.router import api_router
from app.config import settings
from app.shared.client import client
from app.shared.indexes import ensure_indexes
from app.shared.audit_middleware import AuditMiddleware
from app.shared.rate_limit import RateLimitMiddleware
from app.shared.security_headers import SecurityHeadersMiddleware
from app.shared.request_logger import RequestLoggerMiddleware
from app.core.exceptions import global_exception_handler
from app.core.exceptions import CAMSException

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ensure_indexes()
        print("Indexes ensured.")
    except Exception as e:
        print(f"Warning: Could not ensure indexes: {e}")
    yield
    client.close()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

@app.get("/")
async def root():
    return {"message": "welcome to collage Academic"}
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.add_exception_handler(CAMSException, global_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=100, window=60)
app.add_middleware(AuditMiddleware)
app.add_middleware(RequestLoggerMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "ok"}