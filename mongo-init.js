db = db.getSiblingDB('college_academic_db');

// Create indexes
db.users.createIndex({ "email": 1 }, { unique: true });
db.users.createIndex({ "role": 1 });
db.users.createIndex({ "status": 1 });
db.users.createIndex({ "isDeleted": 1 });

db.departments.createIndex({ "name": 1 }, { unique: true, partialFilterExpression: { "isDeleted": false } });
db.departments.createIndex({ "isDeleted": 1 });

db.levels.createIndex({ "departmentId": 1, "levelNumber": 1 }, { unique: true, partialFilterExpression: { "isDeleted": false } });
db.levels.createIndex({ "isDeleted": 1 });

db.modules.createIndex({ "moduleCode": 1 }, { unique: true, partialFilterExpression: { "isDeleted": false } });
db.modules.createIndex({ "levelId": 1 });
db.modules.createIndex({ "departmentId": 1 });
db.modules.createIndex({ "pin": 1 });

db.students.createIndex({ "userId": 1 }, { unique: true });
db.students.createIndex({ "studentId": 1 }, { unique: true, sparse: true });
db.students.createIndex({ "departmentId": 1, "currentLevelId": 1 });
db.students.createIndex({ "status": 1 });

db.teachers.createIndex({ "userId": 1 }, { unique: true });
db.teachers.createIndex({ "departmentId": 1 });

db.moduleAssignments.createIndex({ "moduleId": 1, "isActive": 1 });
db.moduleAssignments.createIndex({ "teacherId": 1, "isActive": 1 });

db.marks.createIndex({ "studentId": 1, "moduleId": 1 }, { unique: true });
db.marks.createIndex({ "moduleId": 1, "status": 1 });
db.marks.createIndex({ "enteredBy": 1, "status": 1 });
db.marks.createIndex({ "status": 1 });

db.academicRecords.createIndex({ "studentId": 1, "status": 1 });
db.academicRecords.createIndex({ "studentId": 1, "levelId": 1 }, { unique: true, partialFilterExpression: { "status": "active" } });

db.promotions.createIndex({ "studentId": 1 });
db.promotions.createIndex({ "status": 1 });
db.promotions.createIndex({ "createdAt": -1 });

db.auditLogs.createIndex({ "userId": 1, "timestamp": -1 });
db.auditLogs.createIndex({ "action": 1, "timestamp": -1 });
db.auditLogs.createIndex({ "entityType": 1, "entityId": 1 });
db.auditLogs.createIndex({ "timestamp": -1 });

print("All indexes created successfully");