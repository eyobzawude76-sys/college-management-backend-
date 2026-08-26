from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.shared.audit_service import log_activity
from app.shared.jwt import decode_token

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip logging for health checks and static files
        if request.url.path in ["/health", "/docs", "/openapi.json"] or request.method == "OPTIONS":
            return await call_next(request)

        response = await call_next(request)

        # Only log state-changing operations
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            user_id = None
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                payload = decode_token(token)
                if payload:
                    user_id = payload.get("sub")

            action_map = {
                "POST": "CREATE",
                "PUT": "UPDATE",
                "PATCH": "UPDATE",
                "DELETE": "DELETE"
            }

            entity_type = self._extract_entity_type(request.url.path)

            await log_activity(
                action=action_map.get(request.method, request.method),
                entity_type=entity_type,
                user_id=user_id,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                description=f"{request.method} {request.url.path}"
            )

        return response

    def _extract_entity_type(self, path: str) -> str:
        parts = path.strip("/").split("/")
        if len(parts) > 1:
            return parts[1]  # e.g., /users/123 -> users
        return "unknown"