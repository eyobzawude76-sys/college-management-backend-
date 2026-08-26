from datetime import datetime
from app.database import audit_logs_collection
from typing import Optional

async def log_activity(
    action: str,
    entity_type: str,
    user_id: Optional[str],
    ip_address: Optional[str],
    user_agent: Optional[str],
    description: str
):
    log_entry = {
        "action": action,
        "entityType": entity_type,
        "userId": user_id,
        "ipAddress": ip_address,
        "userAgent": user_agent,
        "description": description,
        "timestamp": datetime.utcnow()
    }
    await audit_logs_collection.insert_one(log_entry)
