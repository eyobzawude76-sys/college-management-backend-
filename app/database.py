from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client = AsyncIOMotorClient(settings.MONGODB_URL)
db = client[settings.DATABASE_NAME]

# Collections
users_collection = db.users
refresh_tokens_collection = db.refresh_tokens
departments_collection = db.departments
courses_collection = db.courses
levels_collection = db.levels
record_office_vaults_collection=db.record_office_vaults_collection
modules_collection = db.modules
students_collection = db.students
department_reviews_collection=db.department_reviews
teachers_collection = db.teachers
module_assignments_collection = db.module_assignments
marks_collection = db.marks
grading_history_collection=db.grading_history
promotions_collection = db.promotions
academic_records_collection = db.academic_records
record_office_vaults_collection = db.record_office_vaults
audit_logs_collection = db.audit_log
committee_history_collection = db.committee_history
committee_reviews_collection = db["committee_reviews"] # yookaan db.get_collection("committee_reviews")