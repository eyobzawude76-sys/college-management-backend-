import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def test_db():
    client = AsyncIOMotorClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
    try:
        await client.server_info()
        print("Successfully connected to MongoDB!")
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")

asyncio.run(test_db())
