
import logging
from datetime import datetime
from typing import Dict, Any, List, Union
from fastapi import APIRouter
from bson import ObjectId

from app.database import (
    marks_collection,
    modules_collection,
    students_collection,
    academic_records_collection,
    committee_reviews_collection,
)

logger = logging.getLogger(__name__)
router = APIRouter()

def get_id_filters(id_str: str) -> List[Union[str, ObjectId]]:
    """ObjectId fi String tajaajila barbaacha database-iif wal-simsiisa."""
    values: List[Union[str, ObjectId]] = [str(id_str)]
    if ObjectId.is_valid(str(id_str)):
        values.append(ObjectId(str(id_str)))
    return values

def calculate_grade_and_points(total_score: float) -> tuple[str, float, str]:
    """Total Score /100 irraa Grade, Grade Point fi Status murteessa."""
    if total_score >= 90:
        return "A+", 4.0, "PASS"
    elif total_score >= 85:
        return "A", 4.0, "PASS"
    elif total_score >= 80:
        return "A-", 3.75, "PASS"
    elif total_score >= 75:
        return "B+", 3.5, "PASS"
    elif total_score >= 70:
        return "B", 3.0, "PASS"
    elif total_score >= 65:
        return "B-", 2.75, "PASS"
    elif total_score >= 60:
        return "C+", 2.5, "PASS"
    elif total_score >= 50:
        return "C", 2.0, "PASS"
    elif total_score >= 45:
        return "C-", 1.75, "PASS"
    elif total_score >= 40:
        return "D", 1.0, "PASS"
    else:
        return "F", 0.0, "FAIL"

async def process_student_level_results(
    student_id: str,
    level_id: str,
    department_id: str,
    reviewer_user_id: str,
) -> Dict[str, Any]:

    now = datetime.utcnow()

    # 1. STUDENT FETCH
    student = await students_collection.find_one({
        "_id": {"$in": get_id_filters(student_id)}
    })

    if not student:
        error_msg = f"❌ Student not found: {student_id}"
        print(error_msg)
        raise ValueError(error_msg)

    full_name = (
        student.get("fullName")
        or f"{student.get('firstName', '')} {student.get('lastName', '')}".strip()
        or "Student"
    )
    student_number = student.get("studentId", "N/A")

    print("\n" + "=" * 85)
    print(f" 🚀 PROCESSING STUDENT: {full_name.upper()} (ID: {student_number})")
    print(f" 🏢 Dept ID: {department_id} | 🎓 Level ID: {level_id}")
    print("=" * 85)

    # 2. ALL MODULES OF LEVEL
    all_level_modules = await modules_collection.find({
        "levelId": {"$in": get_id_filters(level_id)},
        "isDeleted": {"$ne": True},
    }).to_list(length=None)

    # 3. APPROVED / DEPARTMENT-REVIEWED MARKS FETCH
    allowed_statuses = [
        "PENDING_COMMITTEE_REVIEW",
        "pending_committee_review",
        "APPROVED_BY_DEPT",
        "approved_by_dept",
        "APPROVED",
        "approved"
    ]

    student_marks = await marks_collection.find({
        "studentId": {"$in": get_id_filters(student_id)},
        "levelId": {"$in": get_id_filters(level_id)},
        "status": {"$in": allowed_statuses},
        "isDeleted": {"$ne": True},
    }).to_list(length=None)

    # 4. MODULE -> MARK LOOKUP
    marks_lookup: Dict[str, Dict[str, Any]] = {}
    for mark in student_marks:
        module_id = mark.get("moduleId")
        if module_id:
            marks_lookup[str(module_id)] = mark

    # 5. PROCESS ALL MODULES
    processed_modules = []
    total_quality_points = 0.0
    total_credit_hours = 0
    passed_count = 0
    failed_count = 0

    print(f"{'MODULE NAME':<32} | {'INST(70)':<8} | {'IND(30)':<7} | {'TOTAL':<6} | {'GRADE':<5} | {'STATUS':<10}")
    print("-" * 85)

    for module in all_level_modules:
        module_id = str(module["_id"])
        module_name = (
            module.get("moduleName")
            or module.get("name")
            or module.get("moduleCode")
            or module.get("code")
            or "Module"
        )

        raw_credit = module.get("creditHour", 1)
        credit_hour = int(raw_credit) if raw_credit else 1

        mark = marks_lookup.get(module_id)

        if mark:
            institutional = float(mark.get("institutionalScore", mark.get("institutional", mark.get("inst", 0))) or 0)
            industrial = float(mark.get("industrialScore", mark.get("industrial", mark.get("ind", 0))) or 0)
            total_score = institutional + industrial
            is_mark_available = True
        else:
            # Missing module evaluated as 0
            institutional = 0.0
            industrial = 0.0
            total_score = 0.0
            is_mark_available = False

        grade, grade_point, module_status = calculate_grade_and_points(total_score)
        quality_point = credit_hour * grade_point

        if module_status == "PASS":
            passed_count += 1
        else:
            failed_count += 1

        total_quality_points += quality_point
        total_credit_hours += credit_hour

        mark_str_flag = "" if is_mark_available else " (MISSING -> 0)"
        print(f"{module_name[:32]:<32} | {institutional:<8.1f} | {industrial:<7.1f} | {total_score:<6.1f} | {grade:<5} | {module_status}{mark_str_flag}")

        processed_modules.append({
            "moduleId": module_id,
            "moduleName": module_name,
            "creditHour": credit_hour,
            "institutional": institutional,
            "industrial": industrial,
            "totalScore": total_score,
            "grade": grade,
            "gradePoint": grade_point,
            "qualityPoint": quality_point,
            "status": module_status,
            "markAvailable": is_mark_available,
        })

    print("-" * 85)

    # 6. GPA CALCULATION
    gpa = round(total_quality_points / total_credit_hours, 2) if total_credit_hours > 0 else 0.0
    total_modules = len(all_level_modules)

    # 7. OVERALL PROMOTION DECISION
    all_modules_completed = (
        total_modules > 0
        and passed_count == total_modules
        and failed_count == 0
    )

    is_promoted = all_modules_completed and gpa >= 2.0

    if is_promoted:
        overall_status = "COMPETENT"
        action = "PROMOTED"
        reason = "All level modules passed and GPA requirement satisfied."
    else:
        overall_status = "NOT YET COMPETENT"
        action = "REPEAT"
        reason = "One or more level modules failed or missing (evaluated as 0)."

    print("📊 EVALUATION RESULT SUMMARY:")
    print(f" 🔹 Total Credits: {total_credit_hours} | Total Points: {round(total_quality_points, 2)} | Calculated GPA: {gpa}")
    print(f" 🔹 Passed: {passed_count}/{total_modules} | Failed/Missing: {failed_count}")
    print(f" 🏆 Final Decision: {overall_status} ({action})")
    print(f" 📌 Reason: {reason}")

    # 8. SUMMARY RESULT
    summary_result = {
        "studentId": str(student_id),
        "studentNumber": student_number,
        "fullName": full_name,
        "departmentId": str(department_id),
        "levelId": str(level_id),
        "gpa": gpa,
        "passedModules": passed_count,
        "failedModules": failed_count,
        "totalModules": total_modules,
        "totalCredits": total_credit_hours,
        "totalQualityPoints": round(total_quality_points, 2),
        "allModulesCompleted": all_modules_completed,
        "isPromoted": is_promoted,
        "overallStatus": overall_status,
        "committeeRecommendation": {
            "status": overall_status,
            "action": action,
            "reason": reason,
        },
        "modules": processed_modules,
        "generatedAt": now,
    }

    # 9. COMMITTEE REVIEW RECORD UPDATE
    await committee_reviews_collection.update_one(
        {"studentId": str(student_id), "levelId": str(level_id)},
        {
            "$set": {
                **summary_result,
                "status": "READY_FOR_COMMITTEE",
                "departmentApproved": True,
                "departmentApprovedBy": str(reviewer_user_id),
                "departmentApprovedAt": now,
                "updatedAt": now,
            },
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )

    # 10. ACADEMIC RECORD UPDATE
    await academic_records_collection.update_one(
        {"studentId": str(student_id), "levelId": str(level_id)},
        {
            "$set": {
                **summary_result,
                "status": "READY_FOR_COMMITTEE",
                "departmentApproved": True,
                "departmentApprovedBy": str(reviewer_user_id),
                "departmentApprovedAt": now,
                "updatedAt": now,
            },
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
    print(" ✅ Saved to committee_reviews_collection & academic_records_collection")
    print("=" * 85 + "\n")

    return summary_result

# ============================================================
# ⚡ AUTOMATIC ALL-LEVEL STUDENTS PROCESSOR (TRGGERED BY DEPT HEAD)
# ============================================================
async def process_all_students_in_level(
    level_id: str,
    department_id: str,
    reviewer_user_id: str
) -> List[Dict[str, Any]]:
    """
    Department Head yeroo Level Approve godhu Barattoota Level sana keessa jiran
    HUNDA maqaa isaaniitiin (A-Z) tartiibsee Grade Engine automatic-iin irratti hojjeta.
    """
    # Level sana keessatti barattoota mark qaban HUNDA adda baasuu
    unique_student_ids = await marks_collection.distinct(
        "studentId",
        {"levelId": {"$in": get_id_filters(level_id)}, "departmentId": {"$in": get_id_filters(department_id)}}
    )

    # Barattoota Database irraa aadaa baasnee Maqaa isaaniitiin Sort (A-Z) gochuu
    students_list = []
    for s_id in unique_student_ids:
        st = await students_collection.find_one({"_id": {"$in": get_id_filters(s_id)}})
        if st:
            name = st.get("fullName") or f"{st.get('firstName', '')} {st.get('lastName', '')}".strip() or "Student"
            students_list.append({"id": str(s_id), "name": name})

    # Tartiiba Maqaatiin Sort Godhii
    students_list.sort(key=lambda x: x["name"].lower())

    print("\n" + "🔥" * 45)
    print(f" ⚙️ AUTOMATIC GRADE ENGINE EXECUTION FOR {len(students_list)} STUDENTS IN LEVEL: {level_id}")
    print("🔥" * 45)

    results = []
    for st in students_list:
        try:
            res = await process_student_level_results(
                student_id=st["id"],
                level_id=level_id,
                department_id=department_id,
                reviewer_user_id=reviewer_user_id
            )
            results.append(res)
        except Exception as e:
            print(f"❌ Error processing student {st['name']} ({st['id']}): {str(e)}")

    print("🔥" * 45)
    print(f" SUCCESS: ALL {len(results)} STUDENTS PROCESSED AUTOMATICALLY!")
    print("🔥" * 45 + "\n")

    return results

# Backwards compatibility for marks.py imports
def calculate_grade(total_score: float):
    grade, grade_point, status = calculate_grade_and_points(total_score)
    return {"grade": grade, "gradePoint": grade_point, "status": status}

def process_student_result(modules_data: list):
    processed = []
    total_credits = 0
    total_qp = 0
    failed = 0
    passed = 0

    for mod in modules_data:
        inst = float(mod.get("institutional", 0) or 0)
        ind = float(mod.get("industrial", 0) or 0)
        tot = inst + ind
        ch = int(mod.get("creditHour", 1) or 1)

        grade, gp, status = calculate_grade_and_points(tot)
        qp = ch * gp

        if status == "PASS":
            passed += 1
        else:
            failed += 1

        total_credits += ch
        total_qp += qp

        processed.append({
            **mod,
            "totalScore": tot,
            "grade": grade,
            "gradePoint": gp,
            "qualityPoint": qp,
            "status": status
        })

    gpa = round(total_qp / total_credits, 2) if total_credits > 0 else 0.0
    return {
        "modules": processed,
        "gpa": gpa,
        "passedModules": passed,
        "failedModules": failed,
        "isPromoted": failed == 0
    }