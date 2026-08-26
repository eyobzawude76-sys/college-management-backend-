from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from app.core.constants import UserRole, UserStatus

class User(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    fullName: str
    email:Optional[str] = None
    passwordHash: str
    role: UserRole
    status: UserStatus = UserStatus.ACTIVE
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: Optional[datetime] = None
    deletedAt: Optional[datetime] = None
    isDeleted: bool = False
    departmentId: Optional[str] = None
    department_id: Optional[str] = None
    studentId: Optional[str] = None
    currentLevelId: Optional[str] = None
    courseId: Optional[str] = None

    class Config:
        populate_by_name = True

class UserResponse(BaseModel):
    id: str = Field(..., alias="_id")
    fullName: str
    email: EmailStr
    role: UserRole
    status: UserStatus
    createdAt: datetime
    
    class Config:
        populate_by_name = True
