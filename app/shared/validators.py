# app/utils/validators.py
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

def validate_object_id(id_str: str, field_name: str = "id") -> str:
    try:
        ObjectId(id_str)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} format"
        )
    return id_str