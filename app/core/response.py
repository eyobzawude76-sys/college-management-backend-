from typing import Any, Optional

def success_response(data: Any = None, message: str = "Success", meta: Optional[dict] = None):
    response = {"success": True, "message": message, "data": data}
    if meta:
        response["meta"] = meta
    return response

def paginated_response(data: Any, page: int, limit: int, total: int):
    return success_response(
        data=data,
        meta={"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}
    )