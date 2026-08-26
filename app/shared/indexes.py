from pymongo import ASCENDING
from app.database import students_collection

async def ensure_indexes():
    print("Ensuring indexes...")

    # 1. Index-oota dullooman/error fidan Drop gochuu
    old_indexes = ["student_id_1", "user_id_1"]
    for idx in old_indexes:
        try:
            await students_collection.drop_index(idx)
            print(f"Index {idx} drop ta'eera.")
        except Exception:
            pass

    # 2. Index 'student_id' sparse ta'e uumuu
    try:
        await students_collection.create_index(
            [("student_id", ASCENDING)],
            unique=True,
            sparse=True
        )
        print("Index student_id sparse ta'e uumameera!")
    except Exception as e:
        print(f"Error creating student_id index: {e}")

    # 3. Index 'user_id' sparse ta'e uumuu
    try:
        await students_collection.create_index(
            [("user_id", ASCENDING)],
            unique=True,
            sparse=True
        )
        print("Index user_id sparse ta'e uumameera!")
    except Exception as e:
        print(f"Error creating user_id index: {e}")