from bson import ObjectId
from datetime import datetime

def serialize_mongo_doc(doc: dict) -> dict:
    if not doc:
        return doc
    result = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, dict):
            result[k] = serialize_mongo_doc(v)
        elif isinstance(v, list):
            result[k] = [serialize_mongo_doc(i) if isinstance(i, dict) else str(i) if isinstance(i, ObjectId) else i for i in v]
        else:
            result[k] = v
    return result