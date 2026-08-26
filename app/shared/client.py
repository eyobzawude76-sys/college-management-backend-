from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client = AsyncIOMotorClient(
    settings.MONGODB_URL,
    serverSelectionTimeoutMS=5000,
    retryWrites=True,
    maxPoolSize=50,
    minPoolSize=10,
)
db = client[settings.DATABASE_NAME]