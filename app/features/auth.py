from datetime import datetime, timedelta
from typing import Optional
from bson import ObjectId
import jwt
from app.database import (
     users_collection,
       teachers_collection,
       departments_collection,
       module_assignments_collection,
       modules_collection,
    students_collection,
)
from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, HTTPException, status, Depends
from typing import Optional
from app.database import users_collection, refresh_tokens_collection
from app.shared.hashing import hash_password, verify_password
from app.core.security import (
    create_access_token,
    create_refresh_token_value,
    decode_token,
    create_refresh_token_payload,
    hash_token,
)
from app.config import settings
from app.shared.auth import get_current_active_user
from app.core.models import User, UserResponse
from app.core.constants import UserRole, UserStatus

# =========================================================
# SCHEMAS
# =========================================================

class RefreshToken(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    userId: str
    tokenHash: str
    expiresAt: datetime
    isRevoked: bool = False
    createdAt: datetime = Field(default_factory=datetime.utcnow)

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class LoginResponse(Token):
    user: dict

class TokenRefresh(BaseModel):
    refresh_token: str

class UserBase(BaseModel):
    fullName: str
    email:Optional [str]= None
    # 💡 FIELD KANNEEN DABALI (Akka MongoDB irraa departmentId dubbisuuf):
    departmentId: Optional[str] = Field(None, alias="department_id")
    department_id: Optional[str] = None
class UserCreate(UserBase):
    password: str = Field(..., min_length=6)
    role: UserRole

class UserLogin(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    password: str
     # =========================================================
# HELPERS
# =========================================================

def normalize_role(role) -> str:
    """
    UserRole enum ykn string ta'us
    frontend/backend keessatti string tokko godha.
    """
    if hasattr(role, "value"):
        return str(role.value)

    return str(role)

def normalize_status(status_value) -> str:
    """
    UserStatus enum ykn string ta'us string godha.
    """
    if hasattr(status_value, "value"):
        return str(status_value.value)

    return str(status_value)

def public_user(user: dict) -> dict:
    """
    Database keessaa passwordHash fi fields sensitive
    frontend'itti akka hin ergamneef user public qopheessa.
    """

    return {
        "_id": str(user["_id"]),
        "fullName": user.get("fullName", ""),
        "email": user.get("email", ""),
        "username": user.get("username"),
        "role": normalize_role(user.get("role", "")),
        "status": normalize_status(user.get("status", "")),
    }

# =========================================================
# AUTHENTICATE USER
# =========================================================

async def authenticate_user(login_input: str, password: str):

    # Email ykn Username dhihaateen search godha (case-insensitive search yoo barbaachise)
    user = await users_collection.find_one({
        "$or": [
            {"email": login_input},
            {"username": login_input}
        ],
        "isDeleted": False,
    })

    if not user:
        return None

    # Field names Database keessatti adda addaa ta'uusuu danda'an kaniin check godha
    password_hash = (
        user.get("hashedPassword") or 
        user.get("passwordHash") or 
        user.get("hashed_password")
    )

    if not password_hash:
        return None

    if not verify_password(password, password_hash):
        return None

    user_status = normalize_status(
        user.get("status", "")
    ).lower()

    if user_status not in ["active", "approved"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not active",
        )

    return user

# =========================================================
# GENERATE TOKEN PAIR
# =========================================================

async def generate_token_pair(
    user_id: str,
    role: str,
):

    role = normalize_role(role)

    # Access token
    access_token = create_access_token({
        "sub": user_id,
        "role": role,
    })

    # Raw refresh value
    raw_refresh = create_refresh_token_value()

    # Hash raw value for DB
    token_hash = hash_token(raw_refresh)

    # JWT refresh token payload
    jti = raw_refresh[:16]

    payload = create_refresh_token_payload(
        user_id,
        jti,
    )

    refresh_token = jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    expires_at = payload["exp"]

    await refresh_tokens_collection.insert_one({
        "userId": user_id,
        "tokenHash": token_hash,
        "expiresAt": expires_at,
        "isRevoked": False,
        "createdAt": datetime.utcnow(),
    })

    return access_token, refresh_token

# =========================================================
# ROTATE REFRESH TOKEN
# =========================================================

async def rotate_refresh_token(old_token: str):

    payload = decode_token(old_token)

    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token type",
        )

    token_hash = hash_token(old_token)

    stored = await refresh_tokens_collection.find_one({
        "tokenHash": token_hash
    })

    if not stored:
        raise HTTPException(
            status_code=401,
            detail="Refresh token not found",
        )

    if stored.get("isRevoked"):
        raise HTTPException(
            status_code=401,
            detail="Refresh token revoked",
        )

    expires_at = stored.get("expiresAt")

    if expires_at and expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=401,
            detail="Refresh token expired",
        )

    # Revoke old token
    await refresh_tokens_collection.update_one(
        {"_id": stored["_id"]},
        {
            "$set": {
                "isRevoked": True
            }
        },
    )

    # Find user
    try:
        user = await users_collection.find_one({
            "_id": ObjectId(stored["userId"])
        })
    except Exception:
        user = None

    if not user:
        raise HTTPException(
            status_code=401,
            detail="User not found",
        )

    user_status = normalize_status(
        user.get("status", "")
    ).lower()

    if user_status not in ["active", "approved"]:
        raise HTTPException(
            status_code=403,
            detail="User account is not active",
        )

    return await generate_token_pair(
        str(user["_id"]),
        normalize_role(user.get("role", "")),
    )

# =========================================================
# REVOKE USER TOKENS
# =========================================================

async def revoke_user_tokens(user_id: str):

    await refresh_tokens_collection.update_many(
        {
            "userId": user_id,
            "isRevoked": False,
        },
        {
            "$set": {
                "isRevoked": True
            }
        },
    )

# =========================================================
# ROUTER
# =========================================================

router = APIRouter(
    tags=["Authentication"]
)

# =========================================================
# STUDENT REGISTRATION
# =========================================================

from app.features.students import register_student

router.post(
    "/register-student",
    status_code=status.HTTP_201_CREATED,
)(register_student)

# =========================================================
# NORMAL USER REGISTRATION
# =========================================================

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(user_data: UserCreate):

    existing = await users_collection.find_one({
        "email": user_data.email
    })

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email already registered",
        )

    password_hash = hash_password(
        user_data.password
    )

    role = normalize_role(user_data.role)

    status_value = (
        UserStatus.PENDING
        if role == normalize_role(UserRole.STUDENT)
        else UserStatus.ACTIVE
    )

    new_user = {
        "fullName": user_data.fullName,
        "email": user_data.email,
        "username": user_data.email,
        "passwordHash": password_hash,
        "role": role,
        "status": status_value,
        "createdAt": datetime.utcnow(),
        "isDeleted": False,
    }

    result = await users_collection.insert_one(
        new_user
    )

    new_user["_id"] = str(
        result.inserted_id
    )

    return UserResponse(**new_user)

# =========================================================
# LOGIN
# =========================================================
# LOGIN
# =========================================================
# =========================================================
# LOGIN
# =========================================================

@router.post("/login", response_model=LoginResponse)
async def login(credentials: UserLogin):
    print("\n================ [DEBUG AUTH START] =======================")

    # =====================================================
    # 1. LOGIN INPUT
    # =====================================================

    login_input = (
        credentials.email
        or credentials.username
        or ""
    ).strip()

    print(f"1. LOGIN ATTEMPT FOR: '{login_input}'")

    if not login_input:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email or username is required.",
        )

    # =====================================================
    # 2. SEARCH USERS COLLECTION
    #    Admin / Department Head / Teacher accounts
    # =====================================================

    user = await users_collection.find_one({
        "$or": [
            {"email": login_input},
            {"username": login_input},
        ],
        "isDeleted": {"$ne": True},
    })

    source_collection = "users"

    # =====================================================
    # 3. SEARCH TEACHERS COLLECTION
    # =====================================================

    if not user:
        user = await teachers_collection.find_one({
            "$or": [
                {"email": login_input},
                {"username": login_input},
            ],
            "isDeleted": {"$ne": True},
        })

        if user:
            source_collection = "teachers"

    # =====================================================
    # 4. SEARCH STUDENTS COLLECTION
    #    Student users collection keessa HIN GALU
    # =====================================================

    if not user:
        user = await students_collection.find_one({
            "$or": [
                {"email": login_input},
                {"username": login_input},
            ],
            "isDeleted": {"$ne": True},
        })

        if user:
            source_collection = "students"

    # =====================================================
    # 5. USER NOT FOUND
    # =====================================================

    if not user:
        print(
            f"❌ AUTH ERROR: '{login_input}' "
            "not found in users, teachers or students."
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
        )

    print(
        f"✅ USER FOUND: "
        f"ID={user.get('_id')} | "
        f"Email={user.get('email')} | "
        f"Role={user.get('role')} | "
        f"SOURCE={source_collection}"
    )

    # =====================================================
    # 6. PASSWORD
    # =====================================================

    db_password = (
        user.get("passwordHash")
        or user.get("hashedPassword")
        or user.get("hashed_password")
        or user.get("password")
        or ""
    )

    db_password = str(db_password).strip()
    user_password = str(credentials.password).strip()

    if not db_password:
        print("❌ AUTH ERROR: Password field not found.")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
        )

    # =====================================================
    # 7. VERIFY PASSWORD
    # =====================================================

    is_valid = False

    try:
        is_valid = verify_password(
            user_password,
            db_password,
        )
    except Exception as e:
        print(f"⚠️ PASSWORD VERIFY ERROR: {e}")

    # Backward compatibility
    if not is_valid and user_password == db_password:
        is_valid = True

    if not is_valid:
        print("❌ AUTH ERROR: Password does not match.")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
        )

    print("✅ AUTH SUCCESS: Password verified.")

    # =====================================================
    # 8. STATUS
    # =====================================================

    user_status = normalize_status(
        user.get("status", "")
    ).lower()

    if user_status not in ["active", "approved"]:
        print(
            f"❌ AUTH ERROR: Account status = {user_status}"
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active",
        )

    # =====================================================
    # 9. ROLE
    # =====================================================

    if source_collection == "students":
        role = UserRole.STUDENT.value
    else:
        role = normalize_role(
            user.get("role", "")
        ).lower().strip()

    # =====================================================
    # 10. USER ID
    # =====================================================

    user_id = str(user["_id"])

    print(f"USER ID       : {user_id}")
    print(f"ROLE          : {role}")
    print(f"SOURCE        : {source_collection}")
    print(f"DEPARTMENT    : {user.get('departmentId')}")
    print(f"LEVEL         : {user.get('currentLevelId')}")

    # =====================================================
    # 11. GENERATE TOKEN
    # =====================================================

    access_token, refresh_token = await generate_token_pair(
        user_id,
        role,
    )

    print(
        f"✅ TOKEN ISSUED: "
        f"User ID={user_id} | Role={role}"
    )

    # =====================================================
    # 12. STUDENT RESPONSE
    # =====================================================

    if source_collection == "students":

        response_user = {
            "_id": user_id,

            "fullName": user.get(
                "full_name",
                user.get("fullName", "")
            ),

            "email": user.get(
                "email",
                ""
            ),

            "username": user.get(
                "username",
                user.get("email", "")
            ),

            "role": role,

            "status": normalize_status(
                user.get("status", "")
            ),

            "studentId": user.get(
                "studentId",
                ""
            ),

            "departmentId": (
                str(user.get("departmentId"))
                if user.get("departmentId") is not None
                else ""
            ),

            "currentLevelId": (
                str(user.get("currentLevelId"))
                if user.get("currentLevelId") is not None
                else ""
            ),
        }

    # =====================================================
    # 13. USERS / TEACHERS RESPONSE
    # =====================================================

    else:

        response_user = {
            "_id": user_id,

            "fullName": user.get(
                "fullName",
                user.get("full_name", "")
            ),

            "email": user.get(
                "email",
                ""
            ),

            "username": user.get(
                "username",
                ""
            ),

            "role": role,

            "status": normalize_status(
                user.get("status", "")
            ),

            "departmentId": (
                str(user.get("departmentId"))
                if user.get("departmentId") is not None
                else ""
            ),

            "courseId": (
                str(user.get("courseId"))
                if user.get("courseId") is not None
                else ""
            ),
        }

    # =====================================================
    # 14. DEBUG
    # =====================================================

    print("📌 LOGIN RESPONSE:")

    for key, value in response_user.items():
        print(f"   {key}: {value}")

    print("===================================================\n")

    # =====================================================
    # 15. FINAL RESPONSE
    # =====================================================

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": response_user,
    }
# ==========================
# REFRESH TOKEN
# =========================================================

@router.post(
    "/refresh",
    response_model=Token,
)
async def refresh_token(
    data: TokenRefresh,
):

    access_token, refresh_token_value = (
        await rotate_refresh_token(
            data.refresh_token
        )
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_value,
        "token_type": "bearer",
    }

# =========================================================
# CURRENT USER / ME
# =========================================================
@router.get("/me")
async def get_me(current_user = Depends(get_current_active_user)):
    # Safely convert current_user to dict regardless of its type
    if isinstance(current_user, dict):
        user_dict = current_user
    elif hasattr(current_user, "model_dump"):
        user_dict = current_user.model_dump()
    elif hasattr(current_user, "__dict__"):
        user_dict = current_user.__dict__
    else:
        user_dict = dict(current_user)

    dept_id = str(user_dict.get("departmentId") or user_dict.get("department_id") or "")

    return {
        "_id": str(user_dict.get("id") or user_dict.get("_id") or ""),
        "fullName": user_dict.get("fullName", ""),
        "username": user_dict.get("username", "") or user_dict.get("email", ""),
        "role": user_dict.get("role", ""),
        "departmentId": dept_id
    }