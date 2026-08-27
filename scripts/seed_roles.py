import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

# Password Hash Setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

async def seed_users():
    # MongoDB Connection
    client = AsyncIOMotorClient("mongodb+srv://eyobzawude76_db_user:mySecret123@cluster0.uo74prq.mongodb.net/college_academic_db?retryWrites=true&w=majority")
    db = client["college_academic_db"]
    users_collection = db["users"]

    # Users uumaman
    users = [
        {
            "fullName": "System Admin",
            "email": "admin@college.edu", 
            "username": "admin",
            "passwordHash": hash_password("Admin@1234"),
            "role": "admin",
            "status": "approved",
            "isDeleted": False
        },
        {
            "fullName": "Academic Committee",
            "email": "committee@college.edu",
            "username": "committee",
            "passwordHash": hash_password("Committee@1234"),
            "role": "committee",
            "status": "approved",
            "isDeleted": False
        },
        {
            "fullName": "Record Officer",
            "email": "record@college.edu",
            "username": "record_officer",
            "passwordHash": hash_password("Record@1234"),
            "role": "record_officer",
            "status": "approved",
            "isDeleted": False
        },
        {
            "fullName": "Promotion Officer",
            "email": "promotion@college.edu",
            "username": "promotion_officer",
            "passwordHash": hash_password("Promotion@1234"),
            "role": "promotion_officer",
            "status": "approved",
            "isDeleted": False
        }
    ]
    for user_data in users:
        # 1. Email YKN Username tiin user duraan jiru dhabamsiisi
        await users_collection.delete_many({
            "$or": [
                {"email": user_data["email"]},
                {"username": user_data["username"]}
            ]
        })
        
        # 2. User haaraa insert godhi
        await users_collection.insert_one(user_data)
        print(f"🔄 Haara'ee uumameera: {user_data['role']} ({user_data['email']})")


if __name__ == "__main__":
    asyncio.run(seed_users())