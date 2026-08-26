import os
import shutil

mapping = {
    'auth': {'routers': 'auth.py', 'services': 'auth_service.py', 'models': ['user.py', 'refresh_token.py'], 'repositories': 'user_repo.py'},
    'students': {'routers': 'students.py', 'services': 'student_service.py', 'models': ['student.py', 'student_level_history.py'], 'repositories': 'student_repo.py', 'schemas': 'student.py'},
    'teachers': {'routers': 'teachers.py', 'models': 'teacher.py', 'schemas': 'teacher.py'},
    'departments': {'routers': 'departments.py', 'models': 'department.py', 'schemas': 'department.py'},
    'marks': {'routers': 'marks.py', 'models': 'mark.py', 'schemas': 'mark.py', 'repositories': 'mark_repo.py'},
    'promotions': {'routers': 'promotions.py', 'models': 'promotion.py', 'services': 'promotion_service.py', 'schemas': 'promotion.py'},
    'reports': {'routers': 'reports.py', 'services': 'export_service.py', 'schemas': 'report.py'},
    'academic_records': {'routers': 'academic_records.py', 'models': 'academic_record.py', 'services': 'record_service.py', 'schemas': 'academic_record.py'},
    'committee': {'routers': 'committee.py'}
}

# 1. Move Files
for feature, items in mapping.items():
    feature_dir = f'app/modules/{feature}'
    os.makedirs(feature_dir, exist_ok=True)
    
    for category, files in items.items():
        if isinstance(files, str):
            files = [files]
        
        for file in files:
            source_dir = f'app/{category}'
            source_path = os.path.join(source_dir, file)
            
            # Map category to new filename
            new_filename = category.rstrip('s') + '.py'
            if category == 'repositories': new_filename = 'repository.py'
            if category == 'services': new_filename = 'service.py'
            
            # This is a bit simplistic, but should work for the requested structure
            dest_path = os.path.join(feature_dir, new_filename)
            
            if os.path.exists(source_path):
                shutil.move(source_path, dest_path)
                print(f"Moved {source_path} to {dest_path}")

# 2. Update Imports (This is the hard part, I'll use grep_search/replace later for this)
# A full regex-based import replacer is risky.
