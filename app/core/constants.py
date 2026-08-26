from enum import Enum



class UserRole(str, Enum):
    ADMIN = "admin"
    STUDENT = "student"
    TEACHER = "teacher"
    DEPARTMENT_HEAD = "department_head"
    COMMITTEE = "committee"
    RECORD_OFFICE = "record_office"

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    APPROVED="approved"