from functools import wraps
from fastapi import HTTPException, status

def require_role(allowed_roles: list):
    from app.core.constants import UserRole

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required"
                )

            # 1. Role current_user keessaa fudhachuu (dict ykn object)
            if isinstance(current_user, dict):
                user_role = current_user.get("role", "")
            else:
                user_role = getattr(current_user, "role", "")

            # Role Enum yoo ta'e value isaa fudhachuu
            if hasattr(user_role, "value"):
                user_role = user_role.value

            user_role_str = str(user_role).lower().strip()

            # 2. allowed_roles gara lowercase string-tti convert gochuu
            formatted_allowed = []
            for r in allowed_roles:
                role_val = r.value if hasattr(r, "value") else r
                formatted_allowed.append(str(role_val).lower().strip())
         
# DEBUG
            print("========== RBAC DEBUG ==========")
            print("CURRENT USER:", current_user)
            print("USER ROLE:", user_role)
            print("USER ROLE STRING:", user_role_str)
            print("ALLOWED ROLES:", formatted_allowed)
            print("================================")

            # 3. Role validation check
            if user_role_str not in formatted_allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied. Required roles: {formatted_allowed}"
                )

            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator