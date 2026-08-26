import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("cams.request")

class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        
        logger.info(
            f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s"
        )
        response.headers["X-Response-Time"] = f"{duration:.3f}s"
        return response